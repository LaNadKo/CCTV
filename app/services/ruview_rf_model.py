from __future__ import annotations

import json
import math
import struct
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.config import settings
from app.schemas.ruview import RuViewPoseBox, RuViewPoseKeypoint, RuViewPosePerson, RuViewPoseSnapshot
from app.services.ruview_bridge import RecentCsiPacket, get_recent_ruview_csi_packets

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
    return RuViewPoseSnapshot(
        reachable=True,
        source_url=str(model.path),
        source_kind="cctv-rf-calibrated-ridge",
        captured_at=datetime.now(timezone.utc),
        camera_aligned=True,
        overlay_allowed=True,
        persons=[person],
    )
