import asyncio
import threading
from pathlib import Path
from typing import List, Tuple, Optional

import cv2
try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except Exception:
    _PIL_AVAILABLE = False

# simple ru->lat transliteration fallback (correct utf-8 characters)
_RU_LAT_MAP = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E", "Ж": "Zh", "З": "Z", "И": "I",
    "Й": "Y", "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T",
    "У": "U", "Ф": "F", "Х": "Kh", "Ц": "Ts", "Ч": "Ch", "Ш": "Sh", "Щ": "Shch", "Ы": "Y", "Э": "E",
    "Ю": "Yu", "Я": "Ya",
}
_RU_LAT_MAP.update({k.lower(): v.lower() for k, v in list(_RU_LAT_MAP.items())})


def _translit(text: str) -> str:
    return "".join(_RU_LAT_MAP.get(ch, ch) for ch in text)


def draw_labels(frame_bgr, labels):
    """Draw labels with Cyrillic support via PIL.
    labels: list of (x1, y1, text, color_rgb)
    """
    if not labels:
        return frame_bgr
    if _PIL_AVAILABLE:
        pil_img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_img)
        font = _pick_font(16)
        for x1, y1, text, color_rgb in labels:
            try:
                draw.text((x1, max(y1 - 22, 0)), text, fill=tuple(color_rgb), font=font or ImageFont.load_default())
            except Exception:
                safe_text = _translit(text)
                draw.text((x1, max(y1 - 22, 0)), safe_text, fill=tuple(color_rgb), font=font or ImageFont.load_default())
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    for x1, y1, text, color_rgb in labels:
        safe_text = _translit(text)
        cv2.putText(frame_bgr, safe_text, (x1, max(y1 - 5, 0)), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (color_rgb[2], color_rgb[1], color_rgb[0]), 2, cv2.LINE_AA)
    return frame_bgr


def _normalize_vec(vec):
    import numpy as _np
    norm = _np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm

_FONT_CACHE = None


def _pick_font(size: int = 16):
    global _FONT_CACHE
    if _FONT_CACHE:
        return _FONT_CACHE
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                _FONT_CACHE = ImageFont.truetype(path, size)
                return _FONT_CACHE
            except Exception:
                continue
    try:
        _FONT_CACHE = ImageFont.load_default()
    except Exception:
        _FONT_CACHE = None
    return _FONT_CACHE
import numpy as np
import torch
from facenet_pytorch import MTCNN, InceptionResnetV1
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models

import logging

log = logging.getLogger("app.face")

_mtcnn: Optional[MTCNN] = None
_embedder: Optional[InceptionResnetV1] = None
_device: str = "cpu"
_model_lock = threading.Lock()

_SIM_MARGIN = 0.05
_FACE_PROB_MIN = 0.85
_MIN_FACE_RATIO = 0.12


def _ensure_models():
    global _mtcnn, _embedder, _device
    if _mtcnn is not None and _embedder is not None:
        return _mtcnn, _embedder, _device
    _device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("[VISION] Initializing models on device=%s", _device)
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
    _embedder = InceptionResnetV1(pretrained="vggface2").eval().to(_device)
    return _mtcnn, _embedder, _device


def _person_label(p: models.Person) -> str:
    parts = [p.last_name, p.first_name, p.middle_name]
    label = " ".join([x for x in parts if x]) or f"ID {p.person_id}"
    return label


def _preprocess(frame_bgr: np.ndarray) -> np.ndarray:
    """Reduce overexposure: CLAHE on L channel in LAB."""
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l2 = clahe.apply(l)
    lab = cv2.merge((l2, a, b))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


async def load_gallery(session: AsyncSession) -> List[Tuple[int, np.ndarray, str]]:
    gallery: List[Tuple[int, np.ndarray, str]] = []
    # prefer multi-embedding table
    res = await session.execute(
        select(models.PersonEmbedding, models.Person)
        .join(models.Person, models.PersonEmbedding.person_id == models.Person.person_id)
    )
    rows = res.all()
    if rows:
        for emb_row, p in rows:
            try:
                emb = np.frombuffer(emb_row.embedding, dtype=np.float32)
                if emb.size == 0:
                    continue
                emb = _normalize_vec(emb)
                gallery.append((p.person_id, emb, _person_label(p)))
            except Exception:
                continue
    else:
        # legacy fallback
        res = await session.execute(select(models.Person).where(models.Person.embeddings.is_not(None)))
        persons = res.scalars().all()
        for p in persons:
            try:
                emb = np.frombuffer(p.embeddings, dtype=np.float32)
                if emb.size == 0:
                    continue
                emb = _normalize_vec(emb)
                gallery.append((p.person_id, emb, _person_label(p)))
            except Exception:
                continue
    log.info("gallery.loaded total=%d", len(gallery))
    return gallery


def _detect_and_embed(frame_bgr: np.ndarray):
    with _model_lock:
        return _detect_and_embed_inner(frame_bgr)


def _detect_and_embed_inner(frame_bgr: np.ndarray):
    mtcnn, embedder, device = _ensure_models()
    frame_bgr = _preprocess(frame_bgr)
    img_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    boxes, probs = mtcnn.detect(img_rgb)
    if boxes is None or len(boxes) == 0:
        return [], []
    h, w, _ = img_rgb.shape
    min_size = max(h, w) * _MIN_FACE_RATIO
    filtered = []
    for box, prob in zip(boxes, probs):
        if prob is not None and prob < _FACE_PROB_MIN:
            continue
        x1, y1, x2, y2 = [float(b) for b in box]
        if (x2 - x1) < min_size or (y2 - y1) < min_size:
            continue
        filtered.append((box, prob))
    if not filtered:
        return [], []
    # simple NMS to drop overlapping duplicates
    kept = []
    filtered.sort(key=lambda x: x[1] or 0, reverse=True)
    def iou(a, b):
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        inter_x1, inter_y1 = max(ax1, bx1), max(ay1, by1)
        inter_x2, inter_y2 = min(ax2, bx2), min(ay2, by2)
        inter = max(0, inter_x2 - inter_x1) * max(0, inter_y2 - inter_y1)
        area_a = (ax2 - ax1) * (ay2 - ay1)
        area_b = (bx2 - bx1) * (by2 - by1)
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0
    for box, prob in filtered:
        if any(iou(box, k[0]) > 0.5 for k in kept):
            continue
        kept.append((box, prob))

    boxes_kept = [k[0] for k in kept]
    # aligned face crops from MTCNN (pre-whitened with post_process=True)
    face_tensors = mtcnn.extract(img_rgb, boxes_kept, None)
    if face_tensors is None:
        return [], []
    if isinstance(face_tensors, torch.Tensor):
        faces = face_tensors
    else:
        faces = torch.stack([t for t in face_tensors if t is not None]) if len(face_tensors) else None
    if faces is None or faces.nelement() == 0:
        return [], []
    if faces.dim() == 3:
        faces = faces.unsqueeze(0)
    faces = faces.to(device)
    with torch.no_grad():
        embs = embedder(faces).cpu().numpy()
    embs = np.stack([_normalize_vec(e) for e in embs])
    int_boxes = [(int(x1), int(y1), int(x2), int(y2)) for x1, y1, x2, y2 in boxes_kept]
    return embs, int_boxes


def _match_faces(embs: List[np.ndarray], boxes: List[Tuple[int, int, int, int]], gallery: List[Tuple[int, np.ndarray, str]], threshold: float):
    results = []
    for emb, box in zip(embs, boxes):
        # group best similarity per person (multi-embedding: pick best)
        person_best: dict[int, tuple[float, str]] = {}
        for pid, g_emb, label in gallery:
            if emb.shape != g_emb.shape:
                continue
            sim = float(np.dot(emb, g_emb))  # both L2-normalized
            prev = person_best.get(pid)
            if prev is None or sim > prev[0]:
                person_best[pid] = (sim, label)

        best_id = None
        best_sim = -1.0
        best_label = None
        second_best = -1.0
        for pid, (sim, label) in person_best.items():
            if sim > best_sim:
                second_best = best_sim
                best_sim = sim
                best_id = pid
                best_label = label
            elif sim > second_best:
                second_best = sim

        margin_ok = best_sim - second_best >= _SIM_MARGIN
        recognized = best_id is not None and best_sim >= threshold and margin_ok
        results.append({
            "box": box,
            "person_id": best_id if recognized else None,
            "confidence": best_sim if best_sim > 0 else None,
            "recognized": recognized,
            "label": best_label if recognized else "Unknown",
        })
    return results


async def annotate_and_match(frame_bgr: np.ndarray, gallery: List[Tuple[int, np.ndarray, str]], threshold: float):
    # используем исходный кадр, чтобы совпадать с пайплайном энролла
    embs, boxes = await asyncio.to_thread(_detect_and_embed, frame_bgr)
    if len(embs) == 0:
        return [], frame_bgr
    matches = _match_faces(embs, boxes, gallery, threshold)
    annotated = frame_bgr.copy()
    faces_info = []
    if _PIL_AVAILABLE:
        pil_img = Image.fromarray(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_img)
        font = _pick_font(16)
    else:
        pil_img = None

    for idx, m in enumerate(matches):
        x1, y1, x2, y2 = m["box"]
        recognized = m["recognized"]
        label_text = m["label"] or "Unknown"
        if recognized and m["confidence"] is not None:
            label_text = f"{label_text} ({m['confidence']:.2f})"
        color = (0, 200, 0) if recognized else (200, 0, 0)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (color[2], color[1], color[0]), 2)  # BGR
        if pil_img:
            try:
                draw.text((x1, max(y1 - 22, 0)), label_text, fill=tuple(color), font=font or ImageFont.load_default())
            except Exception:
                safe_label = _translit(label_text)
                draw.text((x1, max(y1 - 22, 0)), safe_label, fill=tuple(color), font=font or ImageFont.load_default())
        else:
            # fallback ascii for OpenCV
            safe_label = _translit(label_text)
            cv2.putText(annotated, safe_label, (x1, max(y1 - 5, 0)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (color[2], color[1], color[0]), 2, cv2.LINE_AA)
        faces_info.append((m["box"], label_text, recognized, m["person_id"], m["confidence"], embs[idx]))

    if pil_img:
        annotated = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    return faces_info, annotated
