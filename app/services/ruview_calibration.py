from __future__ import annotations

import base64
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings

_ROOT = Path("calibration_datasets")
_AUTO_ROOT = _ROOT / "auto"


@dataclass
class _Session:
    session_id: str
    label: str
    scenario: str
    notes: str | None
    directory: Path
    started_at: datetime
    deadline_monotonic: float | None
    csi_file: Any
    camera_file: Any
    csi_samples: int = 0
    camera_samples: int = 0
    latest_tracks: int = 0
    stopped_at: datetime | None = None


_lock = threading.RLock()
_session: _Session | None = None
_auto_session: _Session | None = None
_last_manifest: dict[str, Any] | None = None
_latest_camera_samples: dict[int, dict[str, Any]] = {}
_latest_camera_track_samples: dict[int, dict[str, Any]] = {}
_auto_last_camera_monotonic = 0.0


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip())
    return normalized.strip("-")[:48] or "session"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _write_jsonl(handle: Any, payload: dict[str, Any]) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False, default=_json_default) + "\n")


def _close_session_locked(stopped_at: datetime | None = None) -> dict[str, Any]:
    global _session, _last_manifest
    if _session is None:
        return _manifest_locked(active=False)
    _session.stopped_at = stopped_at or _utc_now()
    manifest = _manifest_locked(active=False)
    for handle in (_session.csi_file, _session.camera_file):
        try:
            handle.flush()
            handle.close()
        except Exception:
            pass
    (_session.directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    _last_manifest = manifest
    _session = None
    return manifest


def _manifest_for_session(session: _Session, active: bool) -> dict[str, Any]:
    now = _utc_now()
    return {
        "active": bool(active),
        "session_id": session.session_id,
        "label": session.label,
        "scenario": session.scenario,
        "notes": session.notes,
        "directory": str(session.directory),
        "started_at": session.started_at,
        "stopped_at": session.stopped_at,
        "duration_seconds": round(((session.stopped_at or now) - session.started_at).total_seconds(), 3),
        "csi_samples": session.csi_samples,
        "camera_samples": session.camera_samples,
        "latest_tracks": session.latest_tracks,
    }


def _close_auto_session_locked(stopped_at: datetime | None = None) -> None:
    global _auto_session
    if _auto_session is None:
        return
    _auto_session.stopped_at = stopped_at or _utc_now()
    manifest = _manifest_for_session(_auto_session, active=False)
    for handle in (_auto_session.csi_file, _auto_session.camera_file):
        try:
            handle.flush()
            handle.close()
        except Exception:
            pass
    (_auto_session.directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    _auto_session = None


def _maybe_auto_training_stop_locked() -> None:
    if _auto_session is None or _auto_session.deadline_monotonic is None:
        return
    if time.monotonic() >= _auto_session.deadline_monotonic:
        _close_auto_session_locked()


def _ensure_auto_session_locked() -> _Session | None:
    global _auto_session
    if not settings.ruview_auto_training_enabled:
        _close_auto_session_locked()
        return None
    _maybe_auto_training_stop_locked()
    if _auto_session is not None:
        return _auto_session

    started_at = _utc_now()
    session_id = f"{started_at.strftime('%Y%m%d_%H%M%S')}_auto-good-scenes"
    directory = _AUTO_ROOT / session_id
    directory.mkdir(parents=True, exist_ok=True)
    duration = max(60.0, float(settings.ruview_auto_training_session_seconds))
    _auto_session = _Session(
        session_id=session_id,
        label="auto-good-scenes",
        scenario="camera-skeleton-plus-csi",
        notes="Auto-collected only when camera skeleton quality is high enough.",
        directory=directory,
        started_at=started_at,
        deadline_monotonic=time.monotonic() + duration,
        csi_file=(directory / "csi.jsonl").open("a", encoding="utf-8", buffering=1),
        camera_file=(directory / "camera.jsonl").open("a", encoding="utf-8", buffering=1),
    )
    manifest = _manifest_for_session(_auto_session, active=True)
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return _auto_session


def _maybe_auto_stop_locked() -> None:
    if _session is None or _session.deadline_monotonic is None:
        return
    if time.monotonic() >= _session.deadline_monotonic:
        _close_session_locked()


def _manifest_locked(active: bool | None = None) -> dict[str, Any]:
    if _session is None:
        if _last_manifest is not None:
            return {**_last_manifest, "active": False}
        return {
            "active": False,
            "session_id": None,
            "label": None,
            "scenario": None,
            "directory": None,
            "started_at": None,
            "stopped_at": None,
            "duration_seconds": None,
            "csi_samples": 0,
            "camera_samples": 0,
            "latest_tracks": 0,
        }
    now = _utc_now()
    is_active = active if active is not None else _session.stopped_at is None
    return {
        "active": bool(is_active),
        "session_id": _session.session_id,
        "label": _session.label,
        "scenario": _session.scenario,
        "notes": _session.notes,
        "directory": str(_session.directory),
        "started_at": _session.started_at,
        "stopped_at": _session.stopped_at,
        "duration_seconds": round(((_session.stopped_at or now) - _session.started_at).total_seconds(), 3),
        "csi_samples": _session.csi_samples,
        "camera_samples": _session.camera_samples,
        "latest_tracks": _session.latest_tracks,
    }


def start_calibration_session(
    label: str,
    scenario: str,
    duration_seconds: float | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    global _session
    with _lock:
        _maybe_auto_stop_locked()
        if _session is not None:
            _close_session_locked()

        started_at = _utc_now()
        session_id = f"{started_at.strftime('%Y%m%d_%H%M%S')}_{_slug(label)}"
        directory = _ROOT / session_id
        directory.mkdir(parents=True, exist_ok=True)
        csi_file = (directory / "csi.jsonl").open("a", encoding="utf-8", buffering=1)
        camera_file = (directory / "camera.jsonl").open("a", encoding="utf-8", buffering=1)
        deadline = None
        if duration_seconds is not None and duration_seconds > 0:
            deadline = time.monotonic() + float(duration_seconds)
        _session = _Session(
            session_id=session_id,
            label=label,
            scenario=scenario,
            notes=notes,
            directory=directory,
            started_at=started_at,
            deadline_monotonic=deadline,
            csi_file=csi_file,
            camera_file=camera_file,
        )
        manifest = _manifest_locked(active=True)
        (directory / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        return manifest


def stop_calibration_session() -> dict[str, Any]:
    with _lock:
        return _close_session_locked()


def get_calibration_status() -> dict[str, Any]:
    with _lock:
        _maybe_auto_stop_locked()
        _maybe_auto_training_stop_locked()
        manifest = _manifest_locked()
        manifest.update(
            {
                "auto_training_enabled": bool(settings.ruview_auto_training_enabled),
                "auto_training_active": _auto_session is not None,
                "auto_training_session_id": _auto_session.session_id if _auto_session else None,
                "auto_training_directory": str(_auto_session.directory) if _auto_session else None,
                "auto_training_csi_samples": _auto_session.csi_samples if _auto_session else 0,
                "auto_training_camera_samples": _auto_session.camera_samples if _auto_session else 0,
                "auto_training_latest_tracks": _auto_session.latest_tracks if _auto_session else 0,
            }
        )
        return manifest


def _auto_good_tracks(tracks: Any) -> list[dict[str, Any]]:
    if not settings.ruview_auto_training_enabled or not isinstance(tracks, list):
        return []
    good: list[dict[str, Any]] = []
    min_points = max(1, int(settings.ruview_auto_training_min_keypoints))
    min_point_conf = float(settings.ruview_auto_training_min_keypoint_confidence)
    min_track_conf = float(settings.ruview_auto_training_min_track_confidence)
    for track in tracks:
        if not isinstance(track, dict) or bool(track.get("head_only")):
            continue
        try:
            confidence = float(track.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < min_track_conf:
            continue
        keypoints = track.get("keypoints")
        confs = track.get("keypoint_conf")
        if not isinstance(keypoints, list) or not isinstance(confs, list):
            continue
        visible = 0
        for point, conf in zip(keypoints, confs):
            try:
                point_conf = float(conf)
            except (TypeError, ValueError):
                point_conf = 0.0
            if isinstance(point, list) and len(point) >= 2 and point_conf >= min_point_conf:
                visible += 1
        if visible >= min_points:
            good.append(dict(track))
    return good


def _has_pose_tracks(tracks: Any) -> bool:
    if not isinstance(tracks, list):
        return False
    for track in tracks:
        if not isinstance(track, dict) or bool(track.get("head_only")):
            continue
        keypoints = track.get("keypoints")
        confs = track.get("keypoint_conf")
        if not isinstance(keypoints, list):
            continue
        visible = 0
        for index, point in enumerate(keypoints):
            if not isinstance(point, list) or len(point) < 2:
                continue
            try:
                confidence = float(confs[index]) if isinstance(confs, list) and index < len(confs) else 1.0
            except (TypeError, ValueError):
                confidence = 0.0
            if confidence >= 0.12:
                visible += 1
        if visible >= 5:
            return True
    return False


def record_csi_packet(
    *,
    packet_type: str,
    node_id: int,
    source_ip: str,
    source_port: int,
    sequence: int | None,
    rssi: int | None,
    channel: int | None,
    payload_bytes: int | None,
    raw: bytes,
    received_at: datetime,
) -> None:
    with _lock:
        _maybe_auto_stop_locked()
        _maybe_auto_training_stop_locked()
        auto_session = _auto_session
        if auto_session is not None:
            _write_jsonl(
                auto_session.csi_file,
                {
                    "ts": received_at,
                    "monotonic": time.monotonic(),
                    "packet_type": packet_type,
                    "node_id": node_id,
                    "source_ip": source_ip,
                    "source_port": source_port,
                    "sequence": sequence,
                    "rssi": rssi,
                    "channel": channel,
                    "payload_bytes": payload_bytes,
                    "raw_b64": base64.b64encode(raw).decode("ascii"),
                },
            )
            auto_session.csi_samples += 1
        if _session is None:
            return
        _write_jsonl(
            _session.csi_file,
            {
                "ts": received_at,
                "monotonic": time.monotonic(),
                "packet_type": packet_type,
                "node_id": node_id,
                "source_ip": source_ip,
                "source_port": source_port,
                "sequence": sequence,
                "rssi": rssi,
                "channel": channel,
                "payload_bytes": payload_bytes,
                "raw_b64": base64.b64encode(raw).decode("ascii"),
            },
        )
        _session.csi_samples += 1


def record_camera_sample(processor_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    global _auto_last_camera_monotonic
    with _lock:
        _maybe_auto_stop_locked()
        _maybe_auto_training_stop_locked()
        try:
            camera_id = int(payload.get("camera_id"))
        except (TypeError, ValueError):
            camera_id = 0
        if camera_id > 0:
            camera_sample = {
                "received_monotonic": time.monotonic(),
                "received_at": _utc_now(),
                "processor_id": processor_id,
                **payload,
            }
            _latest_camera_samples[camera_id] = camera_sample
            if _has_pose_tracks(payload.get("tracks")):
                _latest_camera_track_samples[camera_id] = camera_sample
        good_tracks = _auto_good_tracks(payload.get("tracks"))
        now = time.monotonic()
        if good_tracks and now - _auto_last_camera_monotonic >= max(
            0.2,
            float(settings.ruview_auto_training_sample_interval_seconds),
        ):
            auto_session = _ensure_auto_session_locked()
            if auto_session is not None:
                auto_payload = {**payload, "tracks": good_tracks}
                _write_jsonl(
                    auto_session.camera_file,
                    {
                        "ts": _utc_now(),
                        "processor_id": processor_id,
                        "auto_quality": {
                            "good_tracks": len(good_tracks),
                            "min_keypoints": settings.ruview_auto_training_min_keypoints,
                            "min_keypoint_confidence": settings.ruview_auto_training_min_keypoint_confidence,
                        },
                        **auto_payload,
                    },
                )
                auto_session.camera_samples += 1
                auto_session.latest_tracks = len(good_tracks)
                _auto_last_camera_monotonic = now
        if _session is None:
            return {"active": False}
        tracks = payload.get("tracks")
        track_count = len(tracks) if isinstance(tracks, list) else 0
        _write_jsonl(
            _session.camera_file,
            {
                "ts": _utc_now(),
                "processor_id": processor_id,
                **payload,
            },
        )
        _session.camera_samples += 1
        _session.latest_tracks = track_count
        return {
            "active": True,
            "session_id": _session.session_id,
            "camera_samples": _session.camera_samples,
            "latest_tracks": _session.latest_tracks,
        }


def get_latest_camera_sample(
    camera_id: int | None = None,
    max_age_seconds: float = 1.5,
    require_tracks: bool = False,
) -> dict[str, Any] | None:
    with _lock:
        now = time.monotonic()
        samples = []
        source = _latest_camera_track_samples if require_tracks else _latest_camera_samples
        for sample in source.values():
            sample_age = now - float(sample.get("received_monotonic") or 0.0)
            if sample_age > max_age_seconds:
                continue
            if camera_id is not None and int(sample.get("camera_id") or 0) != int(camera_id):
                continue
            samples.append((sample_age, sample))
        if not samples:
            return None
        _, sample = min(samples, key=lambda item: item[0])
        return dict(sample)
