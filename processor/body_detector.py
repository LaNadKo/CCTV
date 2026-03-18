"""YOLOv8-nano person/body detection."""
from __future__ import annotations
import logging
import numpy as np

logger = logging.getLogger(__name__)
_model = None


def _load_model():
    global _model
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO("yolov8n.pt")
    return _model


def detect_bodies(frame_bgr: np.ndarray, conf: float = 0.5) -> list[dict]:
    model = _load_model()
    results = model(frame_bgr, verbose=False, conf=conf)
    detections = []
    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            if cls != 0:  # 0 = person
                continue
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            detections.append({"box": [float(x1), float(y1), float(x2), float(y2)], "confidence": float(box.conf[0])})
    return detections
