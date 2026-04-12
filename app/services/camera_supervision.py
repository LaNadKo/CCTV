"""Camera-supervised RF fingerprint collection."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from app.config import settings
from app.schemas.camera_room import CameraRoomProjectionOut
from app.schemas.tracking import ProcessorTrackObservationIn
from app.services.camera_room import project_track_observation
from app.services.ruview_bridge import get_ruview_bridge_status
from app.services.ruview_calibration import collect_instant_calibration_sample

log = logging.getLogger(__name__)

_lock = threading.Lock()
_last_sample_at: dict[str, datetime] = {}


def observe_camera_supervised_track(
    processor_id: int,
    payload: ProcessorTrackObservationIn,
) -> CameraRoomProjectionOut | None:
    projection = project_track_observation(payload)
    if projection is None or not settings.camera_supervision_enabled:
        return projection
    if settings.camera_supervision_require_manual_calibration and projection.source == "auto_full_frame":
        return projection
    if payload.confidence is not None and payload.confidence < settings.camera_supervision_min_confidence:
        return projection
    if not _should_collect(processor_id, payload):
        return projection

    try:
        status = get_ruview_bridge_status()
        if not status.listening or (not status.nodes and not status.links):
            return projection
        collect_instant_calibration_sample(
            kind="live_reference",
            label=f"camera_{payload.camera_id}_track_{payload.track_id}",
            person_count=1,
            x_cm=projection.x_cm,
            y_cm=projection.y_cm,
            z_cm=projection.z_cm,
            related_nodes=projection.related_nodes,
            note=(
                f"Auto label from processor {processor_id}, camera {payload.camera_id}, "
                f"track {payload.track_id}, projection={projection.source}."
            ),
        )
    except Exception:
        log.exception("Failed to store camera-supervised RF sample")
    return projection


def _should_collect(processor_id: int, payload: ProcessorTrackObservationIn) -> bool:
    now = datetime.now(timezone.utc)
    key = f"{processor_id}:{payload.camera_id}:{payload.track_id}"
    with _lock:
        previous = _last_sample_at.get(key)
        if previous is not None:
            elapsed = (now - previous).total_seconds()
            if elapsed < settings.camera_supervision_min_interval_seconds:
                return False
        _last_sample_at[key] = now
    return True
