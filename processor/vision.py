"""Face detection/recognition pipeline (standalone, aligned with backend)."""
from __future__ import annotations
import base64
import logging
import numpy as np

logger = logging.getLogger(__name__)

_mtcnn = None
_resnet = None
_device = "cpu"

_SIM_MARGIN = 0.05
_FACE_PROB_MIN = 0.85


def _normalize_vec(vec):
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm


def _load_models():
    global _mtcnn, _resnet, _device
    if _mtcnn is None:
        import torch
        from facenet_pytorch import MTCNN, InceptionResnetV1
        _device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Loading models on device=%s", _device)
        if _device == "cuda":
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
        _mtcnn = MTCNN(
            image_size=160,
            margin=0,
            min_face_size=20,
            thresholds=[0.5, 0.6, 0.6],
            factor=0.709,
            post_process=True,
            keep_all=True,
            device=_device,
        )
        _resnet = InceptionResnetV1(pretrained="vggface2").eval().to(_device)
    return _mtcnn, _resnet


def detect_faces(frame_rgb: np.ndarray) -> list[dict]:
    """Detect faces and extract normalized embeddings using aligned MTCNN extraction."""
    mtcnn, resnet = _load_models()
    import torch

    boxes, probs = mtcnn.detect(frame_rgb)
    if boxes is None or len(boxes) == 0:
        return []

    # filter by probability
    filtered_boxes = []
    filtered_probs = []
    for box, prob in zip(boxes, probs):
        if prob is not None and prob >= _FACE_PROB_MIN:
            filtered_boxes.append(box)
            filtered_probs.append(prob)
    if not filtered_boxes:
        return []

    # Use MTCNN aligned extraction (same as backend vision.py)
    face_tensors = mtcnn.extract(frame_rgb, filtered_boxes, None)
    if face_tensors is None:
        return []

    if isinstance(face_tensors, torch.Tensor):
        faces = face_tensors
    else:
        faces = torch.stack([t for t in face_tensors if t is not None]) if len(face_tensors) else None
    if faces is None or faces.nelement() == 0:
        return []
    if faces.dim() == 3:
        faces = faces.unsqueeze(0)
    faces = faces.to(_device)

    with torch.no_grad():
        embs = resnet(faces).cpu().numpy()

    results = []
    for i, box in enumerate(filtered_boxes):
        if i >= len(embs):
            break
        emb = _normalize_vec(embs[i].astype(np.float32))
        results.append({
            "box": box.tolist() if hasattr(box, 'tolist') else list(box),
            "confidence": float(filtered_probs[i]) if filtered_probs[i] is not None else 0.0,
            "embedding": emb,
        })
    return results


def match_embedding(embedding: np.ndarray, gallery: list[dict], threshold: float = 0.25) -> tuple[int | None, float]:
    """Match embedding against gallery using cosine similarity (aligned with backend)."""
    embedding = _normalize_vec(embedding)

    # Group best similarity per person (multi-embedding support)
    person_best: dict[int, float] = {}
    for entry in gallery:
        ref_emb = np.frombuffer(base64.b64decode(entry["embedding_b64"]), dtype=np.float32)
        ref_emb = _normalize_vec(ref_emb)
        sim = float(np.dot(embedding, ref_emb))
        pid = entry["person_id"]
        if pid not in person_best or sim > person_best[pid]:
            person_best[pid] = sim

    if not person_best:
        return None, 0.0

    # Find best and second-best with margin check
    best_id = None
    best_sim = -1.0
    second_best = -1.0
    for pid, sim in person_best.items():
        if sim > best_sim:
            second_best = best_sim
            best_sim = sim
            best_id = pid
        elif sim > second_best:
            second_best = sim

    margin_ok = best_sim - second_best >= _SIM_MARGIN
    if best_sim >= threshold and margin_ok:
        return best_id, best_sim
    return None, best_sim
