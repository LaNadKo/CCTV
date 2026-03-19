"""SORT multi-object tracker (Kalman + Hungarian)."""
from __future__ import annotations
import numpy as np
from scipy.optimize import linear_sum_assignment


def iou(bb_a: np.ndarray, bb_b: np.ndarray) -> float:
    x1 = max(bb_a[0], bb_b[0])
    y1 = max(bb_a[1], bb_b[1])
    x2 = min(bb_a[2], bb_b[2])
    y2 = min(bb_a[3], bb_b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (bb_a[2] - bb_a[0]) * (bb_a[3] - bb_a[1])
    area_b = (bb_b[2] - bb_b[0]) * (bb_b[3] - bb_b[1])
    return inter / (area_a + area_b - inter + 1e-6)


class KalmanBoxTracker:
    _count = 0

    def __init__(self, bbox: np.ndarray):
        from filterpy.kalman import KalmanFilter
        self.kf = KalmanFilter(dim_x=7, dim_z=4)
        self.kf.F = np.array([
            [1,0,0,0,1,0,0],[0,1,0,0,0,1,0],[0,0,1,0,0,0,1],[0,0,0,1,0,0,0],
            [0,0,0,0,1,0,0],[0,0,0,0,0,1,0],[0,0,0,0,0,0,1]
        ], dtype=float)
        self.kf.H = np.array([
            [1,0,0,0,0,0,0],[0,1,0,0,0,0,0],[0,0,1,0,0,0,0],[0,0,0,1,0,0,0]
        ], dtype=float)
        self.kf.R[2:,2:] *= 10.
        self.kf.P[4:,4:] *= 1000.
        self.kf.P *= 10.
        self.kf.Q[-1,-1] *= 0.01
        self.kf.Q[4:,4:] *= 0.01
        cx = (bbox[0]+bbox[2])/2
        cy = (bbox[1]+bbox[3])/2
        w = bbox[2]-bbox[0]
        h = bbox[3]-bbox[1]
        self.kf.x[:4] = np.array([cx,cy,w,h]).reshape(4,1)
        self.id = KalmanBoxTracker._count
        KalmanBoxTracker._count += 1
        self.hits = 1
        self.age = 0
        self.time_since_update = 0

    def predict(self) -> np.ndarray:
        self.kf.predict()
        self.age += 1
        self.time_since_update += 1
        cx,cy,w,h = self.kf.x[:4].flatten()
        return np.array([cx-w/2, cy-h/2, cx+w/2, cy+h/2])

    def update(self, bbox: np.ndarray):
        self.time_since_update = 0
        self.hits += 1
        cx = (bbox[0]+bbox[2])/2
        cy = (bbox[1]+bbox[3])/2
        w = bbox[2]-bbox[0]
        h = bbox[3]-bbox[1]
        self.kf.update(np.array([cx,cy,w,h]))

    def get_state(self) -> np.ndarray:
        cx,cy,w,h = self.kf.x[:4].flatten()
        return np.array([cx-w/2, cy-h/2, cx+w/2, cy+h/2])


class SORTTracker:
    def __init__(self, max_age: int = 5, min_hits: int = 3, iou_threshold: float = 0.3):
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.trackers: list[KalmanBoxTracker] = []

    def update(self, detections: np.ndarray) -> list[tuple[np.ndarray, int]]:
        predicted = np.array([t.predict() for t in self.trackers]) if self.trackers else np.empty((0,4))
        if len(detections) == 0:
            self.trackers = [t for t in self.trackers if t.time_since_update <= self.max_age]
            return [(t.get_state(), t.id) for t in self.trackers if t.hits >= self.min_hits and t.time_since_update == 0]
        if len(predicted) > 0:
            cost = np.zeros((len(detections), len(predicted)))
            for d in range(len(detections)):
                for t in range(len(predicted)):
                    cost[d, t] = 1 - iou(detections[d], predicted[t])
            row_idx, col_idx = linear_sum_assignment(cost)
            matched_d, matched_t = set(), set()
            for d, t in zip(row_idx, col_idx):
                if cost[d, t] < 1 - self.iou_threshold:
                    self.trackers[t].update(detections[d])
                    matched_d.add(d)
                    matched_t.add(t)
            unmatched_d = [d for d in range(len(detections)) if d not in matched_d]
        else:
            unmatched_d = list(range(len(detections)))
        for d in unmatched_d:
            self.trackers.append(KalmanBoxTracker(detections[d]))
        self.trackers = [t for t in self.trackers if t.time_since_update <= self.max_age]
        return [(t.get_state(), t.id) for t in self.trackers if t.hits >= self.min_hits and t.time_since_update == 0]
