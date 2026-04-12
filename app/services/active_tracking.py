"""In-memory hybrid camera/RuView active tracking service."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.schemas.tracking import ActivePersonTrack, ActiveTrackingSnapshot, ProcessorTrackObservationIn
from app.services.camera_supervision import observe_camera_supervised_track
from app.services.ruview_calibration import estimate_current_zone


class ActiveTrackingService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tracks: dict[str, ActivePersonTrack] = {}

    def observe_camera_track(
        self,
        processor_id: int,
        payload: ProcessorTrackObservationIn,
        *,
        create_missing: bool = True,
    ) -> ActivePersonTrack | None:
        wall_now = datetime.now(timezone.utc)
        now = _as_utc(payload.observed_at) or wall_now
        if now > wall_now + timedelta(seconds=10):
            now = wall_now
        projection = observe_camera_supervised_track(processor_id, payload)
        raw_track_key = _track_key(processor_id, payload)
        anonymous_key = f"camera:{processor_id}:{payload.camera_id}:{payload.track_id}"

        with self._lock:
            track_key = raw_track_key
            if payload.person_id is None:
                track_key = (
                    self._find_exact_identity_track_key(processor_id, payload, now)
                    or self._find_anonymous_merge_key(processor_id, payload, now, projection)
                    or raw_track_key
                )
            previous = self._tracks.get(track_key)
            if previous is None and payload.person_id is not None:
                previous = self._tracks.pop(anonymous_key, None)
                if previous is None:
                    merge_payload = payload.model_copy(update={"person_id": None})
                    merge_key = self._find_anonymous_merge_key(
                        processor_id,
                        merge_payload,
                        now,
                        projection,
                        max_age_seconds=settings.active_tracking_room_hold_seconds,
                    )
                    if merge_key is not None:
                        previous = self._tracks.pop(merge_key, None)
            if previous is None and not create_missing:
                return None
            if previous is None:
                previous = ActivePersonTrack(
                    track_key=track_key,
                    status="camera",
                    source="camera",
                    person_id=payload.person_id,
                    person_label=payload.person_label,
                    processor_id=processor_id,
                    camera_id=payload.camera_id,
                    processor_track_id=payload.track_id,
                    first_seen_at=now,
                    last_seen_at=now,
                )

            updated = previous.model_copy(
                update={
                    "track_key": track_key,
                    "status": "camera",
                    "source": "camera",
                    "person_id": payload.person_id if payload.person_id is not None else previous.person_id,
                    "person_label": payload.person_label or previous.person_label,
                    "processor_id": processor_id,
                    "camera_id": payload.camera_id,
                    "processor_track_id": payload.track_id,
                    "confidence": payload.confidence if payload.confidence is not None else previous.confidence,
                    "bbox": payload.bbox,
                    "frame_width": payload.frame_width,
                    "frame_height": payload.frame_height,
                    "keypoints": payload.keypoints if payload.keypoints is not None else previous.keypoints,
                    "keypoint_conf": payload.keypoint_conf if payload.keypoint_conf is not None else previous.keypoint_conf,
                    "estimated_x_cm": projection.x_cm if projection is not None else previous.estimated_x_cm,
                    "estimated_y_cm": projection.y_cm if projection is not None else previous.estimated_y_cm,
                    "estimated_z_cm": projection.z_cm if projection is not None else previous.estimated_z_cm,
                    "active_nodes": projection.related_nodes if projection is not None else previous.active_nodes,
                    "last_seen_at": now,
                    "last_camera_seen_at": now,
                    "note": (
                        (
                            f"Camera bbox projected to room coordinates via {projection.source}; RF label stored automatically."
                            if projection.source != "auto_full_frame"
                            else "Camera bbox projected with temporary full-frame mapping; RF training is blocked until manual camera calibration."
                        )
                        if projection is not None
                        else "Camera body/face tracker is the primary source."
                    ),
                }
            )
            self._tracks[track_key] = updated
            if updated.person_id is not None:
                self._drop_duplicate_anonymous_tracks(updated)
            return updated

    def snapshot(self, limit: int = 200) -> ActiveTrackingSnapshot:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._expire_locked(now)
            tracks = [track.model_copy(deep=True) for track in self._tracks.values()]

        rf_message: str | None = None
        try:
            rf_estimate = estimate_current_zone(limit=limit)
            rf_message = rf_estimate.message
        except Exception as exc:
            rf_estimate = None
            rf_message = f"RuView estimate unavailable: {exc}"

        fresh_tracks = [
            track
            for track in tracks
            if _seconds_since(now, track.last_camera_seen_at) <= settings.active_tracking_camera_fresh_seconds
        ]
        stale_candidates = [
            track
            for track in tracks
            if _seconds_since(now, track.last_camera_seen_at) > settings.active_tracking_camera_fresh_seconds
        ]
        fresh_camera_keys = {track.track_key for track in fresh_tracks}
        rf_ready = _rf_estimate_ready(rf_estimate)
        fresh_rf_owner_key = _select_rf_owner(rf_estimate, fresh_tracks) if rf_ready else None
        fresh_rf_owner = next((track for track in fresh_tracks if track.track_key == fresh_rf_owner_key), None)
        known_stale_candidates = [track for track in stale_candidates if track.person_id is not None]
        stale_rf_owner_key = None
        if rf_ready and (
            not fresh_tracks
            or fresh_rf_owner is None
            or fresh_rf_owner.person_id is None
        ):
            stale_rf_owner_key = _select_rf_owner(
                rf_estimate,
                known_stale_candidates or stale_candidates,
                prefer_identity=True,
            )
            if stale_rf_owner_key is not None and fresh_rf_owner is not None and fresh_rf_owner.person_id is None:
                fresh_rf_owner_key = None

        updated_tracks: list[ActivePersonTrack] = []
        for track in tracks:
            if track.track_key in fresh_camera_keys:
                if fresh_rf_owner_key == track.track_key and rf_estimate is not None:
                    updated_tracks.append(
                        track.model_copy(
                            update={
                                "source": "fusion",
                                "estimated_x_cm": rf_estimate.estimated_x_cm,
                                "estimated_y_cm": rf_estimate.estimated_y_cm,
                                "estimated_z_cm": 0.0,
                                "rf_confidence": rf_estimate.confidence,
                                "active_nodes": rf_estimate.active_nodes,
                                "last_rf_seen_at": now,
                                "note": "Camera keeps identity and pose; RuView refines the room position for this track.",
                            }
                        )
                    )
                else:
                    updated_tracks.append(
                        track.model_copy(
                            update={
                                "status": "camera",
                                "source": "camera",
                                "note": "Camera supplies live identity, pose, and room projection.",
                            }
                        )
                    )
                continue

            age = _seconds_since(now, track.last_seen_at)
            camera_gap = _seconds_since(now, track.last_camera_seen_at)
            if stale_rf_owner_key == track.track_key and rf_estimate is not None:
                updated_tracks.append(
                    track.model_copy(
                        update={
                            "status": "rf",
                            "source": "fusion" if track.person_id is not None else "ruview",
                            "estimated_x_cm": rf_estimate.estimated_x_cm,
                            "estimated_y_cm": rf_estimate.estimated_y_cm,
                            "estimated_z_cm": 0.0,
                            "rf_confidence": rf_estimate.confidence,
                            "active_nodes": rf_estimate.active_nodes,
                            "last_seen_at": now,
                            "last_rf_seen_at": now,
                            "note": "Camera identity and last pose are retained; RuView CSI supplies the room position.",
                        }
                    )
                )
            elif camera_gap <= settings.active_tracking_room_hold_seconds and age <= settings.active_tracking_expire_seconds:
                updated_tracks.append(
                    track.model_copy(
                        update={
                            "status": "ambiguous" if len(stale_candidates) > 1 else "lost",
                            "source": "none",
                            "note": "Camera lost the body; RuView assignment is ambiguous or below confidence threshold.",
                        }
                    )
                )

        with self._lock:
            self._tracks = {track.track_key: track for track in updated_tracks}

        sorted_tracks = sorted(updated_tracks, key=lambda item: item.last_seen_at, reverse=True)
        live_tracks = [track for track in sorted_tracks if track.status in {"camera", "rf"}]
        return ActiveTrackingSnapshot(
            generated_at=now,
            active_count=len(live_tracks),
            camera_count=sum(1 for track in live_tracks if track.status == "camera"),
            rf_count=sum(1 for track in live_tracks if track.status == "rf"),
            tracks=live_tracks,
            rf_message=rf_message,
        )

    def _expire_locked(self, now: datetime) -> None:
        expired = [
            key
            for key, track in self._tracks.items()
            if _seconds_since(now, track.last_seen_at) > settings.active_tracking_expire_seconds
        ]
        for key in expired:
            self._tracks.pop(key, None)

    def _find_anonymous_merge_key(
        self,
        processor_id: int,
        payload: ProcessorTrackObservationIn,
        now: datetime,
        projection,
        *,
        max_age_seconds: float | None = None,
    ) -> str | None:
        if payload.person_id is not None:
            return None
        raw_track_key = _track_key(processor_id, payload)
        raw_match = self._tracks.get(raw_track_key)
        if raw_match is not None:
            return raw_match.track_key

        best_key: str | None = None
        best_score = 0.0
        for track in self._tracks.values():
            if track.person_id is not None:
                continue
            if track.processor_id != processor_id or track.camera_id != payload.camera_id:
                continue
            max_age = (
                float(max_age_seconds)
                if max_age_seconds is not None
                else settings.active_tracking_camera_merge_seconds
            )
            if _seconds_since(now, track.last_camera_seen_at) > max_age:
                continue

            iou = _bbox_iou(track.bbox, payload.bbox)
            distance_score = _projection_distance_score(track, projection)
            score = max(iou, distance_score)
            if score > best_score:
                best_score = score
                best_key = track.track_key

        if best_score >= settings.active_tracking_camera_merge_min_score:
            return best_key
        return None

    def _find_exact_identity_track_key(
        self,
        processor_id: int,
        payload: ProcessorTrackObservationIn,
        now: datetime,
    ) -> str | None:
        for track in self._tracks.values():
            if track.person_id is None:
                continue
            if track.processor_id != processor_id or track.camera_id != payload.camera_id:
                continue
            if track.processor_track_id != payload.track_id:
                continue
            if _seconds_since(now, track.last_camera_seen_at) <= settings.active_tracking_room_hold_seconds:
                return track.track_key
        return None

    def _drop_duplicate_anonymous_tracks(self, identity_track: ActivePersonTrack) -> None:
        duplicate_keys: list[str] = []
        for key, track in self._tracks.items():
            if key == identity_track.track_key or track.person_id is not None:
                continue
            if track.processor_id != identity_track.processor_id or track.camera_id != identity_track.camera_id:
                continue
            same_processor_track = (
                track.processor_track_id is not None
                and track.processor_track_id == identity_track.processor_track_id
            )
            same_box = _bbox_iou(track.bbox, identity_track.bbox) >= settings.active_tracking_camera_merge_min_score
            if same_processor_track or same_box:
                duplicate_keys.append(key)
        for key in duplicate_keys:
            self._tracks.pop(key, None)


def _track_key(processor_id: int, payload: ProcessorTrackObservationIn) -> str:
    if payload.person_id is not None:
        return f"person:{payload.person_id}"
    return f"camera:{processor_id}:{payload.camera_id}:{payload.track_id}"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _seconds_since(now: datetime, value: datetime | None) -> float:
    if value is None:
        return float("inf")
    return max(0.0, (now - _as_utc(value)).total_seconds())


def _bbox_iou(left, right) -> float:
    if left is None or right is None:
        return 0.0
    lx1, ly1, lx2, ly2 = _normalized_box(left)
    rx1, ry1, rx2, ry2 = _normalized_box(right)
    intersection_w = max(0.0, min(lx2, rx2) - max(lx1, rx1))
    intersection_h = max(0.0, min(ly2, ry2) - max(ly1, ry1))
    intersection = intersection_w * intersection_h
    if intersection <= 0:
        return 0.0
    left_area = max(0.0, lx2 - lx1) * max(0.0, ly2 - ly1)
    right_area = max(0.0, rx2 - rx1) * max(0.0, ry2 - ry1)
    union = left_area + right_area - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _normalized_box(box) -> tuple[float, float, float, float]:
    x1 = min(float(box.x1), float(box.x2))
    y1 = min(float(box.y1), float(box.y2))
    x2 = max(float(box.x1), float(box.x2))
    y2 = max(float(box.y1), float(box.y2))
    return x1, y1, x2, y2


def _projection_distance_score(track: ActivePersonTrack, projection) -> float:
    if (
        projection is None
        or projection.x_cm is None
        or projection.y_cm is None
        or track.estimated_x_cm is None
        or track.estimated_y_cm is None
    ):
        return 0.0
    dx = float(track.estimated_x_cm) - float(projection.x_cm)
    dy = float(track.estimated_y_cm) - float(projection.y_cm)
    distance_cm = (dx * dx + dy * dy) ** 0.5
    radius_cm = max(1.0, float(settings.active_tracking_camera_merge_radius_cm))
    if distance_cm >= radius_cm:
        return 0.0
    return 1.0 - (distance_cm / radius_cm)


def _rf_estimate_ready(rf_estimate) -> bool:
    return (
        rf_estimate is not None
        and rf_estimate.ready
        and rf_estimate.estimated_x_cm is not None
        and rf_estimate.estimated_y_cm is not None
        and rf_estimate.confidence >= settings.active_tracking_rf_min_confidence
    )


def _select_rf_owner(
    rf_estimate,
    candidates: list[ActivePersonTrack],
    *,
    prefer_identity: bool = False,
) -> str | None:
    if not candidates or not _rf_estimate_ready(rf_estimate):
        return None
    if prefer_identity:
        identity_candidates = [track for track in candidates if track.person_id is not None]
        if identity_candidates:
            candidates = identity_candidates
    if len(candidates) == 1:
        return candidates[0].track_key

    positioned = [
        track
        for track in candidates
        if track.estimated_x_cm is not None and track.estimated_y_cm is not None
    ]
    if not positioned:
        return None

    def distance_sq(track: ActivePersonTrack) -> float:
        dx = float(track.estimated_x_cm or 0) - float(rf_estimate.estimated_x_cm)
        dy = float(track.estimated_y_cm or 0) - float(rf_estimate.estimated_y_cm)
        return dx * dx + dy * dy

    nearest = min(positioned, key=distance_sq)
    max_distance_sq = settings.active_tracking_rf_assignment_radius_cm ** 2
    if distance_sq(nearest) <= max_distance_sq:
        return nearest.track_key
    return None


_service = ActiveTrackingService()


def observe_camera_track(
    processor_id: int,
    payload: ProcessorTrackObservationIn,
    *,
    create_missing: bool = True,
) -> ActivePersonTrack | None:
    return _service.observe_camera_track(processor_id, payload, create_missing=create_missing)


def get_active_tracking_snapshot(limit: int = 200) -> ActiveTrackingSnapshot:
    return _service.snapshot(limit=limit)
