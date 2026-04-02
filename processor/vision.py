"""Face detection/recognition pipeline (standalone, aligned with backend)."""
from __future__ import annotations
import base64
import logging
import os
import threading
from pathlib import Path
import shutil
import sys
import urllib.request
import cv2
import numpy as np

from processor.config import settings

logger = logging.getLogger(__name__)

_mtcnn = None
_resnet = None
_device = "cpu"
_model_lock = threading.RLock()
_force_cpu_runtime = False

_FACE_PROB_MIN = 0.72
_MIN_FACE_SIDE_RATIO = 0.07
_MTCNN_WEIGHT_URLS = {
    "pnet.pt": "https://raw.githubusercontent.com/timesler/facenet-pytorch/master/data/pnet.pt",
    "rnet.pt": "https://raw.githubusercontent.com/timesler/facenet-pytorch/master/data/rnet.pt",
    "onet.pt": "https://raw.githubusercontent.com/timesler/facenet-pytorch/master/data/onet.pt",
}


def _normalize_vec(vec):
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm


def _build_detection_variants(frame_rgb: np.ndarray):
    yield frame_rgb
    try:
        ycrcb = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2YCrCb)
        ycrcb[:, :, 0] = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8)).apply(ycrcb[:, :, 0])
        enhanced = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2RGB)
        yield enhanced

        blurred = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=1.2)
        sharpened = cv2.addWeighted(enhanced, 1.35, blurred, -0.35, 0)
        yield sharpened

        gamma = np.clip(((enhanced.astype(np.float32) / 255.0) ** 0.85) * 255.0, 0, 255).astype(np.uint8)
        yield gamma
    except Exception:
        return


def _processor_cache_dir() -> Path | None:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    return Path(local_appdata) / "CCTV Processor" / "models" / "facenet_pytorch"


def _download_weight(name: str, target: Path) -> None:
    url = _MTCNN_WEIGHT_URLS[name]
    target.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading MTCNN weight %s from %s", name, url)
    urllib.request.urlretrieve(url, target)


def _candidate_weight_dirs(expected_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            return
        seen.add(key)
        candidates.append(path)

    add(expected_dir)
    add(_processor_cache_dir())

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        add(exe_dir / "facenet_pytorch" / "data")
        add(exe_dir / "_internal" / "facenet_pytorch" / "data")
        add(exe_dir / "models" / "facenet_pytorch")

    return candidates


def _ensure_mtcnn_weights() -> Path:
    from facenet_pytorch.models import mtcnn as mtcnn_module

    expected_dir = (Path(mtcnn_module.__file__).resolve().parent / "../data").resolve()
    expected_dir.mkdir(parents=True, exist_ok=True)

    missing = [name for name in _MTCNN_WEIGHT_URLS if not (expected_dir / name).exists()]
    if not missing:
        return expected_dir

    cache_dir = _processor_cache_dir()
    for name in missing:
        target = expected_dir / name
        copied = False
        for candidate_dir in _candidate_weight_dirs(expected_dir):
            source = candidate_dir / name
            if source.exists() and source.resolve() != target.resolve():
                shutil.copy2(source, target)
                logger.info("Copied MTCNN weight %s from %s", name, source)
                copied = True
                break
        if copied:
            continue

        if cache_dir is not None:
            cache_target = cache_dir / name
            if not cache_target.exists():
                _download_weight(name, cache_target)
            shutil.copy2(cache_target, target)
            logger.info("Prepared MTCNN weight %s in %s", name, target)
            continue

        _download_weight(name, target)
        logger.info("Prepared MTCNN weight %s in %s", name, target)

    return expected_dir


def _want_device() -> str:
    import torch

    if _force_cpu_runtime:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _reset_models(target_device: str | None = None) -> None:
    global _mtcnn, _resnet, _device
    _mtcnn = None
    _resnet = None
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
    logger.warning("Face inference switched to CPU fallback after CUDA failure: %s", reason)
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    _reset_models(target_device="cpu")


def _load_models():
    global _mtcnn, _resnet, _device
    target_device = _want_device()
    if _mtcnn is None or _resnet is None or _device != target_device:
        import torch
        from facenet_pytorch import MTCNN, InceptionResnetV1

        weights_dir = _ensure_mtcnn_weights()
        _device = target_device
        logger.info("Loading models on device=%s (mtcnn_weights=%s)", _device, weights_dir)
        if _device == "cuda":
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
        _mtcnn = MTCNN(
            image_size=160,
            margin=0,
            min_face_size=16,
            thresholds=[0.42, 0.5, 0.56],
            factor=0.709,
            post_process=True,
            keep_all=True,
            device=_device,
        )
        _resnet = InceptionResnetV1(pretrained="vggface2").eval().to(_device)
    return _mtcnn, _resnet


def get_inference_device() -> str:
    global _device
    if _mtcnn is not None:
        return _device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def detect_faces(frame_rgb: np.ndarray) -> list[dict]:
    """Detect faces and extract normalized embeddings using aligned MTCNN extraction."""
    try:
        return _detect_faces_impl(frame_rgb)
    except RuntimeError as exc:
        if _device == "cuda" and _is_cuda_runtime_error(exc):
            _switch_runtime_to_cpu(exc)
            return _detect_faces_impl(frame_rgb)
        raise


def _detect_faces_impl(frame_rgb: np.ndarray) -> list[dict]:
    with _model_lock:
        mtcnn, resnet = _load_models()
        import torch

        filtered_boxes = []
        filtered_probs = []
        source_frame = frame_rgb

        height, width = frame_rgb.shape[:2]
        min_face_side = max(height, width) * _MIN_FACE_SIDE_RATIO

        for variant in _build_detection_variants(frame_rgb):
            boxes, probs = mtcnn.detect(variant)
            if boxes is None or len(boxes) == 0:
                continue

            filtered_boxes = []
            filtered_probs = []
            for box, prob in zip(boxes, probs):
                if prob is None or prob < _FACE_PROB_MIN:
                    continue
                x1, y1, x2, y2 = [float(v) for v in box]
                if (x2 - x1) < min_face_side or (y2 - y1) < min_face_side:
                    continue
                filtered_boxes.append(box)
                filtered_probs.append(prob)

            if filtered_boxes:
                source_frame = variant
                break

        if not filtered_boxes:
            return []

        # Use MTCNN aligned extraction (same as backend vision.py)
        face_tensors = mtcnn.extract(source_frame, filtered_boxes, None)
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


def match_embedding(
    embedding: np.ndarray,
    gallery: list[dict],
    threshold: float | None = None,
) -> tuple[int | None, float]:
    """Match embedding against gallery using cosine similarity (aligned with backend)."""
    threshold = settings.face_match_threshold if threshold is None else threshold
    sim_margin = settings.face_match_margin
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

    effective_threshold = threshold
    if len(person_best) == 1:
        effective_threshold = max(effective_threshold, 0.68)

    margin_ok = len(person_best) == 1 or (best_sim - second_best >= sim_margin)
    if best_sim >= effective_threshold and margin_ok:
        return best_id, best_sim
    return None, best_sim
