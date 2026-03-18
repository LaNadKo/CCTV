"""Anti-spoofing: LBP texture + micro-movement."""
from __future__ import annotations
import cv2
import numpy as np


def lbp_texture_score(face_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    lbp = np.zeros_like(gray, dtype=np.uint8)
    for i in range(1, h - 1):
        for j in range(1, w - 1):
            center = gray[i, j]
            code = 0
            code |= (gray[i-1,j-1] >= center) << 7
            code |= (gray[i-1,j] >= center) << 6
            code |= (gray[i-1,j+1] >= center) << 5
            code |= (gray[i,j+1] >= center) << 4
            code |= (gray[i+1,j+1] >= center) << 3
            code |= (gray[i+1,j] >= center) << 2
            code |= (gray[i+1,j-1] >= center) << 1
            code |= (gray[i,j-1] >= center)
            lbp[i, j] = code
    hist, _ = np.histogram(lbp.ravel(), bins=256, range=(0, 256))
    hist = hist.astype(float) / (hist.sum() + 1e-6)
    variance = np.var(hist)
    return float(variance)


def micro_movement_check(prev_gray: np.ndarray | None, curr_gray: np.ndarray, threshold: float = 2.0) -> bool:
    if prev_gray is None:
        return True
    diff = cv2.absdiff(prev_gray, curr_gray)
    mean_diff = float(np.mean(diff))
    return mean_diff > threshold
