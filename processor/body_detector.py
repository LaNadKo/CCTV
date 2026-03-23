"""YOLO pose detection with person boxes and keypoints."""
from __future__ import annotations
import logging
import threading
import numpy as np

logger = logging.getLogger(__name__)
_model = None
_device = "cpu"
_model_lock = threading.RLock()
_force_cpu_runtime = False


def _box_iou(box_a: list[float], box_b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
    area_a = max(1.0, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1.0, (bx2 - bx1) * (by2 - by1))
    return inter / (area_a + area_b - inter + 1e-6)


def _load_model():
    global _model, _device
    target_device = _want_device()
    if _model is None or _device != target_device:
        from ultralytics import YOLO
        _device = target_device
        _model = YOLO("yolov8n-pose.pt")
        try:
            _model.fuse()
        except Exception:
            logger.debug("YOLO pose model fuse skipped", exc_info=True)
    return _model


def _want_device() -> str:
    if _force_cpu_runtime:
        return "cpu"
    try:
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _reset_model(target_device: str | None = None) -> None:
    global _model, _device
    _model = None
    if target_device:
        _device = target_device


def _is_cuda_runtime_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "cuda error" in text or "device-side assert" in text or "misaligned address" in text


def _switch_runtime_to_cpu(reason: BaseException | str) -> None:
    global _force_cpu_runtime
    if _force_cpu_runtime:
        return
    _force_cpu_runtime = True
    logger.warning("Body inference switched to CPU fallback after CUDA failure: %s", reason)
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    _reset_model(target_device="cpu")


def detect_bodies(frame_bgr: np.ndarray, conf: float = 0.5) -> list[dict]:
    try:
        return _detect_bodies_impl(frame_bgr, conf=conf)
    except RuntimeError as exc:
        if _device.startswith("cuda") and _is_cuda_runtime_error(exc):
            _switch_runtime_to_cpu(exc)
            return _detect_bodies_impl(frame_bgr, conf=conf)
        raise


def _detect_bodies_impl(frame_bgr: np.ndarray, conf: float = 0.5) -> list[dict]:
    with _model_lock:
        model = _load_model()
        results = model.predict(
            frame_bgr,
            verbose=False,
            conf=conf,
            device=_device,
            imgsz=512,
            max_det=6,
            classes=[0],
            half=_device.startswith("cuda"),
        )
        detections = []
        for r in results:
            keypoints_xy = r.keypoints.xy.cpu().numpy() if r.keypoints is not None and r.keypoints.xy is not None else None
            keypoints_conf = r.keypoints.conf.cpu().numpy() if r.keypoints is not None and r.keypoints.conf is not None else None
            for idx, box in enumerate(r.boxes):
                cls = int(box.cls[0])
                if cls != 0:  # 0 = person
                    continue
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                payload = {
                    "box": [float(x1), float(y1), float(x2), float(y2)],
                    "confidence": float(box.conf[0]),
                }
                if keypoints_xy is not None and idx < len(keypoints_xy):
                    payload["keypoints"] = keypoints_xy[idx].tolist()
                if keypoints_conf is not None and idx < len(keypoints_conf):
                    payload["keypoint_conf"] = keypoints_conf[idx].tolist()
                detections.append(payload)
        detections.sort(key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
        deduped: list[dict] = []
        for candidate in detections:
            if any(_box_iou(candidate["box"], existing["box"]) >= 0.55 for existing in deduped):
                continue
            deduped.append(candidate)
        return deduped
