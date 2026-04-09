import asyncio
import threading
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models

try:
    from PIL import Image, ImageDraw, ImageFont

    _PIL_AVAILABLE = True
except Exception:
    _PIL_AVAILABLE = False

_RU_LAT_MAP = {
    "Рђ": "A",
    "Р‘": "B",
    "Р’": "V",
    "Р“": "G",
    "Р”": "D",
    "Р•": "E",
    "РЃ": "E",
    "Р–": "Zh",
    "Р—": "Z",
    "Р": "I",
    "Р™": "Y",
    "Рљ": "K",
    "Р›": "L",
    "Рњ": "M",
    "Рќ": "N",
    "Рћ": "O",
    "Рџ": "P",
    "Р ": "R",
    "РЎ": "S",
    "Рў": "T",
    "РЈ": "U",
    "Р¤": "F",
    "РҐ": "Kh",
    "Р¦": "Ts",
    "Р§": "Ch",
    "РЁ": "Sh",
    "Р©": "Shch",
    "Р«": "Y",
    "Р­": "E",
    "Р®": "Yu",
    "РЇ": "Ya",
}
_RU_LAT_MAP.update({key.lower(): value.lower() for key, value in list(_RU_LAT_MAP.items())})

_SIM_MARGIN = 0.05
_FONT_CACHE = None
_model_lock = threading.Lock()
_FACE_RUNTIME = None


def _face_runtime():
    global _FACE_RUNTIME
    if _FACE_RUNTIME is None:
        from cctv_ai.face_onnx import (
            detect_faces_rgb,
            extract_best_face_embedding_bgr,
            normalize_vec,
            preprocess_frame,
        )

        _FACE_RUNTIME = {
            "detect_faces_rgb": detect_faces_rgb,
            "extract_best_face_embedding_bgr": extract_best_face_embedding_bgr,
            "normalize_vec": normalize_vec,
            "preprocess_frame": preprocess_frame,
        }
    return _FACE_RUNTIME


def _translit(text: str) -> str:
    return "".join(_RU_LAT_MAP.get(ch, ch) for ch in text)


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


def draw_labels(frame_bgr, labels):
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
        cv2.putText(
            frame_bgr,
            safe_text,
            (x1, max(y1 - 5, 0)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (color_rgb[2], color_rgb[1], color_rgb[0]),
            2,
            cv2.LINE_AA,
        )
    return frame_bgr


def _person_label(person: models.Person) -> str:
    parts = [person.last_name, person.first_name, person.middle_name]
    return " ".join([part for part in parts if part]) or f"ID {person.person_id}"


async def load_gallery(session: AsyncSession) -> List[Tuple[int, np.ndarray, str]]:
    normalize_vec = _face_runtime()["normalize_vec"]
    gallery: List[Tuple[int, np.ndarray, str]] = []
    res = await session.execute(
        select(models.PersonEmbedding, models.Person).join(
            models.Person, models.PersonEmbedding.person_id == models.Person.person_id
        )
    )
    for emb_row, person in res.all():
        try:
            emb = np.frombuffer(emb_row.embedding, dtype=np.float32)
            if emb.size == 0:
                continue
            gallery.append((person.person_id, normalize_vec(emb), _person_label(person)))
        except Exception:
            continue
    return gallery


def extract_best_face_embedding(image_bgr: np.ndarray) -> np.ndarray | None:
    extract_best_face_embedding_bgr = _face_runtime()["extract_best_face_embedding_bgr"]
    return extract_best_face_embedding_bgr(image_bgr, prob_min=0.46, min_face_ratio=0.028)


def _detect_and_embed(frame_bgr: np.ndarray):
    with _model_lock:
        runtime = _face_runtime()
        prepared = runtime["preprocess_frame"](frame_bgr)
        img_rgb = cv2.cvtColor(prepared, cv2.COLOR_BGR2RGB)
        faces = runtime["detect_faces_rgb"](
            img_rgb,
            prob_min=0.46,
            min_face_ratio=0.028,
            det_size=(1024, 1024),
            build_variants=True,
            max_num=0,
        )
        if not faces:
            return [], []
        embeddings = [np.asarray(face["embedding"], dtype=np.float32) for face in faces]
        boxes = [
            tuple(int(round(v)) for v in face["box"])
            for face in faces
        ]
        return embeddings, boxes


def _match_faces(
    embeddings: List[np.ndarray],
    boxes: List[Tuple[int, int, int, int]],
    gallery: List[Tuple[int, np.ndarray, str]],
    threshold: float,
):
    results = []
    for emb, box in zip(embeddings, boxes):
        person_best: dict[int, tuple[float, str]] = {}
        for person_id, gallery_embedding, label in gallery:
            if emb.shape != gallery_embedding.shape:
                continue
            sim = float(np.dot(emb, gallery_embedding))
            prev = person_best.get(person_id)
            if prev is None or sim > prev[0]:
                person_best[person_id] = (sim, label)

        best_id = None
        best_sim = -1.0
        best_label = None
        second_best = -1.0
        for person_id, (sim, label) in person_best.items():
            if sim > best_sim:
                second_best = best_sim
                best_sim = sim
                best_id = person_id
                best_label = label
            elif sim > second_best:
                second_best = sim

        margin_ok = best_sim - second_best >= _SIM_MARGIN
        recognized = best_id is not None and best_sim >= threshold and margin_ok
        results.append(
            {
                "box": box,
                "person_id": best_id if recognized else None,
                "confidence": best_sim if best_sim > 0 else None,
                "recognized": recognized,
                "label": best_label if recognized else "Unknown",
            }
        )
    return results


async def annotate_and_match(
    frame_bgr: np.ndarray,
    gallery: List[Tuple[int, np.ndarray, str]],
    threshold: float,
):
    embeddings, boxes = await asyncio.to_thread(_detect_and_embed, frame_bgr)
    if len(embeddings) == 0:
        return [], frame_bgr

    matches = _match_faces(embeddings, boxes, gallery, threshold)
    annotated = frame_bgr.copy()
    faces_info = []
    if _PIL_AVAILABLE:
        pil_img = Image.fromarray(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_img)
        font = _pick_font(16)
    else:
        pil_img = None

    for idx, match in enumerate(matches):
        x1, y1, x2, y2 = match["box"]
        recognized = bool(match["recognized"])
        label_text = match["label"] or "Unknown"
        if recognized and match["confidence"] is not None:
            label_text = f"{label_text} ({match['confidence']:.2f})"
        color = (0, 200, 0) if recognized else (200, 0, 0)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (color[2], color[1], color[0]), 2)
        if pil_img:
            try:
                draw.text((x1, max(y1 - 22, 0)), label_text, fill=tuple(color), font=font or ImageFont.load_default())
            except Exception:
                draw.text(
                    (x1, max(y1 - 22, 0)),
                    _translit(label_text),
                    fill=tuple(color),
                    font=font or ImageFont.load_default(),
                )
        else:
            cv2.putText(
                annotated,
                _translit(label_text),
                (x1, max(y1 - 5, 0)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (color[2], color[1], color[0]),
                2,
                cv2.LINE_AA,
            )
        faces_info.append((match["box"], label_text, recognized, match["person_id"], match["confidence"], embeddings[idx]))

    if pil_img:
        annotated = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    return faces_info, annotated
