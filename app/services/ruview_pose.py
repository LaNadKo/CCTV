"""Stabilized pose feed from the official RuView sensing server."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import hypot
from typing import Any

import httpx

from app.config import settings
from app.schemas.ruview import RuViewPoseBox, RuViewPoseKeypoint, RuViewPosePerson, RuViewPoseSnapshot
from app.services.ruview_upstream import _candidate_base_urls


_ASSIGNMENT_RADIUS_PX = 180.0
_POSE_ALPHA = 0.42
_BOX_ALPHA = 0.35
_MAX_STALE_SECONDS = 2.5


@dataclass
class _RawPose:
    ruview_id: str | None
    confidence: float
    bbox: RuViewPoseBox | None
    keypoints: list[RuViewPoseKeypoint]
    zone: str | None


@dataclass
class _StablePose:
    stable_id: str
    ruview_id: str | None
    confidence: float
    bbox: RuViewPoseBox | None
    keypoints: list[RuViewPoseKeypoint]
    zone: str | None
    last_seen_at: datetime
    miss_count: int = 0
    raw_seen_count: int = 1
    history_centers: list[tuple[float, float]] = field(default_factory=list)


class _RuViewPoseStabilizer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tracks: dict[str, _StablePose] = {}
        self._next_id = 1

    def update(self, raw_persons: list[_RawPose], now: datetime) -> list[RuViewPosePerson]:
        with self._lock:
            assigned: set[str] = set()
            next_tracks = dict(self._tracks)

            for raw in raw_persons:
                track_key = self._match_track(raw, assigned)
                if track_key is None:
                    track_key = f"rvp-{self._next_id}"
                    self._next_id += 1
                    next_tracks[track_key] = _StablePose(
                        stable_id=track_key,
                        ruview_id=raw.ruview_id,
                        confidence=raw.confidence,
                        bbox=raw.bbox,
                        keypoints=raw.keypoints,
                        zone=raw.zone,
                        last_seen_at=now,
                    )
                else:
                    previous = next_tracks[track_key]
                    next_tracks[track_key] = _smooth_pose(previous, raw, now)
                assigned.add(track_key)

            for key, track in list(next_tracks.items()):
                age = (now - track.last_seen_at).total_seconds()
                if age > _MAX_STALE_SECONDS:
                    next_tracks.pop(key, None)
                elif key not in assigned:
                    track.miss_count += 1

            self._tracks = next_tracks
            return [
                _to_schema(track)
                for track in sorted(self._tracks.values(), key=lambda item: item.stable_id)
                if (now - track.last_seen_at).total_seconds() <= _MAX_STALE_SECONDS
            ]

    def _match_track(self, raw: _RawPose, assigned: set[str]) -> str | None:
        if raw.ruview_id is not None:
            for key, track in self._tracks.items():
                if key not in assigned and track.ruview_id == raw.ruview_id:
                    return key

        raw_center = _pose_center(raw.bbox, raw.keypoints)
        if raw_center is None:
            return None

        best_key: str | None = None
        best_distance = float("inf")
        for key, track in self._tracks.items():
            if key in assigned:
                continue
            center = _pose_center(track.bbox, track.keypoints)
            if center is None:
                continue
            distance = hypot(raw_center[0] - center[0], raw_center[1] - center[1])
            if distance < best_distance:
                best_distance = distance
                best_key = key

        if best_distance <= _ASSIGNMENT_RADIUS_PX:
            return best_key
        return None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric


def _to_int(value: Any, default: int = 0) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return default
    return numeric


def _normalize_bbox(raw: Any) -> RuViewPoseBox | None:
    if not isinstance(raw, dict):
        return None
    width = _to_float(raw.get("width"))
    height = _to_float(raw.get("height"))
    if width <= 0 or height <= 0:
        return None
    return RuViewPoseBox(
        x=_to_float(raw.get("x")),
        y=_to_float(raw.get("y")),
        width=width,
        height=height,
    )


def _normalize_keypoints(raw: Any) -> list[RuViewPoseKeypoint]:
    if not isinstance(raw, list):
        return []
    keypoints: list[RuViewPoseKeypoint] = []
    for index, item in enumerate(raw):
        if isinstance(item, dict):
            keypoints.append(
                RuViewPoseKeypoint(
                    name=str(item.get("name") or f"kp{index}"),
                    x=_to_float(item.get("x")),
                    y=_to_float(item.get("y")),
                    z=_to_float(item.get("z")) if item.get("z") is not None else None,
                    confidence=max(0.0, min(_to_float(item.get("confidence"), 1.0), 1.0)),
                )
            )
        elif isinstance(item, list) and len(item) >= 2:
            keypoints.append(
                RuViewPoseKeypoint(
                    name=f"kp{index}",
                    x=_to_float(item[0]),
                    y=_to_float(item[1]),
                    z=_to_float(item[2]) if len(item) >= 3 else None,
                    confidence=max(0.0, min(_to_float(item[3], 1.0) if len(item) >= 4 else 1.0, 1.0)),
                )
            )
    return keypoints


def _normalize_person(raw: Any) -> _RawPose | None:
    if not isinstance(raw, dict):
        return None
    bbox = _normalize_bbox(raw.get("bbox"))
    keypoints = _normalize_keypoints(raw.get("keypoints"))
    if bbox is None and not keypoints:
        return None
    confidence = max(0.0, min(_to_float(raw.get("confidence"), 0.0), 1.0))
    ruview_id = raw.get("id")
    return _RawPose(
        ruview_id=None if ruview_id is None else str(ruview_id),
        confidence=confidence,
        bbox=bbox,
        keypoints=keypoints,
        zone=str(raw.get("zone")) if raw.get("zone") is not None else None,
    )


def _pose_center(bbox: RuViewPoseBox | None, keypoints: list[RuViewPoseKeypoint]) -> tuple[float, float] | None:
    if bbox is not None:
        return bbox.x + bbox.width / 2.0, bbox.y + bbox.height / 2.0
    visible = [point for point in keypoints if point.confidence is None or point.confidence >= 0.25]
    if not visible:
        return None
    return (
        sum(point.x for point in visible) / len(visible),
        sum(point.y for point in visible) / len(visible),
    )


def _lerp(old: float, new: float, alpha: float) -> float:
    return old + (new - old) * alpha


def _smooth_box(old: RuViewPoseBox | None, new: RuViewPoseBox | None) -> RuViewPoseBox | None:
    if old is None:
        return new
    if new is None:
        return old
    return RuViewPoseBox(
        x=_lerp(old.x, new.x, _BOX_ALPHA),
        y=_lerp(old.y, new.y, _BOX_ALPHA),
        width=_lerp(old.width, new.width, _BOX_ALPHA),
        height=_lerp(old.height, new.height, _BOX_ALPHA),
    )


def _smooth_keypoints(
    old_points: list[RuViewPoseKeypoint],
    new_points: list[RuViewPoseKeypoint],
) -> list[RuViewPoseKeypoint]:
    old_by_name = {point.name or f"kp{index}": point for index, point in enumerate(old_points)}
    smoothed: list[RuViewPoseKeypoint] = []
    for index, point in enumerate(new_points):
        key = point.name or f"kp{index}"
        previous = old_by_name.get(key)
        if previous is None:
            smoothed.append(point)
            continue
        smoothed.append(
            RuViewPoseKeypoint(
                name=point.name,
                x=_lerp(previous.x, point.x, _POSE_ALPHA),
                y=_lerp(previous.y, point.y, _POSE_ALPHA),
                z=_lerp(previous.z, point.z, _POSE_ALPHA) if previous.z is not None and point.z is not None else point.z,
                confidence=max(previous.confidence or 0.0, point.confidence or 0.0),
            )
        )
    return smoothed


def _smooth_pose(previous: _StablePose, raw: _RawPose, now: datetime) -> _StablePose:
    bbox = _smooth_box(previous.bbox, raw.bbox)
    keypoints = _smooth_keypoints(previous.keypoints, raw.keypoints)
    center = _pose_center(bbox, keypoints)
    history = list(previous.history_centers[-5:])
    if center is not None:
        history.append(center)
    return _StablePose(
        stable_id=previous.stable_id,
        ruview_id=raw.ruview_id or previous.ruview_id,
        confidence=_lerp(previous.confidence, raw.confidence, 0.32),
        bbox=bbox,
        keypoints=keypoints,
        zone=raw.zone or previous.zone,
        last_seen_at=now,
        miss_count=0,
        raw_seen_count=previous.raw_seen_count + 1,
        history_centers=history,
    )


def _to_schema(track: _StablePose) -> RuViewPosePerson:
    return RuViewPosePerson(
        stable_id=track.stable_id,
        ruview_id=track.ruview_id,
        confidence=track.confidence,
        bbox=track.bbox,
        keypoints=track.keypoints,
        zone=track.zone,
        last_seen_at=track.last_seen_at,
    )


def _format_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{exc.response.status_code} from {exc.request.url}"
    if isinstance(exc, httpx.RequestError):
        return f"{exc.__class__.__name__}: {exc.request.url}"
    return str(exc)


async def _fetch_pose_current() -> tuple[str, dict[str, Any]]:
    urls = _candidate_base_urls()
    timeout_seconds = max(0.2, float(settings.ruview_upstream_timeout_seconds))
    timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 0.5))
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for base_url in urls:
            try:
                response = await client.get(f"{base_url}/api/v1/pose/current")
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict):
                    return base_url, data
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
    raise RuntimeError(_format_error(last_error) if last_error else "No RuView upstream URLs configured")


_stabilizer = _RuViewPoseStabilizer()


async def get_ruview_pose_snapshot() -> RuViewPoseSnapshot:
    now = datetime.now(timezone.utc)
    try:
        _base_url, payload = await _fetch_pose_current()
    except Exception as exc:
        return RuViewPoseSnapshot(
            generated_at=now,
            reachable=False,
            persons=[],
            error=f"RuView pose unavailable: {exc}",
        )

    raw_items = payload.get("persons", [])
    if not isinstance(raw_items, list):
        raw_items = []
    raw_persons = [person for person in (_normalize_person(item) for item in raw_items) if person is not None]
    persons = _stabilizer.update(raw_persons, now)
    return RuViewPoseSnapshot(
        generated_at=now,
        reachable=True,
        source=str(payload.get("source")) if payload.get("source") is not None else None,
        total_persons=max(_to_int(payload.get("total_persons")), len(persons)),
        persons=persons,
    )
