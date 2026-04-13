"""Face detection and recognition based on SCRFD + ArcFace ONNX models."""
from __future__ import annotations

import base64
import numpy as np

from cctv_ai.face_onnx import (
    detect_faces_rgb,
    get_inference_device as _get_face_device,
    prewarm_models as _prewarm_face_models,
    normalize_vec,
)
from processor.config import settings


def prewarm_models() -> str:
    return _prewarm_face_models(prefer_gpu=True)


def get_inference_device() -> str:
    return _get_face_device()


def detect_faces(frame_rgb: np.ndarray) -> list[dict]:
    return detect_faces_rgb(
        frame_rgb,
        prob_min=0.46,
        min_face_ratio=0.028,
        det_size=(1024, 1024),
        build_variants=True,
        max_num=0,
    )


def match_embedding(
    embedding: np.ndarray,
    gallery: list[dict],
    threshold: float | None = None,
) -> tuple[int | None, float]:
    threshold = settings.face_match_threshold if threshold is None else threshold
    sim_margin = settings.face_match_margin
    probe = normalize_vec(np.asarray(embedding, dtype=np.float32))

    person_best: dict[int, float] = {}
    for entry in gallery:
        ref_emb = np.frombuffer(base64.b64decode(entry["embedding_b64"]), dtype=np.float32)
        ref_emb = normalize_vec(ref_emb)
        sim = float(np.dot(probe, ref_emb))
        person_id = int(entry["person_id"])
        if person_id not in person_best or sim > person_best[person_id]:
            person_best[person_id] = sim

    if not person_best:
        return None, 0.0

    best_id = None
    best_sim = -1.0
    second_best = -1.0
    for person_id, sim in person_best.items():
        if sim > best_sim:
            second_best = best_sim
            best_sim = sim
            best_id = person_id
        elif sim > second_best:
            second_best = sim

    effective_threshold = threshold
    if len(person_best) == 1:
        effective_threshold = max(effective_threshold, 0.68)

    margin_ok = len(person_best) == 1 or (best_sim - second_best >= sim_margin)
    if best_sim >= effective_threshold and margin_ok:
        return best_id, best_sim
    return None, best_sim
