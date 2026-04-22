from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.schemas.ruview import (
    RuViewPoseBox,
    RuViewPoseKeypoint,
    RuViewPosePerson,
    RuViewPoseSnapshot,
)
from app.services.ruview_bridge import has_recent_ruview_csi
from app.services.ruview_rf_model import get_calibrated_pose_snapshot
from app.services.ruview_upstream import candidate_base_urls

_COCO_KEYPOINT_NAMES = [
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
]

_POSE_ALPHA = 0.42
_BOX_ALPHA = 0.35
_ASSIGNMENT_RADIUS_PX = 180.0
_TRACK_MAX_AGE_SECONDS = 2.5


@dataclass
class _PoseTrack:
    track_id: str
    raw_id: str | None
    person: RuViewPosePerson
    center_x: float | None
    center_y: float | None
    updated_at: float


_tracks: dict[str, _PoseTrack] = {}
_next_track_id = 1


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
        if math.isfinite(number):
            return number
    except (TypeError, ValueError):
        return None
    return None


def _bbox_from_raw(raw: Any) -> RuViewPoseBox | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        x = _to_float(raw.get("x") or raw.get("left"))
        y = _to_float(raw.get("y") or raw.get("top"))
        width = _to_float(raw.get("width") or raw.get("w"))
        height = _to_float(raw.get("height") or raw.get("h"))
        if width is None and raw.get("right") is not None and x is not None:
            width = (_to_float(raw.get("right")) or x) - x
        if height is None and raw.get("bottom") is not None and y is not None:
            height = (_to_float(raw.get("bottom")) or y) - y
    elif isinstance(raw, (list, tuple)) and len(raw) >= 4:
        x, y, width, height = (_to_float(raw[0]), _to_float(raw[1]), _to_float(raw[2]), _to_float(raw[3]))
    else:
        return None
    if x is None or y is None or width is None or height is None:
        return None
    return RuViewPoseBox(x=x, y=y, width=max(0.0, width), height=max(0.0, height))


def _keypoint_from_raw(raw: Any, index: int) -> RuViewPoseKeypoint | None:
    name = _COCO_KEYPOINT_NAMES[index] if index < len(_COCO_KEYPOINT_NAMES) else f"kp_{index}"
    if isinstance(raw, dict):
        x = _to_float(raw.get("x"))
        y = _to_float(raw.get("y"))
        confidence = _to_float(raw.get("confidence") or raw.get("score") or raw.get("c"))
        visible_raw = raw.get("visible")
        if "name" in raw and raw["name"]:
            name = str(raw["name"])
    elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
        x = _to_float(raw[0])
        y = _to_float(raw[1])
        confidence = _to_float(raw[2]) if len(raw) >= 3 else None
        visible_raw = raw[3] if len(raw) >= 4 else None
    else:
        return None
    if x is None or y is None:
        return None
    visible = True
    if isinstance(visible_raw, bool):
        visible = visible_raw
    elif confidence is not None:
        visible = confidence > 0.05
    return RuViewPoseKeypoint(name=name, x=x, y=y, confidence=confidence, visible=visible)


def _keypoints_from_raw(raw: Any) -> list[RuViewPoseKeypoint]:
    if not raw:
        return []
    if isinstance(raw, dict):
        ordered = []
        for index, name in enumerate(_COCO_KEYPOINT_NAMES):
            item = raw.get(name)
            if item is not None:
                point = _keypoint_from_raw({**item, "name": name} if isinstance(item, dict) else item, index)
                if point:
                    ordered.append(point)
        if ordered:
            return ordered
        raw = list(raw.values())
    points = []
    for index, item in enumerate(raw):
        point = _keypoint_from_raw(item, index)
        if point:
            points.append(point)
    return points


def _center(person: RuViewPosePerson) -> tuple[float | None, float | None]:
    if person.bbox:
        return person.bbox.x + person.bbox.width / 2, person.bbox.y + person.bbox.height / 2
    visible_points = [point for point in person.keypoints if point.visible]
    if not visible_points:
        return None, None
    return (
        sum(point.x for point in visible_points) / len(visible_points),
        sum(point.y for point in visible_points) / len(visible_points),
    )


def _smooth_value(old: float | None, new: float, alpha: float) -> float:
    if old is None:
        return new
    return old * (1.0 - alpha) + new * alpha


def _smooth_person(old: RuViewPosePerson, new: RuViewPosePerson) -> RuViewPosePerson:
    old_by_name = {point.name: point for point in old.keypoints}
    keypoints = []
    for point in new.keypoints:
        previous = old_by_name.get(point.name)
        if previous:
            keypoints.append(
                RuViewPoseKeypoint(
                    name=point.name,
                    x=_smooth_value(previous.x, point.x, _POSE_ALPHA),
                    y=_smooth_value(previous.y, point.y, _POSE_ALPHA),
                    confidence=point.confidence if point.confidence is not None else previous.confidence,
                    visible=point.visible,
                )
            )
        else:
            keypoints.append(point)

    bbox = new.bbox
    if old.bbox and new.bbox:
        bbox = RuViewPoseBox(
            x=_smooth_value(old.bbox.x, new.bbox.x, _BOX_ALPHA),
            y=_smooth_value(old.bbox.y, new.bbox.y, _BOX_ALPHA),
            width=_smooth_value(old.bbox.width, new.bbox.width, _BOX_ALPHA),
            height=_smooth_value(old.bbox.height, new.bbox.height, _BOX_ALPHA),
        )
    return RuViewPosePerson(
        track_id=old.track_id,
        source_id=new.source_id,
        confidence=new.confidence if new.confidence is not None else old.confidence,
        bbox=bbox,
        keypoints=keypoints,
    )


def _assign_track(person: RuViewPosePerson, now: float) -> RuViewPosePerson:
    global _next_track_id
    raw_id = person.source_id
    center_x, center_y = _center(person)

    expired = [track_id for track_id, track in _tracks.items() if now - track.updated_at > _TRACK_MAX_AGE_SECONDS]
    for track_id in expired:
        _tracks.pop(track_id, None)

    matched: _PoseTrack | None = None
    if raw_id:
        for track in _tracks.values():
            if track.raw_id == raw_id:
                matched = track
                break

    if matched is None and center_x is not None and center_y is not None:
        best_distance = _ASSIGNMENT_RADIUS_PX
        for track in _tracks.values():
            if track.center_x is None or track.center_y is None:
                continue
            distance = math.hypot(center_x - track.center_x, center_y - track.center_y)
            if distance < best_distance:
                matched = track
                best_distance = distance

    if matched is None:
        track_id = f"rv-{_next_track_id}"
        _next_track_id += 1
        person.track_id = track_id
        _tracks[track_id] = _PoseTrack(
            track_id=track_id,
            raw_id=raw_id,
            person=person,
            center_x=center_x,
            center_y=center_y,
            updated_at=now,
        )
        return person

    smoothed = _smooth_person(matched.person, person)
    smoothed.track_id = matched.track_id
    matched.raw_id = raw_id or matched.raw_id
    matched.person = smoothed
    matched.center_x, matched.center_y = _center(smoothed)
    matched.updated_at = now
    return smoothed


def _person_from_raw(raw: Any, index: int) -> RuViewPosePerson | None:
    if not isinstance(raw, dict):
        return None
    source_id = raw.get("track_id") or raw.get("id") or raw.get("person_id")
    bbox = _bbox_from_raw(raw.get("bbox") or raw.get("box") or raw.get("bounding_box"))
    keypoints = _keypoints_from_raw(raw.get("keypoints") or raw.get("pose") or raw.get("joints"))
    confidence = _to_float(raw.get("confidence") or raw.get("score"))
    if not bbox and not keypoints:
        return None
    return RuViewPosePerson(
        track_id=f"raw-{index}",
        source_id=str(source_id) if source_id is not None else None,
        confidence=confidence,
        bbox=bbox,
        keypoints=keypoints,
    )


def _extract_persons(payload: Any) -> list[RuViewPosePerson]:
    if not isinstance(payload, dict):
        return []
    raw_items = (
        payload.get("persons")
        or payload.get("people")
        or payload.get("poses")
        or payload.get("detections")
        or payload.get("results")
    )
    if raw_items is None and (payload.get("keypoints") or payload.get("pose")):
        raw_items = [payload]
    if isinstance(raw_items, dict):
        raw_items = list(raw_items.values())
    if not isinstance(raw_items, list):
        return []

    now = time.monotonic()
    persons = []
    for index, item in enumerate(raw_items):
        person = _person_from_raw(item, index)
        if person:
            persons.append(_assign_track(person, now))
    return persons


def _payload_source(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("source") or "").strip()


def _is_simulated_source(source: str) -> bool:
    lowered = source.lower()
    return lowered == "simulated" or lowered.startswith("simulate")


async def get_ruview_pose_snapshot() -> RuViewPoseSnapshot:
    if not settings.ruview_upstream_enabled:
        return RuViewPoseSnapshot(
            reachable=False,
            camera_aligned=False,
            overlay_allowed=False,
            error="RuView upstream disabled",
        )
    if settings.ruview_require_live_csi_for_pose and not has_recent_ruview_csi():
        return RuViewPoseSnapshot(
            reachable=False,
            camera_aligned=False,
            overlay_allowed=False,
            error="Нет live CSI от ESP32, симуляция RuView скрыта",
        )

    calibrated_snapshot = get_calibrated_pose_snapshot()
    if calibrated_snapshot is not None:
        return calibrated_snapshot

    timeout = httpx.Timeout(settings.ruview_upstream_timeout_seconds)
    last_error: str | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for base_url in candidate_base_urls():
            started = time.perf_counter()
            try:
                response = await client.get(f"{base_url}/api/v1/pose/current")
                response.raise_for_status()
                payload = response.json()
                latency_ms = round((time.perf_counter() - started) * 1000, 1)
                payload_source = _payload_source(payload)
                captured_at = datetime.now(timezone.utc)
                if _is_simulated_source(payload_source):
                    return RuViewPoseSnapshot(
                        reachable=False,
                        source_url=base_url,
                        source_kind=payload_source or None,
                        captured_at=captured_at,
                        latency_ms=latency_ms,
                        camera_aligned=False,
                        overlay_allowed=False,
                        error="RuView sidecar работает в simulated mode; overlay отключён",
                    )
                if not settings.ruview_allow_uncalibrated_pose_overlay:
                    return RuViewPoseSnapshot(
                        reachable=False,
                        source_url=base_url,
                        source_kind=payload_source or None,
                        captured_at=captured_at,
                        latency_ms=latency_ms,
                        camera_aligned=False,
                        overlay_allowed=False,
                        error="RuView RF активен, но camera-aligned overlay отключён",
                    )
                persons = _extract_persons(payload)
                return RuViewPoseSnapshot(
                    reachable=True,
                    source_url=base_url,
                    source_kind=payload_source or None,
                    captured_at=captured_at,
                    latency_ms=latency_ms,
                    camera_aligned=False,
                    overlay_allowed=False,
                    persons=persons,
                )
            except Exception as exc:
                last_error = str(exc)
    return RuViewPoseSnapshot(
        reachable=False,
        camera_aligned=False,
        overlay_allowed=False,
        error=last_error or "No RuView upstream URL configured",
    )


def reset_ruview_pose_tracks() -> None:
    global _next_track_id
    _tracks.clear()
    _next_track_id = 1
