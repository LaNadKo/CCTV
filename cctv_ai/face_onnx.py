from __future__ import annotations

import logging
import os
import threading
import urllib.request
import zipfile
from pathlib import Path

import cv2
import numpy as np

from cctv_ai.runtime_env import prepare_acceleration_env, select_onnx_execution_providers

prepare_acceleration_env()

import onnxruntime as ort

logger = logging.getLogger(__name__)

_BUFFALO_L_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
_FACE_TEMPLATE = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)

_model_lock = threading.RLock()
_detector = None
_recognizer = None
_device_name = "cpu"
_ort_env_ready = False


def normalize_vec(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm <= 1e-8:
        return arr
    return arr / norm


def preprocess_frame(frame_bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_eq = clahe.apply(l_channel)
    merged = cv2.merge((l_eq, a_channel, b_channel))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def build_detection_variants(frame_rgb: np.ndarray):
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


def _runtime_model_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "CCTV Runtime" / "models" / "insightface" / "buffalo_l"
    return Path(".models") / "insightface" / "buffalo_l"


def _candidate_model_dirs() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        candidates.append(path)

    runtime_dir = _runtime_model_dir()
    add(runtime_dir)
    if runtime_dir.parent.parent.parent.exists():
        pass

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        add(Path(local_appdata) / "CCTV Processor" / "models" / "insightface" / "buffalo_l")
        add(Path(local_appdata) / "CCTV Backend" / "models" / "insightface" / "buffalo_l")

    add(Path(".models") / "insightface" / "buffalo_l")

    return candidates


def _ensure_model_pack() -> Path:
    for candidate in _candidate_model_dirs():
        if (candidate / "det_10g.onnx").exists() and (candidate / "w600k_r50.onnx").exists():
            return candidate

    target_dir = _runtime_model_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    zip_path = target_dir.parent / "buffalo_l.zip"
    if not zip_path.exists():
        logger.info("Downloading InsightFace model pack to %s", zip_path)
        urllib.request.urlretrieve(_BUFFALO_L_URL, zip_path)

    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(target_dir)
    return target_dir


def _select_providers(prefer_gpu: bool = True) -> tuple[list[str], str]:
    providers, device_name, _provider = select_onnx_execution_providers(prefer_gpu=prefer_gpu)
    return providers, device_name


def _prepare_onnxruntime(prefer_gpu: bool = True) -> None:
    global _ort_env_ready
    if _ort_env_ready or not prefer_gpu:
        return
    prepare_acceleration_env()
    if hasattr(ort, "preload_dlls"):
        try:
            ort.preload_dlls()
        except Exception:
            logger.debug("onnxruntime.preload_dlls failed", exc_info=True)
    _ort_env_ready = True


def _create_session(model_path: Path, prefer_gpu: bool = True) -> tuple[ort.InferenceSession, str]:
    _prepare_onnxruntime(prefer_gpu=prefer_gpu)
    providers, requested_device = _select_providers(prefer_gpu=prefer_gpu)
    try:
        session = ort.InferenceSession(str(model_path), providers=providers)
        active = session.get_providers()
        if requested_device != "cpu" and providers[0] in active:
            return session, requested_device
        if requested_device != "cpu":
            logger.warning(
                "Face ONNX runtime fell back to CPU for %s; requested=%s active=%s",
                model_path.name,
                providers,
                active,
            )
        return session, "cpu"
    except Exception:
        if requested_device != "cpu":
            logger.warning("Failed to initialize accelerated face runtime for %s providers=%s", model_path.name, providers, exc_info=True)
        session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        return session, "cpu"


def _estimate_norm(landmark: np.ndarray, image_size: int = 112) -> np.ndarray:
    assert landmark.shape == (5, 2)
    ratio = float(image_size) / 112.0
    dst = _FACE_TEMPLATE * ratio
    matrix, _ = cv2.estimateAffinePartial2D(
        landmark.astype(np.float32),
        dst.astype(np.float32),
        method=cv2.LMEDS,
    )
    if matrix is None:
        raise ValueError("Failed to estimate face alignment transform")
    return matrix.astype(np.float32)


def norm_crop(img: np.ndarray, landmark: np.ndarray, image_size: int = 112) -> np.ndarray:
    matrix = _estimate_norm(landmark, image_size=image_size)
    return cv2.warpAffine(img, matrix, (image_size, image_size), borderValue=0.0)


def distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    preds = []
    for idx in range(0, distance.shape[1], 2):
        px = points[:, idx % 2] + distance[:, idx]
        py = points[:, idx % 2 + 1] + distance[:, idx + 1]
        preds.append(px)
        preds.append(py)
    return np.stack(preds, axis=-1)


class SCRFDDetector:
    def __init__(self, model_file: Path, prefer_gpu: bool = True):
        self.session, self.device_name = _create_session(model_file, prefer_gpu=prefer_gpu)
        self.center_cache: dict[tuple[int, int, int], np.ndarray] = {}
        self.nms_thresh = 0.4
        self.det_thresh = 0.5
        input_cfg = self.session.get_inputs()[0]
        input_shape = input_cfg.shape
        self.input_name = input_cfg.name
        self.output_names = [output.name for output in self.session.get_outputs()]
        self.input_size = None if isinstance(input_shape[2], str) else tuple(input_shape[2:4][::-1])
        self.batched = len(self.session.get_outputs()[0].shape) == 3
        self.use_kps = len(self.output_names) in (9, 15)
        if len(self.output_names) in (6, 9):
            self.fmc = 3
            self._feat_stride_fpn = [8, 16, 32]
            self._num_anchors = 2
        else:
            self.fmc = 5
            self._feat_stride_fpn = [8, 16, 32, 64, 128]
            self._num_anchors = 1
        self.input_mean = 127.5
        self.input_std = 128.0

    def forward(self, img: np.ndarray, threshold: float):
        scores_list = []
        bboxes_list = []
        kpss_list = []
        input_size = tuple(img.shape[0:2][::-1])
        blob = cv2.dnn.blobFromImage(
            img,
            1.0 / self.input_std,
            input_size,
            (self.input_mean, self.input_mean, self.input_mean),
            swapRB=True,
        )
        net_outs = self.session.run(self.output_names, {self.input_name: blob})

        input_height = blob.shape[2]
        input_width = blob.shape[3]
        for idx, stride in enumerate(self._feat_stride_fpn):
            if self.batched:
                scores = net_outs[idx][0]
                bbox_preds = net_outs[idx + self.fmc][0] * stride
                kps_preds = net_outs[idx + self.fmc * 2][0] * stride if self.use_kps else None
            else:
                scores = net_outs[idx]
                bbox_preds = net_outs[idx + self.fmc] * stride
                kps_preds = net_outs[idx + self.fmc * 2] * stride if self.use_kps else None

            height = input_height // stride
            width = input_width // stride
            key = (height, width, stride)
            anchor_centers = self.center_cache.get(key)
            if anchor_centers is None:
                anchor_centers = np.stack(np.mgrid[:height, :width][::-1], axis=-1).astype(np.float32)
                anchor_centers = (anchor_centers * stride).reshape((-1, 2))
                if self._num_anchors > 1:
                    anchor_centers = np.stack([anchor_centers] * self._num_anchors, axis=1).reshape((-1, 2))
                if len(self.center_cache) < 100:
                    self.center_cache[key] = anchor_centers

            pos_inds = np.where(scores >= threshold)[0]
            if pos_inds.size == 0:
                continue

            bboxes = distance2bbox(anchor_centers, bbox_preds)
            scores_list.append(scores[pos_inds])
            bboxes_list.append(bboxes[pos_inds])

            if self.use_kps and kps_preds is not None:
                kpss = distance2kps(anchor_centers, kps_preds).reshape((bbox_preds.shape[0], -1, 2))
                kpss_list.append(kpss[pos_inds])

        return scores_list, bboxes_list, kpss_list

    def detect(
        self,
        img: np.ndarray,
        input_size: tuple[int, int] | None = None,
        max_num: int = 0,
        metric: str = "default",
    ) -> tuple[np.ndarray, np.ndarray | None]:
        input_size = self.input_size if input_size is None else input_size
        if input_size is None:
            input_size = (640, 640)

        image_ratio = float(img.shape[0]) / max(float(img.shape[1]), 1.0)
        model_ratio = float(input_size[1]) / float(input_size[0])
        if image_ratio > model_ratio:
            new_height = input_size[1]
            new_width = int(new_height / image_ratio)
        else:
            new_width = input_size[0]
            new_height = int(new_width * image_ratio)
        det_scale = float(new_height) / max(float(img.shape[0]), 1.0)
        resized_img = cv2.resize(img, (new_width, new_height))
        det_img = np.zeros((input_size[1], input_size[0], 3), dtype=np.uint8)
        det_img[:new_height, :new_width, :] = resized_img

        scores_list, bboxes_list, kpss_list = self.forward(det_img, self.det_thresh)
        if not scores_list or not bboxes_list:
            return np.zeros((0, 5), dtype=np.float32), None

        scores = np.vstack(scores_list)
        scores_ravel = scores.ravel()
        order = scores_ravel.argsort()[::-1]
        bboxes = np.vstack(bboxes_list) / det_scale
        pre_det = np.hstack((bboxes, scores)).astype(np.float32, copy=False)
        pre_det = pre_det[order, :]
        keep = self.nms(pre_det)
        det = pre_det[keep, :]

        kpss = None
        if self.use_kps and kpss_list:
            kpss = np.vstack(kpss_list) / det_scale
            kpss = kpss[order, :, :]
            kpss = kpss[keep, :, :]

        if max_num > 0 and det.shape[0] > max_num:
            area = (det[:, 2] - det[:, 0]) * (det[:, 3] - det[:, 1])
            image_center = img.shape[0] // 2, img.shape[1] // 2
            offsets = np.vstack(
                [
                    (det[:, 0] + det[:, 2]) / 2 - image_center[1],
                    (det[:, 1] + det[:, 3]) / 2 - image_center[0],
                ]
            )
            offset_dist_squared = np.sum(np.power(offsets, 2.0), axis=0)
            values = area if metric == "max" else area - offset_dist_squared * 2.0
            keep_idx = np.argsort(values)[::-1][:max_num]
            det = det[keep_idx, :]
            if kpss is not None:
                kpss = kpss[keep_idx, :]
        return det, kpss

    def nms(self, dets: np.ndarray) -> list[int]:
        if dets.size == 0:
            return []
        x1 = dets[:, 0]
        y1 = dets[:, 1]
        x2 = dets[:, 2]
        y2 = dets[:, 3]
        scores = dets[:, 4]
        areas = (x2 - x1 + 1) * (y2 - y1 + 1)
        order = scores.argsort()[::-1]
        keep: list[int] = []
        while order.size > 0:
            idx = int(order[0])
            keep.append(idx)
            xx1 = np.maximum(x1[idx], x1[order[1:]])
            yy1 = np.maximum(y1[idx], y1[order[1:]])
            xx2 = np.minimum(x2[idx], x2[order[1:]])
            yy2 = np.minimum(y2[idx], y2[order[1:]])
            w = np.maximum(0.0, xx2 - xx1 + 1)
            h = np.maximum(0.0, yy2 - yy1 + 1)
            inter = w * h
            ovr = inter / (areas[idx] + areas[order[1:]] - inter)
            inds = np.where(ovr <= self.nms_thresh)[0]
            order = order[inds + 1]
        return keep


class ArcFaceRecognizer:
    def __init__(self, model_file: Path, prefer_gpu: bool = True):
        self.session, self.device_name = _create_session(model_file, prefer_gpu=prefer_gpu)
        input_cfg = self.session.get_inputs()[0]
        input_shape = input_cfg.shape
        self.input_name = input_cfg.name
        self.output_names = [output.name for output in self.session.get_outputs()]
        self.input_size = tuple(input_shape[2:4][::-1])
        self.input_mean = 127.5
        self.input_std = 127.5

    def get_feat(self, imgs: np.ndarray | list[np.ndarray]) -> np.ndarray:
        if not isinstance(imgs, list):
            imgs = [imgs]
        blob = cv2.dnn.blobFromImages(
            imgs,
            1.0 / self.input_std,
            self.input_size,
            (self.input_mean, self.input_mean, self.input_mean),
            swapRB=True,
        )
        output = self.session.run(self.output_names, {self.input_name: blob})[0]
        return output

    def get(self, img: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        aligned = norm_crop(img, landmark=landmarks, image_size=self.input_size[0])
        feat = self.get_feat(aligned).flatten()
        return normalize_vec(feat.astype(np.float32))


def _ensure_runtime(prefer_gpu: bool = True) -> tuple[SCRFDDetector, ArcFaceRecognizer, str]:
    global _detector, _recognizer, _device_name
    if _detector is None or _recognizer is None:
        model_dir = _ensure_model_pack()
        _detector = SCRFDDetector(model_dir / "det_10g.onnx", prefer_gpu=prefer_gpu)
        _recognizer = ArcFaceRecognizer(model_dir / "w600k_r50.onnx", prefer_gpu=prefer_gpu)
        _device_name = _detector.device_name if _detector.device_name == _recognizer.device_name else "cpu"
        logger.info("Loaded face runtime on device=%s from %s", _device_name, model_dir)
    return _detector, _recognizer, _device_name


def prewarm_models(prefer_gpu: bool = True) -> str:
    with _model_lock:
        _, _, device_name = _ensure_runtime(prefer_gpu=prefer_gpu)
        return device_name


def get_inference_device() -> str:
    if _detector is not None:
        return _device_name
    _providers, device_name, _provider = select_onnx_execution_providers(prefer_gpu=True)
    return device_name


def detect_faces_rgb(
    frame_rgb: np.ndarray,
    *,
    prob_min: float = 0.58,
    min_face_ratio: float = 0.05,
    det_size: tuple[int, int] = (640, 640),
    build_variants: bool = True,
    max_num: int = 0,
) -> list[dict]:
    with _model_lock:
        detector, recognizer, _ = _ensure_runtime(prefer_gpu=True)

        detections = np.zeros((0, 5), dtype=np.float32)
        landmarks = None
        used_frame = frame_rgb

        variants = build_detection_variants(frame_rgb) if build_variants else [frame_rgb]
        height, width = frame_rgb.shape[:2]
        min_face_side = max(height, width) * min_face_ratio

        for variant in variants:
            det, kpss = detector.detect(variant, input_size=det_size, max_num=max_num)
            if det.size == 0:
                continue
            filtered_indices = []
            for idx, item in enumerate(det):
                score = float(item[4])
                x1, y1, x2, y2 = [float(v) for v in item[:4]]
                if score < prob_min:
                    continue
                if (x2 - x1) < min_face_side or (y2 - y1) < min_face_side:
                    continue
                filtered_indices.append(idx)
            if not filtered_indices:
                continue
            detections = det[filtered_indices]
            landmarks = kpss[filtered_indices] if kpss is not None else None
            used_frame = variant
            break

        if detections.size == 0:
            return []

        results: list[dict] = []
        for idx, det in enumerate(detections):
            if landmarks is None or idx >= len(landmarks):
                continue
            box = det[:4].astype(np.float32)
            score = float(det[4])
            lmk = landmarks[idx].astype(np.float32)
            embedding = recognizer.get(used_frame, lmk)
            results.append(
                {
                    "box": box.tolist(),
                    "confidence": score,
                    "embedding": embedding,
                    "landmarks": lmk.tolist(),
                }
            )
        return results


def extract_best_face_embedding_bgr(
    image_bgr: np.ndarray,
    *,
    prob_min: float = 0.58,
    min_face_ratio: float = 0.05,
) -> np.ndarray | None:
    prepared = preprocess_frame(image_bgr)
    rgb = cv2.cvtColor(prepared, cv2.COLOR_BGR2RGB)
    faces = detect_faces_rgb(
        rgb,
        prob_min=prob_min,
        min_face_ratio=min_face_ratio,
        build_variants=True,
        max_num=3,
    )
    if not faces:
        return None
    best = max(
        faces,
        key=lambda item: max(float(item["box"][2]) - float(item["box"][0]), 1.0)
        * max(float(item["box"][3]) - float(item["box"][1]), 1.0),
    )
    return np.asarray(best["embedding"], dtype=np.float32)
