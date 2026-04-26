from __future__ import annotations

import json
import math
import struct
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.config import settings
from app.schemas.ruview import RuViewPoseBox, RuViewPoseKeypoint, RuViewPosePerson, RuViewPoseSnapshot
from app.services.ruview_bridge import RecentCsiPacket, get_recent_ruview_csi_packets
from app.services.ruview_calibration import get_latest_camera_sample

CSI_MAGIC = 0xC5110001
RF_LINK_MAGIC = 0xC5110101

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


@dataclass(frozen=True)
class _DecodedCsi:
    key: str
    rssi: float
    amplitude: np.ndarray


@dataclass
class _Model:
    path: Path
    mtime_ns: int
    weights: np.ndarray
    mean: np.ndarray
    std: np.ndarray
    feature_keys: list[str]
    bins: int
    window_seconds: float
    frame_width: float
    frame_height: float
    report: dict[str, Any]


_model_lock = threading.RLock()
_model_cache: _Model | None = None

_pose_lock = threading.RLock()
_stabilized_person: RuViewPosePerson | None = None
_stabilized_raw_center: tuple[float, float] | None = None
_stabilized_updated_at: float = 0.0
_stabilized_anchor_at: float = 0.0

_SMOOTH_ALPHA = 0.18
_STATIC_DEADBAND_PX = 14.0
_MAX_RF_DELTA_PX = 42.0


def _decode_csi_packet(packet: RecentCsiPacket) -> _DecodedCsi | None:
    raw = packet.raw
    if len(raw) < 20:
        return None
    magic = struct.unpack_from("<I", raw, 0)[0]
    if magic == CSI_MAGIC and len(raw) >= 20:
        rx_node = raw[4]
        payload = raw[20:]
        key = f"node:{rx_node}"
    elif magic == RF_LINK_MAGIC and len(raw) >= 32:
        rx_node = raw[5]
        tx_node = raw[6]
        payload_len = struct.unpack_from("<H", raw, 20)[0]
        header_len = struct.unpack_from("<H", raw, 22)[0]
        if header_len <= 0 or header_len > len(raw):
            header_len = 32
        payload = raw[header_len : header_len + payload_len]
        key = f"link:{tx_node}->{rx_node}" if tx_node else f"node:{rx_node}"
    else:
        return None
    if len(payload) < 4:
        return None
    csi = np.frombuffer(payload, dtype=np.int8).astype(np.float32)
    if csi.size % 2 == 1:
        csi = csi[:-1]
    iq = csi.reshape(-1, 2)
    amplitude = np.sqrt((iq[:, 0] * iq[:, 0]) + (iq[:, 1] * iq[:, 1]))
    return _DecodedCsi(key=key, rssi=float(packet.rssi or 0.0), amplitude=amplitude)


def _bin_amplitude(amplitude: np.ndarray, bins: int) -> np.ndarray:
    if amplitude.size == 0:
        return np.zeros(bins, dtype=np.float32)
    chunks = np.array_split(amplitude, bins)
    return np.asarray([float(np.mean(chunk)) if chunk.size else 0.0 for chunk in chunks], dtype=np.float32)


def _build_feature_vector(decoded_rows: list[_DecodedCsi], model: _Model) -> np.ndarray | None:
    if not decoded_rows:
        return None
    stride = 5 + model.bins * 2
    key_index = {key: index for index, key in enumerate(model.feature_keys)}
    vector = np.zeros(len(model.feature_keys) * stride, dtype=np.float32)
    by_key: dict[str, list[_DecodedCsi]] = {}
    for row in decoded_rows:
        if row.key in key_index:
            by_key.setdefault(row.key, []).append(row)
    if not by_key:
        return None
    for key, key_rows in by_key.items():
        offset = key_index[key] * stride
        rssi = np.asarray([row.rssi for row in key_rows], dtype=np.float32)
        amps = np.concatenate([row.amplitude for row in key_rows if row.amplitude.size])
        binned = np.asarray([_bin_amplitude(row.amplitude, model.bins) for row in key_rows if row.amplitude.size])
        vector[offset] = min(len(key_rows), 50) / 50.0
        vector[offset + 1] = float(np.mean(rssi)) if rssi.size else 0.0
        vector[offset + 2] = float(np.std(rssi)) if rssi.size else 0.0
        vector[offset + 3] = float(np.mean(amps)) if amps.size else 0.0
        vector[offset + 4] = float(np.std(amps)) if amps.size else 0.0
        if binned.size:
            vector[offset + 5 : offset + 5 + model.bins] = np.mean(binned, axis=0)
            vector[offset + 5 + model.bins : offset + 5 + model.bins * 2] = np.std(binned, axis=0)
    return vector


def _load_model() -> _Model | None:
    if not settings.ruview_calibrator_enabled:
        return None
    path = Path(settings.ruview_calibrator_model_path)
    if not path.exists():
        return None
    stat = path.stat()
    global _model_cache
    with _model_lock:
        if _model_cache is not None and _model_cache.path == path and _model_cache.mtime_ns == stat.st_mtime_ns:
            return _model_cache
        with np.load(path, allow_pickle=True) as data:
            weights = np.asarray(data["weights"], dtype=np.float32)
            mean = np.asarray(data["mean"], dtype=np.float32)
            std = np.asarray(data["std"], dtype=np.float32)
            report = json.loads(str(data["report"].item()))
        feature_keys = [str(item) for item in report.get("feature_keys") or []]
        if not feature_keys:
            return None
        model = _Model(
            path=path,
            mtime_ns=stat.st_mtime_ns,
            weights=weights,
            mean=mean,
            std=std,
            feature_keys=feature_keys,
            bins=int(report.get("bins") or 16),
            window_seconds=float(report.get("window_seconds") or settings.ruview_calibrator_window_seconds),
            frame_width=float(report.get("frame_width") or 1920.0),
            frame_height=float(report.get("frame_height") or 1080.0),
            report=report,
        )
        _model_cache = model
        return model


def _predict(vector: np.ndarray, model: _Model) -> np.ndarray:
    x_norm = (vector - model.mean) / model.std
    x_aug = np.concatenate([x_norm, np.ones(1, dtype=np.float32)])
    return x_aug @ model.weights


def _pose_from_prediction(prediction: np.ndarray, model: _Model, packet_count: int) -> RuViewPosePerson | None:
    if prediction.shape[0] < 38:
        return None
    values = np.clip(prediction.astype(np.float32), 0.0, 1.0)
    center_x = float(values[0] * model.frame_width)
    center_y = float(values[1] * model.frame_height)
    width = max(24.0, float(values[2] * model.frame_width))
    height = max(24.0, float(values[3] * model.frame_height))
    x = max(0.0, min(model.frame_width, center_x - width / 2.0))
    y = max(0.0, min(model.frame_height, center_y - height / 2.0))
    bbox = RuViewPoseBox(
        x=x,
        y=y,
        width=min(width, model.frame_width - x),
        height=min(height, model.frame_height - y),
    )
    keypoints: list[RuViewPoseKeypoint] = []
    for index, name in enumerate(_COCO_KEYPOINT_NAMES):
        base = 4 + index * 2
        kx = float(values[base] * model.frame_width)
        ky = float(values[base + 1] * model.frame_height)
        visible = math.isfinite(kx) and math.isfinite(ky)
        keypoints.append(
            RuViewPoseKeypoint(
                name=name,
                x=max(0.0, min(model.frame_width, kx)),
                y=max(0.0, min(model.frame_height, ky)),
                confidence=min(0.85, max(0.15, packet_count / 70.0)),
                visible=visible,
            )
        )
    return RuViewPosePerson(
        track_id="rf-1",
        source_id="ruview-rf-calibrator",
        confidence=min(0.85, max(0.1, packet_count / 70.0)),
        bbox=bbox,
        keypoints=keypoints,
    )


def _person_center(person: RuViewPosePerson) -> tuple[float, float] | None:
    if person.bbox:
        return person.bbox.x + person.bbox.width / 2.0, person.bbox.y + person.bbox.height / 2.0
    points = [point for point in person.keypoints if point.visible]
    if not points:
        return None
    return sum(point.x for point in points) / len(points), sum(point.y for point in points) / len(points)


def _copy_person(person: RuViewPosePerson) -> RuViewPosePerson:
    return RuViewPosePerson(
        track_id=person.track_id,
        source_id=person.source_id,
        confidence=person.confidence,
        bbox=RuViewPoseBox(**person.bbox.model_dump()) if person.bbox else None,
        keypoints=[RuViewPoseKeypoint(**point.model_dump()) for point in person.keypoints],
        age_ms=person.age_ms,
    )


def _blend_value(old: float, new: float, alpha: float) -> float:
    return old * (1.0 - alpha) + new * alpha


def _blend_person(old: RuViewPosePerson | None, new: RuViewPosePerson, alpha: float) -> RuViewPosePerson:
    if old is None:
        return _copy_person(new)
    old_points = {point.name: point for point in old.keypoints}
    points: list[RuViewPoseKeypoint] = []
    for point in new.keypoints:
        previous = old_points.get(point.name)
        if previous:
            points.append(
                RuViewPoseKeypoint(
                    name=point.name,
                    x=_blend_value(previous.x, point.x, alpha),
                    y=_blend_value(previous.y, point.y, alpha),
                    confidence=point.confidence,
                    visible=point.visible,
                )
            )
        else:
            points.append(RuViewPoseKeypoint(**point.model_dump()))
    bbox = new.bbox
    if old.bbox and new.bbox:
        bbox = RuViewPoseBox(
            x=_blend_value(old.bbox.x, new.bbox.x, alpha),
            y=_blend_value(old.bbox.y, new.bbox.y, alpha),
            width=_blend_value(old.bbox.width, new.bbox.width, alpha),
            height=_blend_value(old.bbox.height, new.bbox.height, alpha),
        )
    return RuViewPosePerson(
        track_id="rf-1",
        source_id=new.source_id,
        confidence=new.confidence,
        bbox=bbox,
        keypoints=points,
        age_ms=new.age_ms,
    )


def _translate_person(person: RuViewPosePerson, dx: float, dy: float) -> RuViewPosePerson:
    copy = _copy_person(person)
    if copy.bbox:
        copy.bbox.x += dx
        copy.bbox.y += dy
    for point in copy.keypoints:
        point.x += dx
        point.y += dy
    return copy


def _clamp_person(person: RuViewPosePerson, width: float, height: float) -> RuViewPosePerson:
    copy = _copy_person(person)
    if copy.bbox:
        copy.bbox.x = max(0.0, min(width, copy.bbox.x))
        copy.bbox.y = max(0.0, min(height, copy.bbox.y))
        copy.bbox.width = max(0.0, min(copy.bbox.width, width - copy.bbox.x))
        copy.bbox.height = max(0.0, min(copy.bbox.height, height - copy.bbox.y))
    for point in copy.keypoints:
        point.x = max(0.0, min(width, point.x))
        point.y = max(0.0, min(height, point.y))
    return copy


def _box_from_payload(value: Any, sx: float, sy: float) -> RuViewPoseBox | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        x1, y1, x2, y2 = (float(value[0]) * sx, float(value[1]) * sy, float(value[2]) * sx, float(value[3]) * sy)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (x1, y1, x2, y2)):
        return None
    return RuViewPoseBox(x=min(x1, x2), y=min(y1, y2), width=max(1.0, abs(x2 - x1)), height=max(1.0, abs(y2 - y1)))


def _keypoints_from_payload(track: dict[str, Any], sx: float, sy: float) -> list[RuViewPoseKeypoint]:
    raw_points = track.get("keypoints")
    if not isinstance(raw_points, list):
        return []
    raw_conf = track.get("keypoint_conf")
    confs = raw_conf if isinstance(raw_conf, list) else []
    points: list[RuViewPoseKeypoint] = []
    for index, raw in enumerate(raw_points[: len(_COCO_KEYPOINT_NAMES)]):
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            continue
        try:
            x = float(raw[0]) * sx
            y = float(raw[1]) * sy
            confidence = float(confs[index]) if index < len(confs) else None
        except (TypeError, ValueError):
            continue
        visible = math.isfinite(x) and math.isfinite(y) and (confidence is None or confidence >= 0.12)
        points.append(
            RuViewPoseKeypoint(
                name=_COCO_KEYPOINT_NAMES[index],
                x=x,
                y=y,
                confidence=confidence,
                visible=visible,
            )
        )
    return points


def _latest_camera_anchor(model: _Model) -> RuViewPosePerson | None:
    sample = get_latest_camera_sample(max_age_seconds=float(settings.ruview_camera_anchor_max_age_seconds))
    if not sample:
        return None
    try:
        frame_width = max(1.0, float(sample.get("frame_width") or model.frame_width))
        frame_height = max(1.0, float(sample.get("frame_height") or model.frame_height))
    except (TypeError, ValueError):
        frame_width = model.frame_width
        frame_height = model.frame_height
    sx = model.frame_width / frame_width
    sy = model.frame_height / frame_height
    tracks = sample.get("tracks")
    if not isinstance(tracks, list):
        return None

    candidates: list[tuple[float, RuViewPosePerson]] = []
    for track in tracks:
        if not isinstance(track, dict) or bool(track.get("head_only")):
            continue
        try:
            track_age_ms = float(track.get("age_ms") or 0.0)
        except (TypeError, ValueError):
            track_age_ms = 0.0
        if track_age_ms > 900.0:
            continue
        bbox = _box_from_payload(track.get("tracking_bbox") or track.get("bbox"), sx, sy)
        if bbox is None or bbox.width < 24.0 or bbox.height < 40.0:
            continue
        points = _keypoints_from_payload(track, sx, sy)
        visible_points = [point for point in points if point.visible and (point.confidence is None or point.confidence >= 0.18)]
        if len(visible_points) < 5:
            continue
        confidence = 0.5
        try:
            confidence = max(0.0, min(1.0, float(track.get("confidence") or 0.5)))
        except (TypeError, ValueError):
            pass
        score = confidence + min(1.0, len(visible_points) / 17.0)
        candidates.append(
            (
                score,
                RuViewPosePerson(
                    track_id="rf-1",
                    source_id="camera-anchor",
                    confidence=max(confidence, 0.55),
                    bbox=bbox,
                    keypoints=points,
                ),
            )
        )
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _fit_person_to_anchor(raw: RuViewPosePerson, anchor: RuViewPosePerson) -> RuViewPosePerson:
    fitted = _copy_person(anchor)
    fitted.track_id = "rf-1"
    fitted.source_id = "ruview-rf-camera-anchored"
    fitted.confidence = max(raw.confidence or 0.0, anchor.confidence or 0.0)
    return fitted


def _stabilize_pose(raw: RuViewPosePerson, model: _Model) -> tuple[RuViewPosePerson | None, str | None]:
    global _stabilized_anchor_at, _stabilized_person, _stabilized_raw_center, _stabilized_updated_at
    now_float = time.monotonic()
    raw_center = _person_center(raw)
    if raw_center is None:
        return None, "RF-pose model did not produce a usable center"

    anchor = _latest_camera_anchor(model)
    with _pose_lock:
        if anchor is not None:
            target = _fit_person_to_anchor(raw, anchor)
            stabilized = target
            stabilized = _clamp_person(stabilized, model.frame_width, model.frame_height)
            _stabilized_person = stabilized
            _stabilized_raw_center = raw_center
            _stabilized_updated_at = now_float
            _stabilized_anchor_at = now_float
            return stabilized, None

        if _stabilized_person is None:
            if settings.ruview_rf_overlay_requires_camera_anchor:
                return None, "Нет свежего body-track камеры для привязки RF-скелета"
            stabilized = _clamp_person(_blend_person(None, raw, 1.0), model.frame_width, model.frame_height)
            _stabilized_person = stabilized
            _stabilized_raw_center = raw_center
            _stabilized_updated_at = now_float
            return stabilized, None

        since_anchor = now_float - _stabilized_anchor_at if _stabilized_anchor_at else float("inf")
        if settings.ruview_rf_overlay_requires_camera_anchor and since_anchor > float(settings.ruview_rf_pose_hold_seconds):
            _stabilized_person = None
            _stabilized_raw_center = None
            _stabilized_updated_at = 0.0
            _stabilized_anchor_at = 0.0
            return None, "RF-скелет скрыт: нет свежей camera-привязки"

        previous_raw = _stabilized_raw_center or raw_center
        dx = raw_center[0] - previous_raw[0]
        dy = raw_center[1] - previous_raw[1]
        distance = math.hypot(dx, dy)
        if distance < _STATIC_DEADBAND_PX:
            dx = 0.0
            dy = 0.0
        elif distance > _MAX_RF_DELTA_PX:
            scale = _MAX_RF_DELTA_PX / distance
            dx *= scale
            dy *= scale
        predicted = _translate_person(_stabilized_person, dx * _SMOOTH_ALPHA, dy * _SMOOTH_ALPHA)
        predicted.source_id = "ruview-rf-held"
        predicted.confidence = min(predicted.confidence or 0.45, 0.55)
        stabilized = _clamp_person(predicted, model.frame_width, model.frame_height)
        _stabilized_person = stabilized
        _stabilized_raw_center = raw_center
        _stabilized_updated_at = now_float
        return stabilized, None


def get_calibrated_pose_snapshot() -> RuViewPoseSnapshot | None:
    model = _load_model()
    if model is None:
        return None
    window_seconds = max(float(settings.ruview_calibrator_window_seconds), model.window_seconds)
    packets = get_recent_ruview_csi_packets(window_seconds)
    decoded = [item for packet in packets if (item := _decode_csi_packet(packet)) is not None]
    if len(decoded) < 8:
        return RuViewPoseSnapshot(
            reachable=False,
            source_url=str(model.path),
            source_kind="cctv-rf-calibrated-ridge",
            captured_at=datetime.now(timezone.utc),
            frame_width=model.frame_width,
            frame_height=model.frame_height,
            camera_aligned=True,
            overlay_allowed=False,
            error="Недостаточно live CSI для RF-pose модели",
        )
    vector = _build_feature_vector(decoded, model)
    if vector is None:
        return None
    prediction = _predict(vector, model)
    person = _pose_from_prediction(prediction, model, packet_count=len(decoded))
    if person is None:
        return None
    person, error = _stabilize_pose(person, model)
    if person is None:
        return RuViewPoseSnapshot(
            reachable=True,
            source_url=str(model.path),
            source_kind="cctv-rf-calibrated-ridge",
            captured_at=datetime.now(timezone.utc),
            frame_width=model.frame_width,
            frame_height=model.frame_height,
            camera_aligned=True,
            overlay_allowed=False,
            error=error,
        )
    return RuViewPoseSnapshot(
        reachable=True,
        source_url=str(model.path),
        source_kind=person.source_id or "cctv-rf-calibrated-ridge",
        captured_at=datetime.now(timezone.utc),
        frame_width=model.frame_width,
        frame_height=model.frame_height,
        camera_aligned=True,
        overlay_allowed=True,
        persons=[person],
    )
