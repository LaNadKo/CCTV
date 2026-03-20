"""Anti-spoofing: LBP texture + micro-movement."""
from __future__ import annotations
import cv2
import numpy as np


def lbp_texture_score(face_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0

    center = gray[1:-1, 1:-1]
    lbp = np.zeros_like(center, dtype=np.uint8)
    lbp |= ((gray[:-2, :-2] >= center).astype(np.uint8)) << 7
    lbp |= ((gray[:-2, 1:-1] >= center).astype(np.uint8)) << 6
    lbp |= ((gray[:-2, 2:] >= center).astype(np.uint8)) << 5
    lbp |= ((gray[1:-1, 2:] >= center).astype(np.uint8)) << 4
    lbp |= ((gray[2:, 2:] >= center).astype(np.uint8)) << 3
    lbp |= ((gray[2:, 1:-1] >= center).astype(np.uint8)) << 2
    lbp |= ((gray[2:, :-2] >= center).astype(np.uint8)) << 1
    lbp |= (gray[1:-1, :-2] >= center).astype(np.uint8)

    hist, _ = np.histogram(lbp.ravel(), bins=256, range=(0, 256))
    hist = hist.astype(float) / (hist.sum() + 1e-6)
    variance = np.var(hist)
    return float(variance)


def micro_movement_check(
    prev_gray: np.ndarray | None,
    curr_gray: np.ndarray,
    threshold: float = 2.0,
    pixel_threshold: float = 18.0,
    min_active_ratio: float = 0.02,
) -> bool:
    if prev_gray is None:
        return False
    diff = cv2.absdiff(prev_gray, curr_gray)
    mean_diff = float(np.mean(diff))
    active_ratio = float(np.mean(diff >= pixel_threshold))
    return mean_diff >= threshold and active_ratio >= min_active_ratio
