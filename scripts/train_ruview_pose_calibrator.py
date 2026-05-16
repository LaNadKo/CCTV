from __future__ import annotations

import argparse
import base64
import json
import math
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

CSI_MAGIC = 0xC5110001
RF_LINK_MAGIC = 0xC5110101


@dataclass(frozen=True)
class CsiRow:
    ts: float
    key: str
    rssi: float
    amplitude: np.ndarray


@dataclass(frozen=True)
class CameraTarget:
    ts: float
    frame_width: float
    frame_height: float
    target: np.ndarray


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ts_seconds(value: str | None) -> float | None:
    dt = _parse_ts(value)
    return dt.timestamp() if dt else None


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL row") from exc


def _decode_csi(raw_b64: str) -> tuple[str, np.ndarray] | None:
    try:
        raw = base64.b64decode(raw_b64)
    except Exception:
        return None
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
    return key, amplitude


def _load_csi_rows(dataset: Path) -> list[CsiRow]:
    rows: list[CsiRow] = []
    for row in _iter_jsonl(dataset / "csi.jsonl"):
        ts = _ts_seconds(row.get("ts"))
        decoded = _decode_csi(row.get("raw_b64") or "")
        if ts is None or decoded is None:
            continue
        key, amplitude = decoded
        try:
            rssi = float(row.get("rssi"))
        except (TypeError, ValueError):
            rssi = 0.0
        rows.append(CsiRow(ts=ts, key=key, rssi=rssi, amplitude=amplitude))
    rows.sort(key=lambda item: item.ts)
    return rows


def _best_track(tracks: Any) -> dict[str, Any] | None:
    if not isinstance(tracks, list):
        return None
    candidates = [track for track in tracks if isinstance(track, dict) and track.get("keypoints")]
    if not candidates:
        return None

    def score(track: dict[str, Any]) -> float:
        keypoints = track.get("keypoints") or []
        confs = track.get("keypoint_conf") or []
        visible = 0
        conf_sum = 0.0
        for value in confs:
            try:
                conf = float(value)
            except (TypeError, ValueError):
                conf = 0.0
            if conf >= 0.25:
                visible += 1
            conf_sum += conf
        confidence = float(track.get("confidence") or 0.0)
        return len(keypoints) * 0.8 + visible * 1.4 + conf_sum * 0.15 + confidence

    return max(candidates, key=score)


def _target_from_track(track: dict[str, Any], frame_width: float, frame_height: float) -> np.ndarray | None:
    keypoints = track.get("keypoints")
    if not isinstance(keypoints, list) or len(keypoints) < 17:
        return None
    coords: list[float] = []
    xs: list[float] = []
    ys: list[float] = []
    for point in keypoints[:17]:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        try:
            x = float(point[0]) / frame_width
            y = float(point[1]) / frame_height
        except (TypeError, ValueError, ZeroDivisionError):
            return None
        x = min(1.0, max(0.0, x))
        y = min(1.0, max(0.0, y))
        xs.append(x)
        ys.append(y)
        coords.extend([x, y])
    bbox = track.get("bbox") or track.get("tracking_bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        try:
            x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
            center_x = ((x1 + x2) * 0.5) / frame_width
            center_y = ((y1 + y2) * 0.5) / frame_height
            width = abs(x2 - x1) / frame_width
            height = abs(y2 - y1) / frame_height
        except (TypeError, ValueError, ZeroDivisionError):
            center_x = float(np.mean(xs))
            center_y = float(np.mean(ys))
            width = float(max(xs) - min(xs))
            height = float(max(ys) - min(ys))
    else:
        center_x = float(np.mean(xs))
        center_y = float(np.mean(ys))
        width = float(max(xs) - min(xs))
        height = float(max(ys) - min(ys))
    return np.asarray([center_x, center_y, width, height, *coords], dtype=np.float32)


def _load_camera_targets(dataset: Path) -> list[CameraTarget]:
    targets: list[CameraTarget] = []
    for row in _iter_jsonl(dataset / "camera.jsonl"):
        ts = _ts_seconds(row.get("ts"))
        if ts is None:
            continue
        frame_width = float(row.get("frame_width") or 0.0)
        frame_height = float(row.get("frame_height") or 0.0)
        if frame_width <= 0 or frame_height <= 0:
            continue
        track = _best_track(row.get("tracks"))
        if track is None:
            continue
        target = _target_from_track(track, frame_width, frame_height)
        if target is None:
            continue
        targets.append(CameraTarget(ts=ts, frame_width=frame_width, frame_height=frame_height, target=target))
    targets.sort(key=lambda item: item.ts)
    return targets


def _bin_amplitude(amplitude: np.ndarray, bins: int) -> np.ndarray:
    if amplitude.size == 0:
        return np.zeros(bins, dtype=np.float32)
    chunks = np.array_split(amplitude, bins)
    return np.asarray([float(np.mean(chunk)) if chunk.size else 0.0 for chunk in chunks], dtype=np.float32)


def _feature_names(keys: list[str], bins: int) -> list[str]:
    names: list[str] = []
    for key in keys:
        names.extend([f"{key}:count", f"{key}:rssi_mean", f"{key}:rssi_std", f"{key}:amp_mean", f"{key}:amp_std"])
        names.extend(f"{key}:amp_bin_mean_{idx:02d}" for idx in range(bins))
        names.extend(f"{key}:amp_bin_std_{idx:02d}" for idx in range(bins))
    return names


def _build_feature_matrix(
    csi_rows: list[CsiRow],
    targets: list[CameraTarget],
    window_seconds: float,
    bins: int,
) -> tuple[np.ndarray, np.ndarray, list[str], list[int]]:
    keys = sorted({row.key for row in csi_rows})
    feature_names = _feature_names(keys, bins)
    key_index = {key: index for index, key in enumerate(keys)}
    stride = 5 + bins * 2
    features: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    sample_counts: list[int] = []
    csi_ts = np.asarray([row.ts for row in csi_rows], dtype=np.float64)

    for target in targets:
        left = int(np.searchsorted(csi_ts, target.ts - window_seconds, side="left"))
        right = int(np.searchsorted(csi_ts, target.ts, side="right"))
        window = csi_rows[left:right]
        if not window:
            continue
        by_key: dict[str, list[CsiRow]] = {}
        for row in window:
            by_key.setdefault(row.key, []).append(row)
        vector = np.zeros(len(keys) * stride, dtype=np.float32)
        for key, key_rows in by_key.items():
            offset = key_index[key] * stride
            rssi = np.asarray([row.rssi for row in key_rows], dtype=np.float32)
            amps = np.concatenate([row.amplitude for row in key_rows if row.amplitude.size])
            binned = np.asarray([_bin_amplitude(row.amplitude, bins) for row in key_rows if row.amplitude.size])
            vector[offset] = min(len(key_rows), 50) / 50.0
            vector[offset + 1] = float(np.mean(rssi)) if rssi.size else 0.0
            vector[offset + 2] = float(np.std(rssi)) if rssi.size else 0.0
            vector[offset + 3] = float(np.mean(amps)) if amps.size else 0.0
            vector[offset + 4] = float(np.std(amps)) if amps.size else 0.0
            if binned.size:
                vector[offset + 5 : offset + 5 + bins] = np.mean(binned, axis=0)
                vector[offset + 5 + bins : offset + 5 + bins * 2] = np.std(binned, axis=0)
        features.append(vector)
        labels.append(target.target)
        sample_counts.append(len(window))
    if not features:
        raise ValueError("No trainable samples with CSI windows and camera targets")
    return np.vstack(features), np.vstack(labels), feature_names, sample_counts


def _fit_ridge(x_train: np.ndarray, y_train: np.ndarray, alpha: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = np.mean(x_train, axis=0)
    std = np.std(x_train, axis=0)
    std[std < 1e-6] = 1.0
    x_norm = (x_train - mean) / std
    x_aug = np.concatenate([x_norm, np.ones((x_norm.shape[0], 1), dtype=np.float32)], axis=1)
    regularizer = np.eye(x_aug.shape[1], dtype=np.float64) * float(alpha)
    regularizer[-1, -1] = 0.0
    weights = np.linalg.solve(x_aug.T @ x_aug + regularizer, x_aug.T @ y_train)
    return weights.astype(np.float32), mean.astype(np.float32), std.astype(np.float32)


def _predict(x: np.ndarray, weights: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    x_norm = (x - mean) / std
    x_aug = np.concatenate([x_norm, np.ones((x_norm.shape[0], 1), dtype=np.float32)], axis=1)
    return x_aug @ weights


def _metrics(y_true: np.ndarray, y_pred: np.ndarray, frame_width: float, frame_height: float) -> dict[str, float]:
    diff = y_pred - y_true
    center_dx = diff[:, 0] * frame_width
    center_dy = diff[:, 1] * frame_height
    center_error = np.sqrt(center_dx * center_dx + center_dy * center_dy)
    keypoint_error_px: list[float] = []
    for idx in range(4, y_true.shape[1], 2):
        dx = diff[:, idx] * frame_width
        dy = diff[:, idx + 1] * frame_height
        keypoint_error_px.extend(np.sqrt(dx * dx + dy * dy).tolist())
    return {
        "center_mae_px": round(float(np.mean(np.abs(center_dx)) + np.mean(np.abs(center_dy))), 2),
        "center_rmse_px": round(float(np.sqrt(np.mean(center_error * center_error))), 2),
        "center_median_error_px": round(float(np.median(center_error)), 2),
        "keypoint_rmse_px": round(float(np.sqrt(np.mean(np.asarray(keypoint_error_px) ** 2))), 2),
    }


def train(dataset: Path, output: Path, window_seconds: float, bins: int, alpha: float, test_ratio: float) -> dict[str, Any]:
    csi_rows = _load_csi_rows(dataset)
    targets = _load_camera_targets(dataset)
    if len(targets) < 20:
        raise ValueError(f"Too few camera targets: {len(targets)}")
    x, y, feature_names, sample_counts = _build_feature_matrix(csi_rows, targets, window_seconds, bins)
    split = max(1, min(x.shape[0] - 1, int(math.floor(x.shape[0] * (1.0 - test_ratio)))))
    x_train, y_train = x[:split], y[:split]
    x_test, y_test = x[split:], y[split:]
    weights, mean, std = _fit_ridge(x_train, y_train, alpha=alpha)
    train_pred = _predict(x_train, weights, mean, std)
    test_pred = _predict(x_test, weights, mean, std)

    frame_width = max(target.frame_width for target in targets)
    frame_height = max(target.frame_height for target in targets)
    report = {
        "dataset": str(dataset),
        "output": str(output),
        "window_seconds": window_seconds,
        "bins": bins,
        "alpha": alpha,
        "feature_count": int(x.shape[1]),
        "target_count": int(x.shape[0]),
        "train_samples": int(x_train.shape[0]),
        "test_samples": int(x_test.shape[0]),
        "csi_rows": len(csi_rows),
        "camera_targets": len(targets),
        "feature_keys": sorted({row.key for row in csi_rows}),
        "csi_window_samples": {
            "min": int(min(sample_counts)),
            "median": float(np.median(sample_counts)),
            "max": int(max(sample_counts)),
        },
        "train_metrics": _metrics(y_train, train_pred, frame_width, frame_height),
        "test_metrics": _metrics(y_test, test_pred, frame_width, frame_height),
    }
    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output / "ridge_pose_model.npz",
        weights=weights,
        mean=mean,
        std=std,
        feature_names=np.asarray(feature_names, dtype=object),
        report=json.dumps(report, ensure_ascii=False),
    )
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a baseline CSI to camera-pose calibrator.")
    parser.add_argument("dataset", type=Path, help="Prepared RuView calibration dataset directory")
    parser.add_argument("--output", type=Path, help="Output model directory")
    parser.add_argument("--window-seconds", type=float, default=0.8)
    parser.add_argument("--bins", type=int, default=16)
    parser.add_argument("--alpha", type=float, default=35.0)
    parser.add_argument("--test-ratio", type=float, default=0.2)
    args = parser.parse_args()

    output = args.output or args.dataset / "model"
    report = train(
        dataset=args.dataset,
        output=output,
        window_seconds=args.window_seconds,
        bins=args.bins,
        alpha=args.alpha,
        test_ratio=args.test_ratio,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
