"""Body detection and tracking based on MMDeploy RTMDet + RTMPose."""
from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

from cctv_ai.runtime_env import select_mmdeploy_device

logger = logging.getLogger(__name__)

_RTMPOSE_CPU_URL = "https://download.openmmlab.com/mmpose/v1/projects/rtmpose/rtmpose-cpu.zip"

_tracker = None
_states: dict[str, object] = {}
_device = "cpu"
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


def _ensure_model_pack() -> Path:
    target_dir = _runtime_dir()
    det_dir = target_dir / "rtmdet-nano"
    pose_dir = target_dir / "rtmpose-m"
    if det_dir.exists() and pose_dir.exists():
        return target_dir

    archive_path = target_dir.parent / "rtmpose-cpu.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if not archive_path.exists():
        logger.info("Downloading MMDeploy RTMPose SDK to %s", archive_path)
        urllib.request.urlretrieve(_RTMPOSE_CPU_URL, archive_path)

    extract_root = target_dir.parent
    with zipfile.ZipFile(archive_path, "r") as archive:
        archive.extractall(extract_root)
    return target_dir


def _want_device() -> str:
    device, _diagnostics = select_mmdeploy_device()
    return device


def _load_tracker():
    global _tracker, _device
    target_dir = _ensure_model_pack()
    det_model = target_dir / "rtmdet-nano"
    pose_model = target_dir / "rtmpose-m"
    preferred_device = _want_device()
    if _tracker is None or _device != preferred_device:
        with _suppress_native_output():
            import mmdeploy_runtime as mmdeploy

        try:
            with _suppress_native_output():
                _tracker = mmdeploy.PoseTracker(str(det_model), str(pose_model), preferred_device)
            _device = preferred_device
        except Exception:
            if preferred_device != "cpu":
                logger.exception("MMDeploy PoseTracker failed to start on CUDA")
            raise
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
