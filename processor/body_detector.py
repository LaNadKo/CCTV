"""Body detection and tracking based on MMDeploy RTMDet + RTMPose."""
from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

from cctv_ai.model_artifacts import download_verified_https, file_matches_sha256, safe_extract_zip
from cctv_ai.runtime_env import select_mmdeploy_device

logger = logging.getLogger(__name__)

_RTMPOSE_CPU_URL = "https://download.openmmlab.com/mmpose/v1/projects/rtmpose/rtmpose-cpu.zip"
_RTMPOSE_CPU_SHA256 = "54e1d48a8946c87d66e96f81438344fec6e471cb3e44b71dfa04be6e879f3528"
_RTMDET_NANO_SHA256 = "b8585adb6d1352796f6e86337e09c3459b830645a7e7192d9381670bea2facbd"
_RTMPOSE_M_SHA256 = "8ed9cd4724582d00e7978c297472365946277185ecc448d4ad47f4f376ae3208"

_tracker = None
_states: dict[str, object] = {}
_device = "cpu"
_failed_device: str | None = None
_failed_device_until = 0.0
_DEVICE_RETRY_SECONDS = 60.0
_model_lock = threading.RLock()


@contextlib.contextmanager
def _suppress_native_output():
    if os.environ.get("CCTV_PROCESSOR_DEBUG_NATIVE_OUTPUT"):
        yield
        return
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    try:
        stdout_fd = os.dup(1)
        stderr_fd = os.dup(2)
    except OSError:
        yield
        return
    try:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            os.dup2(devnull.fileno(), 1)
            os.dup2(devnull.fileno(), 2)
            yield
    finally:
        try:
            os.dup2(stdout_fd, 1)
            os.dup2(stderr_fd, 2)
        finally:
            os.close(stdout_fd)
            os.close(stderr_fd)


def _runtime_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "CCTV Processor" / "models" / "mmpose" / "rtmpose-cpu" / "rtmpose-ort"
    return Path(".models") / "mmpose" / "rtmpose-cpu" / "rtmpose-ort"


def _model_pack_valid(target_dir: Path) -> bool:
    return file_matches_sha256(
        target_dir / "rtmdet-nano" / "end2end.onnx",
        _RTMDET_NANO_SHA256,
    ) and file_matches_sha256(
        target_dir / "rtmpose-m" / "end2end.onnx",
        _RTMPOSE_M_SHA256,
    )


def _ensure_model_pack() -> Path:
    target_dir = _runtime_dir()
    if _model_pack_valid(target_dir):
        return target_dir

    archive_path = target_dir.parent / "rtmpose-cpu.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if not file_matches_sha256(archive_path, _RTMPOSE_CPU_SHA256):
        logger.info("Downloading verified MMDeploy RTMPose SDK to %s", archive_path)
    download_verified_https(
        _RTMPOSE_CPU_URL,
        archive_path,
        expected_sha256=_RTMPOSE_CPU_SHA256,
        max_bytes=64 * 1024 * 1024,
    )
    safe_extract_zip(
        archive_path,
        target_dir.parent,
        max_members=32,
        max_uncompressed_bytes=80 * 1024 * 1024,
    )
    if not _model_pack_valid(target_dir):
        raise RuntimeError("MMDeploy RTMPose model pack failed integrity validation after extraction")
    return target_dir


def _want_device() -> str:
    device, _diagnostics = select_mmdeploy_device()
    return device


def _effective_device() -> str:
    preferred_device = _want_device()
    if (
        preferred_device != "cpu"
        and _failed_device == preferred_device
        and time.monotonic() < _failed_device_until
    ):
        return "cpu"
    return preferred_device


def _load_tracker():
    global _failed_device, _failed_device_until, _tracker, _device
    target_dir = _ensure_model_pack()
    det_model = target_dir / "rtmdet-nano"
    pose_model = target_dir / "rtmpose-m"
    preferred_device = _effective_device()
    if _tracker is None or _device != preferred_device:
        with _suppress_native_output():
            import mmdeploy_runtime as mmdeploy

        try:
            with _suppress_native_output():
                _tracker = mmdeploy.PoseTracker(str(det_model), str(pose_model), preferred_device)
            _device = preferred_device
            if preferred_device != "cpu":
                _failed_device = None
                _failed_device_until = 0.0
        except Exception:
            if preferred_device == "cpu":
                raise
            _failed_device = preferred_device
            _failed_device_until = time.monotonic() + _DEVICE_RETRY_SECONDS
            logger.exception("MMDeploy PoseTracker failed to start on %s; retrying on CPU", preferred_device)
            with _suppress_native_output():
                _tracker = mmdeploy.PoseTracker(str(det_model), str(pose_model), "cpu")
            _device = "cpu"
    return _tracker


def _state_key(camera_key: object | None) -> str:
    if camera_key is None:
        return "default"
    return str(camera_key)


def _get_state(camera_key: object | None):
    tracker = _load_tracker()
    key = _state_key(camera_key)
    state = _states.get(key)
    if state is None:
        state = tracker.create_state(det_interval=1, det_min_bbox_size=32, keypoint_sigmas=[])
        _states[key] = state
    return tracker, state


def release_camera_state(camera_key: object | None) -> None:
    with _model_lock:
        _states.pop(_state_key(camera_key), None)


def prewarm_model() -> str:
    with _model_lock:
        _load_tracker()
        return _device


def detect_bodies(frame_bgr: np.ndarray, conf: float = 0.5, camera_key: object | None = None) -> list[dict]:
    with _model_lock:
        tracker, state = _get_state(camera_key)
        keypoints_arr, boxes_arr, track_ids_arr = tracker(state, frame_bgr, -1)

    detections: list[dict] = []
    if keypoints_arr is None or boxes_arr is None:
        return detections

    keypoints_arr = np.asarray(keypoints_arr)
    boxes_arr = np.asarray(boxes_arr)
    raw_track_ids = np.asarray(track_ids_arr).reshape(-1) if track_ids_arr is not None else None
    use_track_ids = False
    if raw_track_ids is not None and len(raw_track_ids) >= len(boxes_arr):
        current_ids = [int(value) for value in raw_track_ids[: len(boxes_arr)]]
        use_track_ids = len(set(current_ids)) == len(current_ids)

    for idx, box in enumerate(boxes_arr):
        if idx >= len(keypoints_arr):
            break
        keypoints = np.asarray(keypoints_arr[idx], dtype=np.float32)
        if keypoints.ndim != 2 or keypoints.shape[1] < 3:
            continue
        keypoint_xy = keypoints[:, :2]
        keypoint_conf = keypoints[:, 2]
        mean_conf = float(np.mean(keypoint_conf[:17])) if keypoint_conf.size else 0.0
        head_hits = sum(
            1
            for point_index in range(min(5, keypoint_conf.size))
            if float(keypoint_conf[point_index]) >= 0.16
        )
        shoulder_hits = sum(
            1
            for point_index in (5, 6)
            if point_index < keypoint_conf.size
            and float(keypoint_conf[point_index]) >= 0.18
        )
        upper_body_supported = shoulder_hits >= 2 and head_hits >= 2
        if mean_conf < max(conf * 0.4, 0.08) and not upper_body_supported:
            continue
        payload = {
            "box": [float(v) for v in box[:4]],
            "confidence": mean_conf,
            "keypoints": keypoint_xy.tolist(),
            "keypoint_conf": keypoint_conf.tolist(),
        }
        if use_track_ids and raw_track_ids is not None:
            payload["track_id"] = int(raw_track_ids[idx])
        detections.append(payload)

    return detections
