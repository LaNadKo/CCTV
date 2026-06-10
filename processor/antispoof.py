"""Anti-spoofing helpers for face liveness checks."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import logging
import os
import sys
import threading
import urllib.request
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_PRIMARY_MODEL_NAME = "MiniFASNetV2.onnx"
_PRIMARY_MODEL_URL = "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx"
_PRIMARY_MODEL_SHA256 = "b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907"
_SECONDARY_MODEL_NAME = "MiniFASNetV2-Ensemble.onnx"
_SECONDARY_MODEL_SHA256 = "af2381b88f38769222ed93379e12444e2a50814575de1c46170de570c55a42b6"
_MODEL_MIN_SIZE = 500_000


@dataclass(frozen=True)
class _ModelPrediction:
    real_score: float
    fake_score: float
    provider: str

    @property
    def is_real(self) -> bool:
        return self.real_score >= self.fake_score


@dataclass(frozen=True)
class FaceAntiSpoofPrediction:
    primary_real_score: float | None
    primary_fake_score: float | None
    primary_provider: str
    secondary_real_score: float | None
    secondary_fake_score: float | None
    secondary_provider: str

    @property
    def has_primary(self) -> bool:
        return self.primary_real_score is not None and self.primary_fake_score is not None

    @property
    def has_secondary(self) -> bool:
        return self.secondary_real_score is not None and self.secondary_fake_score is not None


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


def _softmax(logits: np.ndarray) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float32)
    if values.ndim == 1:
        values = values.reshape(1, -1)
    values = values - np.max(values, axis=1, keepdims=True)
    exp = np.exp(values)
    return exp / np.maximum(exp.sum(axis=1, keepdims=True), 1e-6)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_model(path: Path, expected_sha256: str) -> bool:
    try:
        if not path.exists() or path.stat().st_size < _MODEL_MIN_SIZE:
            return False
        return _sha256(path).lower() == expected_sha256
    except OSError:
        return False


def _asset_model_candidates(model_name: str, env_name: str) -> list[Path]:
    explicit = os.environ.get(env_name, "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "processor" / "assets" / "models" / "antispoof" / model_name)
        candidates.append(Path(meipass) / "assets" / "models" / "antispoof" / model_name)
    candidates.append(Path(__file__).resolve().parent / "assets" / "models" / "antispoof" / model_name)
    try:
        executable_dir = Path(sys.executable).resolve().parent
        candidates.append(executable_dir / "processor" / "assets" / "models" / "antispoof" / model_name)
        candidates.append(executable_dir / "assets" / "models" / "antispoof" / model_name)
        candidates.append(executable_dir / "models" / "antispoof" / model_name)
    except Exception:
        pass
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def _download_primary_model(target: Path) -> Path | None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".download")
        urllib.request.urlretrieve(
            _PRIMARY_MODEL_URL,
            tmp,
        )
        if not _valid_model(tmp, _PRIMARY_MODEL_SHA256):
            tmp.unlink(missing_ok=True)
            logger.warning("Downloaded anti-spoof model failed checksum validation")
            return None
        tmp.replace(target)
        return target
    except Exception:
        logger.warning("Failed to download anti-spoof model", exc_info=True)
        return None


def _find_model_path(
    model_name: str,
    expected_sha256: str,
    env_name: str,
    *,
    download_primary: bool = False,
) -> Path | None:
    for candidate in _asset_model_candidates(model_name, env_name):
        if _valid_model(candidate, expected_sha256):
            return candidate
    if not download_primary:
        logger.warning("Bundled anti-spoof ensemble model is unavailable or failed checksum validation")
        return None
    try:
        fallback = Path(sys.executable).resolve().parent / "models" / "antispoof" / model_name
    except Exception:
        fallback = Path.cwd() / "models" / "antispoof" / model_name
    return _download_primary_model(fallback)


class _OnnxAntiSpoofModel:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session = None
        self._input_name = ""
        self._output_name = ""
        self._input_size = (80, 80)
        self._provider = "unavailable"
        self._failed = False

    def _ensure_session(self) -> bool:
        if self._session is not None:
            return True
        if self._failed:
            return False
        with self._lock:
            if self._session is not None:
                return True
            if self._failed:
                return False
            try:
                from cctv_ai.runtime_env import select_onnx_execution_providers
                from processor.config import settings
                import onnxruntime as ort

                model_path = self._find_model_path()
                if model_path is None:
                    self._failed = True
                    return False
                providers, _device, provider = select_onnx_execution_providers(
                    prefer_gpu=settings.processor_accel != "cpu",
                    preference=settings.processor_accel,
                )
                session_options = ort.SessionOptions()
                session_options.log_severity_level = 3
                session = ort.InferenceSession(
                    str(model_path),
                    sess_options=session_options,
                    providers=providers,
                )
                input_cfg = session.get_inputs()[0]
                output_cfg = session.get_outputs()[0]
                shape = input_cfg.shape
                height = shape[2] if len(shape) > 2 and isinstance(shape[2], int) else 80
                width = shape[3] if len(shape) > 3 and isinstance(shape[3], int) else height
                self._session = session
                self._input_name = input_cfg.name
                self._output_name = output_cfg.name
                self._input_size = (int(width), int(height))
                active_providers = session.get_providers()
                self._provider = active_providers[0] if active_providers else provider
                logger.info("Anti-spoof model loaded path=%s provider=%s", model_path, self._provider)
                return True
            except Exception:
                self._failed = True
                logger.exception("Failed to load anti-spoof ONNX model")
                return False

    def _find_model_path(self) -> Path | None:
        raise NotImplementedError

    def _crop_face(self, frame_bgr: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray | None:
        raise NotImplementedError

    def _scores(self, output: np.ndarray) -> tuple[float, float] | None:
        raise NotImplementedError

    def predict(self, frame_bgr: np.ndarray, box: tuple[int, int, int, int]) -> _ModelPrediction | None:
        if not self._ensure_session():
            return None
        tensor = self._crop_face(frame_bgr, box)
        if tensor is None:
            return None
        try:
            outputs = self._session.run([self._output_name], {self._input_name: tensor})
        except Exception:
            logger.debug("Anti-spoof inference failed", exc_info=True)
            return None
        scores = self._scores(outputs[0])
        if scores is None:
            return None
        real_score, fake_score = scores
        return _ModelPrediction(
            real_score=real_score,
            fake_score=fake_score,
            provider=self._provider,
        )


class _PrimaryMiniFASNetAntiSpoof(_OnnxAntiSpoofModel):
    def _find_model_path(self) -> Path | None:
        return _find_model_path(
            _PRIMARY_MODEL_NAME,
            _PRIMARY_MODEL_SHA256,
            "ANTISPOOF_MODEL_PATH",
            download_primary=True,
        )

    def _crop_face(self, frame_bgr: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray | None:
        src_h, src_w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = box
        x, y = int(x1), int(y1)
        box_w = max(1, int(x2 - x1))
        box_h = max(1, int(y2 - y1))
        if box_w <= 1 or box_h <= 1:
            return None
        scale = min((src_h - 1) / max(box_h, 1), (src_w - 1) / max(box_w, 1), 2.7)
        new_w = box_w * scale
        new_h = box_h * scale
        center_x = x + box_w / 2
        center_y = y + box_h / 2
        x1 = max(0, int(center_x - new_w / 2))
        y1 = max(0, int(center_y - new_h / 2))
        x2 = min(src_w - 1, int(center_x + new_w / 2))
        y2 = min(src_h - 1, int(center_y + new_h / 2))
        if x2 <= x1 or y2 <= y1:
            return None
        crop = frame_bgr[y1 : y2 + 1, x1 : x2 + 1]
        if crop.size == 0:
            return None
        crop = cv2.resize(crop, self._input_size)


        tensor = crop.astype(np.float32)
        tensor = np.transpose(tensor, (2, 0, 1))
        return np.expand_dims(tensor, axis=0)

    def _scores(self, output: np.ndarray) -> tuple[float, float] | None:
        probs = _softmax(output)
        if probs.shape[1] < 2:
            return None


        real_score = float(probs[0, 1])
        fake_score = float(np.sum(probs[0, [0, 2]]))
        return real_score, fake_score


class _SecondaryMiniFASNetAntiSpoof(_OnnxAntiSpoofModel):
    def __init__(self) -> None:
        super().__init__()
        self._input_size = (128, 128)

    def _find_model_path(self) -> Path | None:
        return _find_model_path(
            _SECONDARY_MODEL_NAME,
            _SECONDARY_MODEL_SHA256,
            "ANTISPOOF_ENSEMBLE_MODEL_PATH",
        )

    def _crop_face_at_scale(
        self,
        frame_bgr: np.ndarray,
        box: tuple[int, int, int, int],
        scale: float,
    ) -> np.ndarray | None:
        src_h, src_w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = box
        box_w = max(1, int(x2 - x1))
        box_h = max(1, int(y2 - y1))
        crop_size = max(2, int(max(box_w, box_h) * scale))
        center_x = x1 + box_w / 2
        center_y = y1 + box_h / 2
        crop_x = int(center_x - crop_size / 2)
        crop_y = int(center_y - crop_size / 2)
        crop_x1 = max(0, crop_x)
        crop_y1 = max(0, crop_y)
        crop_x2 = min(src_w, crop_x + crop_size)
        crop_y2 = min(src_h, crop_y + crop_size)
        if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
            return None
        crop = frame_bgr[crop_y1:crop_y2, crop_x1:crop_x2]
        crop = cv2.copyMakeBorder(
            crop,
            max(0, -crop_y),
            max(0, crop_y + crop_size - src_h),
            max(0, -crop_x),
            max(0, crop_x + crop_size - src_w),
            cv2.BORDER_REFLECT_101,
        )
        if crop.size == 0:
            return None
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        interpolation = cv2.INTER_AREA if crop_size > self._input_size[0] else cv2.INTER_LANCZOS4
        crop = cv2.resize(crop, self._input_size, interpolation=interpolation)
        tensor = np.transpose(crop, (2, 0, 1)).astype(np.float32) / 255.0
        return np.expand_dims(tensor, axis=0)

    def _crop_face(self, frame_bgr: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray | None:
        return self._crop_face_at_scale(frame_bgr, box, 1.5)

    def _scores(self, output: np.ndarray) -> tuple[float, float] | None:
        probs = _softmax(output)
        if probs.shape[1] < 2:
            return None
        return float(probs[0, 0]), float(probs[0, 1])

    def predict(self, frame_bgr: np.ndarray, box: tuple[int, int, int, int]) -> _ModelPrediction | None:
        if not self._ensure_session():
            return None
        tensors: list[np.ndarray] = []
        for scale in (0.9, 1.5):
            tensor = self._crop_face_at_scale(frame_bgr, box, scale)
            if tensor is not None:
                tensors.append(tensor)
        if not tensors:
            return None
        try:
            output = self._session.run(
                [self._output_name],
                {self._input_name: np.concatenate(tensors, axis=0)},
            )[0]
        except Exception:
            logger.debug("Anti-spoof ensemble inference failed", exc_info=True)
            return None
        probs = _softmax(output)
        if probs.shape[1] < 2:
            return None


        return _ModelPrediction(
            real_score=float(np.min(probs[:, 0])),
            fake_score=float(np.max(probs[:, 1])),
            provider=self._provider,
        )


_PRIMARY_MODEL = _PrimaryMiniFASNetAntiSpoof()
_SECONDARY_MODEL = _SecondaryMiniFASNetAntiSpoof()


def predict_face_liveness(frame_bgr: np.ndarray, box: tuple[int, int, int, int]) -> FaceAntiSpoofPrediction | None:
    primary = _PRIMARY_MODEL.predict(frame_bgr, box)
    secondary = _SECONDARY_MODEL.predict(frame_bgr, box)
    if primary is None and secondary is None:
        return None
    return FaceAntiSpoofPrediction(
        primary_real_score=primary.real_score if primary else None,
        primary_fake_score=primary.fake_score if primary else None,
        primary_provider=primary.provider if primary else "unavailable",
        secondary_real_score=secondary.real_score if secondary else None,
        secondary_fake_score=secondary.fake_score if secondary else None,
        secondary_provider=secondary.provider if secondary else "unavailable",
    )
