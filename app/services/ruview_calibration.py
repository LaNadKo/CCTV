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


_ROOT = Path("calibration_datasets")


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
_last_manifest: dict[str, Any] | None = None
_latest_camera_samples: dict[int, dict[str, Any]] = {}


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
        return _manifest_locked()


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
    with _lock:
        _maybe_auto_stop_locked()
        try:
            camera_id = int(payload.get("camera_id"))
        except (TypeError, ValueError):
            camera_id = 0
        if camera_id > 0:
            _latest_camera_samples[camera_id] = {
                "received_monotonic": time.monotonic(),
                "received_at": _utc_now(),
                "processor_id": processor_id,
                **payload,
            }
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


def get_latest_camera_sample(camera_id: int | None = None, max_age_seconds: float = 1.5) -> dict[str, Any] | None:
    with _lock:
        now = time.monotonic()
        samples = []
        for sample in _latest_camera_samples.values():
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
