"""Camera worker: frame reading, motion detection, face scanning, media serving and recording."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import queue
import shutil
import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from cctv_ai.opencv_capture import open_video_capture
from PIL import Image, ImageDraw, ImageFont
from scipy.optimize import linear_sum_assignment

from processor.camera_utils import redact_source, source_candidates
from processor.config import settings
from processor.inference_scheduler import gpu_inference_gate
from processor.latest_queue import drain, put_latest
from processor.paths import RECORDINGS_DIR, SNAPSHOTS_DIR, ensure_media_dirs
from processor.performance import PerformanceMetrics

logger = logging.getLogger(__name__)
_PROCESSING_BASE_FPS = 24.0
_MAX_FRAME_INTERVAL_SECONDS = 5.0
_FRAME_DIVISOR_CHOICES = (1, 2, 4, 8, 16, 32, 64, 120)
_MIN_FACE_SCAN_DIVISOR = 2

_POSE_SKELETON_EDGES = (
    (5, 6),
    (5, 7),
    (7, 9),
    (6, 8),
    (8, 10),
    (5, 11),
    (6, 12),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (0, 1),
    (0, 2),
    (1, 3),
    (2, 4),
    (0, 5),
    (0, 6),
)


def _resize_capture_frame(frame: np.ndarray, max_pixels: int) -> np.ndarray:
    height, width = frame.shape[:2]
    pixel_count = max(1, int(height) * int(width))
    if pixel_count <= max_pixels:
        return frame
    scale = (max_pixels / float(pixel_count)) ** 0.5
    target_width = max(1, int(width * scale))
    target_height = max(1, int(height * scale))
    return cv2.resize(
        frame,
        (target_width, target_height),
        interpolation=cv2.INTER_AREA,
    )


def _recording_has_free_space(root: Path, min_free_bytes: int) -> bool:
    try:
        return shutil.disk_usage(root).free >= max(0, int(min_free_bytes))
    except OSError:
        return False


@lru_cache(maxsize=8)
def _load_overlay_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        try:
            if candidate.exists():
                return ImageFont.truetype(str(candidate), size=size)
        except Exception:
            continue
    return ImageFont.load_default()


class CameraWorker:
    def __init__(self, assignment: dict, client, source: str | int):
        self.assignment = assignment
        self.camera_id = assignment["camera_id"]
        self.client = client
        self.source = source
        self.processor_id: int | None = None
        self._running = False
        self._gallery: list[dict] = []
        self._prev_gray: np.ndarray | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None

        raw_scan_divisor = getattr(settings, "face_scan_divisor", None)
        if raw_scan_divisor in (None, 0):
            try:
                raw_scan_divisor = max(1, int(round(float(settings.face_scan_interval) * _PROCESSING_BASE_FPS)))
            except Exception:
                raw_scan_divisor = 4
        self._face_scan_divisor = self._sanitize_face_scan_divisor(raw_scan_divisor, fallback=4)
        self._overlay_frame_divisor = self._sanitize_frame_divisor(
            getattr(settings, "overlay_frame_divisor", 1),
            fallback=1,
        )
        self._target_scan_interval = self._frame_divisor_to_interval(self._face_scan_divisor)
        self._last_event: dict[object, float] = {}
        self._event_dedup_seconds = 10.0
        self._unknown_event_dedup_seconds = 5.0
        self._unknown_event_cache: list[tuple[np.ndarray, float]] = []
        self._face_overlay_ttl = max(2.5, min(self._target_scan_interval * 8.0, 3.5))
        self._body_overlay_ttl = max(2.5, min(self._target_scan_interval * 8.0, 3.5))
        self._face_flow_ttl = max(self._face_overlay_ttl, min(self._target_scan_interval * 12.0, 4.5))
        self._body_flow_ttl = max(self._body_overlay_ttl, min(self._target_scan_interval * 12.0, 4.5))
        self._track_visible_ttl = 0.3
        self._track_reacquire_ttl = 1.5
        self._record_event_tail_seconds = 10.0
        self._live_publish_interval = self._frame_divisor_to_interval(self._overlay_frame_divisor)
        self._last_publish_ts = 0.0
        self._publish_frame_counter = 0
        self._last_overlay_refresh_mark = 0
        self._overlay_render_interval = max(self._live_publish_interval, 1.0 / _PROCESSING_BASE_FPS)
        self._last_overlay_render_ts = 0.0
        self._overlay_queue: queue.Queue[tuple[np.ndarray, int] | None] = queue.Queue(maxsize=1)
        self._overlay_stop = threading.Event()
        self._overlay_thread: threading.Thread | None = None
        self._publish_queue: queue.Queue[tuple[np.ndarray, int] | None] = queue.Queue(maxsize=1)
        self._publish_stop = threading.Event()
        self._publish_thread: threading.Thread | None = None
        self._face_queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=1)
        self._face_stop = threading.Event()
        self._face_thread: threading.Thread | None = None
        self._body_queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=1)
        self._body_stop = threading.Event()
        self._body_thread: threading.Thread | None = None
        self._event_queue: queue.Queue[
            tuple[
                dict,
                np.ndarray | None,
                tuple[int, int, int, int] | None,
            ]
            | None
        ] = queue.Queue(maxsize=32)
        self._event_stop = threading.Event()
        self._event_thread: threading.Thread | None = None

        self._last_faces_info: list[tuple[tuple[int, int, int, int], str, bool]] = []
        self._last_faces_ts = 0.0
        self._last_faces_flow_ts = 0.0
        self._last_live_embeddings: list[dict[str, object]] = []
        self._last_live_embeddings_ts = 0.0
        self._last_body_info: list[dict[str, object]] = []
        self._last_body_ts = 0.0
        self._last_body_flow_ts = 0.0
        self._last_activity_ts = 0.0
        self._last_motion_ts = 0.0
        self._last_motion_scan_monotonic = 0.0
        self._last_motion_result = False
        self._motion_scan_interval = 0.18
        self._motion_max_side = 256
        self._liveness_state: dict[str, dict[str, object]] = {}
        self._next_liveness_state_id = 1
        self._liveness_live_hold_seconds = 3.5
        self._liveness_disagreement_suppress_hits = 4
        self._identity_state: dict[str, dict[str, object]] = {}
        self._body_tracks: dict[int, dict[str, object]] = {}
        self._next_body_track_id = 1
        self._recognized_track_hold_seconds = 4.5
        self._spoof_face_boxes: list[tuple[tuple[int, int, int, int], float]] = []
        self._blocked_face_boxes: list[tuple[tuple[int, int, int, int], float]] = []
        self._spoof_face_ttl = 12.0
        self._last_spoof_log_ts = 0.0
        self._body_support_cache: list[dict] | None = None
        self._body_support_ts = 0.0
        self._body_support_interval = max(0.08, min(0.25, self._target_scan_interval))
        self._body_max_side = 800

        self._capture_lock = threading.Lock()
        self._capture_ready = threading.Event()
        self._capture_frame: np.ndarray | None = None
        self._capture_seq = 0
        self._capture_thread: threading.Thread | None = None
        self._capture_handle_lock = threading.Lock()
        self._capture_handle: cv2.VideoCapture | None = None
        self._last_capture_monotonic = 0.0
        self._max_capture_pixels = int(getattr(settings, "max_capture_pixels", 8_294_400))
        self._capture_resize_logged = False
        self._analysis_lock = threading.RLock()
        self._flow_max_side = 960
        self._face_flow_reference: tuple[np.ndarray, float, float] | None = None
        self._body_flow_reference: tuple[np.ndarray, float, float] | None = None
        self._body_scan_interval = max(0.12, self._target_scan_interval)
        self._scan_max_side = 1536
        self._full_face_scan_interval = 1.5
        self._last_full_face_scan_monotonic = 0.0
        self._antispoof_inference_interval = 0.45

        self._frame_lock = threading.Lock()
        self._frame_ready = threading.Condition(self._frame_lock)
        self._latest_raw_jpeg: bytes | None = None
        self._latest_overlay_jpeg: bytes | None = None
        self._stream_frame_sequence = 0
        self._raw_frame_sequence = 0
        self._overlay_frame_sequence = 0

        self._writer: cv2.VideoWriter | None = None
        self._writer_path: Path | None = None
        self._writer_relative_path: str | None = None
        self._writer_started_monotonic = 0.0
        self._writer_started_dt: datetime | None = None
        self._writer_frame_size: tuple[int, int] | None = None
        self._record_queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=2)
        self._record_stop = threading.Event()
        self._record_thread: threading.Thread | None = None
        self._record_target_fps = 15.0
        self._record_enqueue_interval = 1.0 / self._record_target_fps
        self._last_record_enqueue_monotonic = 0.0
        self._recording_upload_concurrency = max(
            1,
            min(8, int(getattr(settings, "recording_upload_concurrency", 2))),
        )
        self._recording_upload_pending: queue.Queue[tuple[dict, Path | None]] = queue.Queue(
            maxsize=max(8, min(512, int(getattr(settings, "recording_upload_queue_size", 128)))),
        )
        self._recording_upload_lock = threading.RLock()
        self._recording_upload_inflight = 0
        self._recording_cleanup_last_monotonic = 0.0
        self._recording_cleanup_interval = 300.0
        self._last_low_disk_log_monotonic = 0.0
        self._metrics = PerformanceMetrics(f"camera={self.camera_id}", logger=logger)

        self._tracking_controller = None
        self._auto_tracker = None
        self._patrol_mode = None
        self._tracking_last_target_monotonic = 0.0
        self._tracking_idle_seconds = 1.2

        ensure_media_dirs()
        self._setup_tracking_runtime()

    def _similarity_to_confidence(self, sim: float | None, recognized: bool) -> float | None:
        if sim is None:
            return None
        sim = max(0.0, min(float(sim), 1.0))
        threshold = max(0.01, min(float(settings.face_match_threshold), 0.99))
        if recognized:
            value = 60.0 + ((sim - threshold) / max(1.0 - threshold, 1e-6)) * 40.0
        else:
            value = min(59.0, (sim / threshold) * 59.0)
        return round(max(0.0, min(100.0, value)), 2)

    def _sanitize_frame_divisor(self, value: object, fallback: int) -> int:
        try:
            raw = int(value)
        except (TypeError, ValueError):
            raw = fallback
        if raw <= 0:
            raw = fallback
        for candidate in _FRAME_DIVISOR_CHOICES:
            if raw <= candidate:
                return candidate
        return _FRAME_DIVISOR_CHOICES[-1]

    def _sanitize_face_scan_divisor(self, value: object, fallback: int) -> int:
        return max(_MIN_FACE_SCAN_DIVISOR, self._sanitize_frame_divisor(value, fallback))

    def _frame_divisor_to_interval(self, divisor: int) -> float:
        return min(_MAX_FRAME_INTERVAL_SECONDS, divisor / _PROCESSING_BASE_FPS)

    async def set_gallery(self, gallery: list[dict]):
        self._gallery = gallery

    async def update_assignment(self, assignment: dict) -> None:
        self.assignment = assignment
        self._setup_tracking_runtime()

    def _setup_tracking_runtime(self) -> None:
        if self._auto_tracker:
            self._auto_tracker.stop(force=True)
        self._tracking_controller = None
        self._auto_tracker = None
        self._patrol_mode = None
        self._tracking_last_target_monotonic = 0.0

    def _select_tracking_target(self, body_tracks: list[dict], frame_shape: tuple[int, ...]) -> tuple[int, int, int, int] | None:
        frame_h, frame_w = frame_shape[:2]
        target_person_id = self.assignment.get("tracking_target_person_id")
        best_box: tuple[int, int, int, int] | None = None
        best_score = float("-inf")
        for state in body_tracks:
            box = state.get("tracking_box")
            if not isinstance(box, tuple):
                box = state.get("box")
            if not isinstance(box, tuple):
                continue
            hits = int(state.get("hits", 0))
            if hits < 2:
                continue
            person_id = state.get("person_id")
            recognized = bool(state.get("recognized"))
            if target_person_id is not None and person_id != target_person_id:
                continue
            pose_support = self._track_has_pose_support(state, strict=not recognized)
            if not recognized and not pose_support and target_person_id is None:
                continue
            x1, y1, x2, y2 = box
            box_w = max(x2 - x1, 1)
            box_h = max(y2 - y1, 1)
            area_ratio = min(0.45, (box_w * box_h) / max(frame_w * frame_h, 1))
            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2
            center_dx = abs(center_x - (frame_w / 2)) / max(frame_w / 2, 1)
            center_dy = abs(center_y - (frame_h / 2)) / max(frame_h / 2, 1)
            center_score = 1.0 - min(1.0, (center_dx * 0.65) + (center_dy * 0.35))
            freshness = max(0.0, 1.0 - ((time.time() - float(state.get("last_seen", 0.0))) / 2.5))
            score = (hits * 0.8) + (center_score * 4.5) + (area_ratio * 5.0) + (freshness * 2.0)
            if pose_support:
                score += 1.2
            if recognized:
                score += 2.5
            if target_person_id is not None and person_id == target_person_id:
                score += 100.0
            if score > best_score:
                best_score = score
                best_box = tuple(int(v) for v in box)
        return best_box

    def _apply_tracking(self, body_tracks: list[dict], frame_shape: tuple[int, ...]) -> None:
        if not self._auto_tracker:
            return
        now = time.monotonic()
        target_box = self._select_tracking_target(body_tracks, frame_shape)
        tracking_mode = str(self.assignment.get("tracking_mode") or "off")
        if target_box is not None:
            self._tracking_last_target_monotonic = now
            if self._patrol_mode:
                self._patrol_mode.interrupt()
            self._auto_tracker.track(target_box, frame_shape[1], frame_shape[0])
            return

        if self._patrol_mode and tracking_mode == "patrol":
            self._patrol_mode.resume()
            if (now - self._tracking_last_target_monotonic) >= self._tracking_idle_seconds:
                self._auto_tracker.stop(force=True)
            self._patrol_mode.step(now)
            return

        self._auto_tracker.stop(force=(now - self._tracking_last_target_monotonic) >= self._tracking_idle_seconds)

    async def start(self, processor_id: int):
        self.processor_id = processor_id
        self._running = True
        self._event_loop = asyncio.get_event_loop()
        await asyncio.to_thread(self._run_loop)

    def stop(self):
        self._running = False
        with self._capture_handle_lock:
            capture = self._capture_handle
        if capture is not None:
            capture.release()
        if self._auto_tracker:
            self._auto_tracker.stop(force=True)

    def get_stream_frame(self, overlay: bool = True) -> bytes | None:
        with self._frame_lock:
            if overlay and self._latest_overlay_jpeg:
                return self._latest_overlay_jpeg
            return self._latest_raw_jpeg

    def wait_for_stream_frame(
        self,
        *,
        overlay: bool,
        after_sequence: int,
        timeout: float = 0.5,
    ) -> tuple[int, bytes | None]:
        def current() -> tuple[int, bytes | None]:
            if overlay and self._latest_overlay_jpeg is not None:
                return self._overlay_frame_sequence, self._latest_overlay_jpeg
            return self._raw_frame_sequence, self._latest_raw_jpeg

        with self._frame_ready:
            sequence, frame = current()
            if sequence <= after_sequence:
                self._frame_ready.wait_for(
                    lambda: current()[0] > after_sequence,
                    timeout=max(0.0, timeout),
                )
                sequence, frame = current()
            return sequence, frame

    def get_live_embedding(self, max_age: float = 2.0) -> dict[str, object] | None:
        with self._analysis_lock:
            now = time.time()
            if (
                not self._last_live_embeddings
                or now - self._last_live_embeddings_ts > max(max_age, self._face_overlay_ttl)
            ):
                return None
            best = max(
                self._last_live_embeddings,
                key=lambda item: max(
                    0.0,
                    float(item["box"][2]) - float(item["box"][0]),
                )
                * max(0.0, float(item["box"][3]) - float(item["box"][1])),
            )
            embedding = np.asarray(best.get("embedding"), dtype=np.float32)
            if embedding.size == 0:
                return None
            return {
                "embedding": embedding.copy(),
                "box": tuple(best["box"]),
                "person_id": best.get("person_id"),
                "similarity": best.get("similarity"),
                "recognized": bool(best.get("recognized")),
                "label": best.get("label"),
                "age_seconds": max(0.0, now - self._last_live_embeddings_ts),
            }

    def bottleneck_text(self) -> str:
        return self._metrics.bottleneck_text()

    def _run_loop(self):
        cap = self._open_capture()
        if not cap.isOpened():
            logger.error("Cannot open camera %s source=%s", self.camera_id, redact_source(self.source))
            return
        with self._capture_handle_lock:
            self._capture_handle = cap
        last_face_scan = 0.0
        last_body_scan = 0.0
        last_processed_seq = 0
        self._capture_ready.clear()
        self._capture_thread = threading.Thread(target=self._capture_loop, args=(cap,), daemon=True)
        self._capture_thread.start()
        self._start_analysis_threads()
        self._start_event_thread()
        self._start_publish_thread()
        self._start_overlay_thread()
        self._start_recording_thread()
        try:
            while self._running:
                last_processed_seq, frame = self._get_latest_frame(last_processed_seq)
                if frame is None:
                    time.sleep(0.01)
                    continue

                motion = self._detect_motion(frame)
                now = time.monotonic()
                if motion:
                    self._last_motion_ts = time.time()
                    self._last_activity_ts = time.time()

                scan_interval = self._target_scan_interval
                should_publish = (now - self._last_publish_ts) >= self._live_publish_interval
                publish_mark = self._next_publish_frame_mark() if should_publish else 0

                if self.assignment.get("detection_enabled", True) and (
                    (now - last_face_scan) >= scan_interval
                ):
                    last_face_scan = now
                    put_latest(self._face_queue, frame)

                if self.assignment.get("detection_enabled", True) and (
                    (now - last_body_scan) >= self._body_scan_interval
                ):
                    last_body_scan = now
                    put_latest(self._body_queue, frame)

                if should_publish:
                    self._publish_live_frames(frame, publish_mark=publish_mark)
                    self._last_publish_ts = now
                self._record_frame(frame, motion)
        finally:
            self._running = False
            if self._capture_thread and self._capture_thread.is_alive():
                self._capture_thread.join(timeout=2)
            self._capture_thread = None
            self._capture_ready.clear()
            with self._capture_lock:
                self._capture_frame = None
                self._capture_seq = 0
            self._stop_analysis_threads()
            self._stop_event_thread()
            self._stop_recording_thread()
            self._stop_publish_thread()
            self._stop_overlay_thread()
            try:
                from processor.body_detector import release_camera_state

                release_camera_state(self.camera_id)
            except Exception:
                logger.exception("Failed to release body tracker state for camera %s", self.camera_id)
            self._metrics.log_summary()
            cap.release()
            with self._capture_handle_lock:
                if self._capture_handle is cap:
                    self._capture_handle = None

    def _capture_loop(self, cap: cv2.VideoCapture) -> None:
        while self._running:
            started = time.perf_counter()
            ok = cap.grab()
            if not ok:
                time.sleep(0.05)
                continue
            ok, frame = cap.retrieve()
            self._metrics.observe("capture", time.perf_counter() - started)
            if not ok or frame is None:
                time.sleep(0.01)
                continue
            original_height, original_width = frame.shape[:2]
            frame = _resize_capture_frame(frame, self._max_capture_pixels)
            if not self._capture_resize_logged and frame.shape[:2] != (original_height, original_width):
                logger.warning(
                    "Camera %s: capture frame %sx%s downscaled to %sx%s by MAX_CAPTURE_PIXELS",
                    self.camera_id,
                    original_width,
                    original_height,
                    frame.shape[1],
                    frame.shape[0],
                )
                self._capture_resize_logged = True
            now = time.monotonic()
            if self._last_capture_monotonic:
                interval = now - self._last_capture_monotonic
                self._metrics.observe("capture_interval", interval)
                if interval > 0.25:
                    logger.warning(
                        "Camera %s: capture pause %.0f ms",
                        self.camera_id,
                        interval * 1000.0,
                    )
            self._last_capture_monotonic = now
            with self._capture_lock:
                self._capture_frame = frame
                self._capture_seq += 1
            self._capture_ready.set()

    def _get_latest_frame(self, last_processed_seq: int) -> tuple[int, np.ndarray | None]:
        if not self._capture_ready.wait(timeout=2):
            return last_processed_seq, None
        with self._capture_lock:
            if self._capture_frame is None or self._capture_seq == last_processed_seq:
                return last_processed_seq, None
            return self._capture_seq, self._capture_frame.copy()

    def _next_publish_frame_mark(self) -> int:
        self._publish_frame_counter += 1
        if self._publish_frame_counter > 999:
            self._publish_frame_counter = 1
        return self._publish_frame_counter

    def _open_single_capture(self, source: str | int) -> cv2.VideoCapture:
        return open_video_capture(
            source,
            open_timeout_ms=5000,
            read_timeout_ms=5000,
            buffer_size=1,
        )

    def _open_capture(self) -> cv2.VideoCapture:
        candidates = source_candidates(self.assignment) or [self.source]
        last_cap: cv2.VideoCapture | None = None
        for index, source in enumerate(candidates):
            cap = self._open_single_capture(source)
            if cap.isOpened():
                if index > 0:
                    logger.warning(
                        "Camera %s: using fallback source %s after primary failed",
                        self.camera_id,
                        redact_source(source),
                    )
                self.source = source
                return cap
            cap.release()
            last_cap = cap
            logger.warning(
                "Camera %s: cannot open source candidate %s",
                self.camera_id,
                redact_source(source),
            )
        return last_cap or cv2.VideoCapture()

    def _detect_motion(self, frame: np.ndarray) -> bool:
        now = time.monotonic()
        if now - self._last_motion_scan_monotonic < self._motion_scan_interval:
            return self._last_motion_result

        with self._metrics.measure("motion"):
            height, width = frame.shape[:2]
            max_side = max(height, width)
            scale = 1.0
            motion_frame = frame
            if max_side > self._motion_max_side:
                scale = self._motion_max_side / float(max_side)
                motion_frame = cv2.resize(
                    frame,
                    (
                        max(1, int(round(width * scale))),
                        max(1, int(round(height * scale))),
                    ),
                    interpolation=cv2.INTER_AREA,
                )
            gray = cv2.cvtColor(motion_frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (11, 11), 0)
            motion = False
            if self._prev_gray is not None and self._prev_gray.shape == gray.shape:
                delta = cv2.absdiff(self._prev_gray, gray)
                threshold = cv2.threshold(
                    delta,
                    settings.motion_threshold,
                    255,
                    cv2.THRESH_BINARY,
                )[1]
                threshold = cv2.dilate(threshold, None, iterations=1)
                contours, _ = cv2.findContours(
                    threshold,
                    cv2.RETR_EXTERNAL,
                    cv2.CHAIN_APPROX_SIMPLE,
                )
                scaled_min_area = max(12.0, float(settings.motion_min_area) * scale * scale)
                motion = any(
                    cv2.contourArea(contour) >= scaled_min_area for contour in contours
                )
            self._prev_gray = gray
            self._last_motion_scan_monotonic = now
            self._last_motion_result = motion
            return motion

    def _scan_faces(self, frame: np.ndarray):
        try:
            from processor.vision import detect_faces, match_embedding

            scan_started = time.monotonic()
            full_scan = (
                scan_started - self._last_full_face_scan_monotonic
                >= self._full_face_scan_interval
            )
            with self._metrics.measure("face_inference"):
                with gpu_inference_gate.live():
                    if full_scan:
                        scan_frame, scale_x, scale_y = self._prepare_scan_frame(frame)
                        faces = detect_faces(
                            cv2.cvtColor(scan_frame, cv2.COLOR_BGR2RGB),
                            build_variants=True,
                            det_size=(1280, 1280),
                        )
                        faces = [
                            {
                                **face,
                                "box": self._rescale_box(
                                    face["box"],
                                    frame.shape[1],
                                    frame.shape[0],
                                    scale_x,
                                    scale_y,
                                ),
                            }
                            for face in faces
                        ]
                        self._last_full_face_scan_monotonic = scan_started
                    else:
                        faces = self._scan_face_rois(frame, detect_faces)
            now = time.time()
            overlay_items: list[tuple[tuple[int, int, int, int], str, bool]] = []
            live_embedding_items: list[dict[str, object]] = []
            with self._analysis_lock:
                bodies = [dict(body) for body in (self._body_support_cache or [])]
                body_tracks = [dict(state) for state in self._body_tracks.values()]

                for face in faces:
                    box = self._clip_box(
                        tuple(float(value) for value in face["box"]),
                        frame.shape[1],
                        frame.shape[0],
                    )
                    track_id = self._find_body_track_for_face(box, body_tracks)
                    person_id, sim = match_embedding(face["embedding"], self._gallery)
                    if person_id is None:
                        if track_id is not None:
                            person_id = self._recover_track_identity(track_id, sim, now, box)
                    if person_id is None:
                        person_id = self._recover_recent_identity(box, sim, now)
                    recognized = person_id is not None
                    label = self._label_for_person(person_id) if recognized else "Неизвестно"
                    liveness = self._evaluate_face_liveness(
                        frame,
                        box,
                        bodies,
                        now,
                        track_id=track_id,
                        recognized=recognized,
                    )
                    if not bool(liveness.get("candidate")):
                        self._remember_blocked_face(box, now)
                        self._drop_spoofed_face_overlay(box, now)
                        self._drop_spoofed_body_overlay(box, now)
                        if bool(liveness.get("spoof")):
                            overlay_items.append((box, "Подмена", False))
                        logger.debug("Camera %s: suppressed non-live/spoof-like face %s", self.camera_id, box)
                        continue
                    if not bool(liveness.get("confirmed")):
                        logger.debug(
                            "Camera %s: live candidate is still pending box=%s stable_hits=%s",
                            self.camera_id,
                            box,
                            liveness.get("stable_hits"),
                        )
                        self._remember_blocked_face(box, now)
                        overlay_items.append((box, "Проверка", False))
                        continue
                    self._forget_blocked_face(box, now)
                    if track_id is not None:
                        self._remember_track_liveness(track_id, now, box)
                    embedding = np.asarray(face.get("embedding"), dtype=np.float32)
                    if embedding.size:
                        live_embedding_items.append(
                            {
                                "embedding": embedding.copy(),
                                "box": box,
                                "person_id": person_id,
                                "similarity": sim,
                                "recognized": recognized,
                                "label": label,
                            }
                        )
                    if recognized:
                        overlay_items.append((box, label, recognized))
                        self._remember_identity(box, person_id, sim, now)
                        if track_id is not None:
                            self._remember_track_identity(track_id, person_id, label, now, box, sim)
                    if not recognized:
                        recent_motion = (time.time() - self._last_motion_ts) <= settings.unknown_face_requires_motion_seconds
                        if not recent_motion and track_id is not None:
                            track_state = self._body_tracks.get(track_id)
                            recent_motion = bool(
                                track_state
                                and int(track_state.get("hits", 0)) >= 2
                                and self._track_has_pose_support(track_state, strict=False)
                            )
                        if not recent_motion and bodies and self._face_supported_by_pose(box, bodies, strict=False):
                            recent_motion = True
                        if not recent_motion:
                            logger.debug(
                                "Camera %s: suppressed unknown face without recent scene motion box=%s",
                                self.camera_id,
                                box,
                            )
                            continue
                        overlay_items.append((box, label, recognized))
                        if self._should_skip_unknown_embedding(face["embedding"]):
                            continue
                    event_type = "face_recognized" if recognized else "face_unknown"

                    if recognized:
                        dedup_key = ("person", person_id)
                        dedup_window = self._event_dedup_seconds
                    else:
                        dedup_key = ("unknown-track", track_id) if track_id is not None else ("unknown-face", self._face_key(box))
                        dedup_window = self._unknown_event_dedup_seconds
                    last_ts = self._last_event.get(dedup_key, 0)
                    if now - last_ts < dedup_window:
                        continue
                    self._last_event[dedup_key] = now
                    self._last_activity_ts = now

                    logger.info(
                        "Camera %s: %s person=%s sim=%.3f",
                        self.camera_id, event_type, person_id, sim,
                    )

                    payload = {
                        "event_type": event_type,
                        "camera_id": self.camera_id,
                        "person_id": person_id,
                        "confidence": self._similarity_to_confidence(sim, recognized),
                        "snapshot_b64": None,
                        "event_ts": datetime.now().isoformat(),
                    }
                    self._queue_event(
                        payload,
                        frame=frame if not recognized else None,
                        box=box if not recognized else None,
                    )

                if overlay_items:
                    self._last_faces_info = overlay_items
                    self._last_faces_ts = now
                    self._last_faces_flow_ts = now
                    self._face_flow_reference = self._make_flow_reference(frame)
                elif now - self._last_faces_ts > self._face_overlay_ttl:
                    self._last_faces_info = []
                    self._last_faces_flow_ts = 0.0
                    self._face_flow_reference = None
                if live_embedding_items:
                    self._last_live_embeddings = live_embedding_items
                    self._last_live_embeddings_ts = now
                elif now - self._last_live_embeddings_ts > self._face_overlay_ttl:
                    self._last_live_embeddings = []
                    self._last_live_embeddings_ts = 0.0
        except Exception:
            logger.exception("Face scan error on camera %s", self.camera_id)

    def _start_analysis_threads(self) -> None:
        self._face_stop.clear()
        self._body_stop.clear()
        drain(self._face_queue)
        drain(self._body_queue)
        self._face_thread = threading.Thread(
            target=self._face_loop,
            name=f"camera-{self.camera_id}-face",
            daemon=True,
        )
        self._body_thread = threading.Thread(
            target=self._body_loop,
            name=f"camera-{self.camera_id}-body",
            daemon=True,
        )
        self._face_thread.start()
        self._body_thread.start()

    def _stop_analysis_threads(self) -> None:
        self._face_stop.set()
        self._body_stop.set()
        put_latest(self._face_queue, None)
        put_latest(self._body_queue, None)
        for thread, name in (
            (self._face_thread, "face"),
            (self._body_thread, "body"),
        ):
            if thread and thread.is_alive():
                thread.join(timeout=3)
                if thread.is_alive():
                    logger.warning(
                        "Camera %s: %s analysis thread did not stop in time",
                        self.camera_id,
                        name,
                    )
        self._face_thread = None
        self._body_thread = None

    def _face_loop(self) -> None:
        while not self._face_stop.is_set():
            try:
                frame = self._face_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if frame is None:
                    break
                with self._metrics.measure("face_pipeline"):
                    self._scan_faces(frame)
            finally:
                self._face_queue.task_done()

    def _body_loop(self) -> None:
        while not self._body_stop.is_set():
            try:
                frame = self._body_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if frame is None:
                    break
                with self._metrics.measure("body_pipeline"):
                    self._scan_bodies_guarded(frame)
            finally:
                self._body_queue.task_done()

    def _scan_bodies_guarded(self, frame: np.ndarray) -> None:
        try:
            now = time.time()
            bodies = self._get_body_support(frame, now)
            with self._analysis_lock:
                body_tracks = self._update_body_tracks(bodies, now)
                body_overlay_items = self._build_body_overlay_items(body_tracks, now)
                self._apply_tracking(body_tracks, frame.shape)
                if body_overlay_items:
                    self._last_body_info = body_overlay_items
                    self._last_body_ts = now
                    self._last_body_flow_ts = now
                    self._body_flow_reference = self._make_flow_reference(frame)
                elif now - self._last_body_ts > self._body_overlay_ttl:
                    self._last_body_info = []
                    self._last_body_flow_ts = 0.0
                    self._body_flow_reference = None
        except Exception:
            logger.exception("Body scan error on camera %s", self.camera_id)

    def _label_for_person(self, person_id: int | None) -> str:
        if person_id is None:
            return "Неизвестно"
        for entry in self._gallery:
            if entry.get("person_id") == person_id:
                return str(entry.get("label") or f"ID {person_id}")
        return f"ID {person_id}"

    def _prepare_scan_frame(self, frame: np.ndarray) -> tuple[np.ndarray, float, float]:
        height, width = frame.shape[:2]
        max_side = max(height, width)
        if max_side <= self._scan_max_side:
            return frame, 1.0, 1.0
        scale = self._scan_max_side / float(max_side)
        resized = cv2.resize(
            frame,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
        return resized, width / float(resized.shape[1]), height / float(resized.shape[0])

    def _scan_face_rois(self, frame: np.ndarray, detect_faces) -> list[dict]:
        height, width = frame.shape[:2]
        with self._analysis_lock:
            face_boxes = [box for box, _label, _recognized in self._last_faces_info]
            head_boxes = [
                state.get("head_box")
                for state in self._body_tracks.values()
                if isinstance(state.get("head_box"), tuple)
                and (time.time() - float(state.get("last_seen", 0.0)))
                <= self._track_reacquire_ttl
            ]

        rois: list[tuple[int, int, int, int]] = []
        for raw_box in [*face_boxes, *head_boxes]:
            if not isinstance(raw_box, tuple):
                continue
            x1, y1, x2, y2 = raw_box
            box_width = max(float(x2 - x1), 1.0)
            box_height = max(float(y2 - y1), 1.0)
            expanded = self._clip_box(
                (
                    x1 - box_width * 0.65,
                    y1 - box_height * 0.65,
                    x2 + box_width * 0.65,
                    y2 + box_height * 0.65,
                ),
                width,
                height,
            )
            if (expanded[2] - expanded[0]) < 48 or (expanded[3] - expanded[1]) < 48:
                continue
            if any(self._box_iou(expanded, existing) >= 0.65 for existing in rois):
                continue
            rois.append(expanded)

        if not rois:
            scan_frame, scale_x, scale_y = self._prepare_scan_frame(frame)
            faces = detect_faces(
                cv2.cvtColor(scan_frame, cv2.COLOR_BGR2RGB),
                build_variants=False,
                det_size=(1024, 1024),
            )
            return [
                {
                    **face,
                    "box": self._rescale_box(
                        face["box"],
                        width,
                        height,
                        scale_x,
                        scale_y,
                    ),
                }
                for face in faces
            ]

        results: list[dict] = []
        for x1, y1, x2, y2 in rois[:8]:
            roi = frame[y1:y2, x1:x2]
            if roi.size == 0:
                continue
            roi_faces = detect_faces(
                cv2.cvtColor(roi, cv2.COLOR_BGR2RGB),
                build_variants=False,
                det_size=(640, 640),
            )
            for face in roi_faces:
                bx1, by1, bx2, by2 = [float(value) for value in face["box"]]
                mapped_box = self._clip_box(
                    (bx1 + x1, by1 + y1, bx2 + x1, by2 + y1),
                    width,
                    height,
                )
                if any(
                    self._box_iou(mapped_box, tuple(item["box"])) >= 0.55
                    for item in results
                ):
                    continue
                results.append({**face, "box": mapped_box})
        return results

    def _rescale_box(
        self,
        box: tuple[float, float, float, float] | list[float],
        width: int,
        height: int,
        scale_x: float,
        scale_y: float,
    ) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = [float(v) for v in box]
        return (
            max(0, min(width - 1, int(round(x1 * scale_x)))),
            max(0, min(height - 1, int(round(y1 * scale_y)))),
            max(0, min(width, int(round(x2 * scale_x)))),
            max(0, min(height, int(round(y2 * scale_y)))),
        )

    def _clip_box(
        self,
        box: tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = box
        return (
            max(0, min(width - 1, int(round(x1)))),
            max(0, min(height - 1, int(round(y1)))),
            max(0, min(width, int(round(x2)))),
            max(0, min(height, int(round(y2)))),
        )

    def _union_boxes(
        self,
        box_a: tuple[int, int, int, int],
        box_b: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int]:
        return (
            min(box_a[0], box_b[0]),
            min(box_a[1], box_b[1]),
            max(box_a[2], box_b[2]),
            max(box_a[3], box_b[3]),
        )

    def _head_box_from_points(
        self,
        points: list[tuple[float, float]],
        frame_width: int,
        frame_height: int,
        pad_x: float,
        pad_top: float,
        pad_bottom: float,
    ) -> tuple[int, int, int, int] | None:
        if not points:
            return None
        min_x = min(point[0] for point in points)
        max_x = max(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_y = max(point[1] for point in points)
        span_x = max(max_x - min_x, 18.0)
        span_y = max(max_y - min_y, 12.0)
        base_w = max(span_x * 1.25, span_y * 1.9, 28.0)
        base_h = max(span_y * 1.8, span_x * 0.95, 28.0)
        return self._clip_box(
            (
                min_x - base_w * pad_x,
                min_y - base_h * pad_top,
                max_x + base_w * pad_x,
                max_y + base_h * pad_bottom,
            ),
            frame_width,
            frame_height,
        )

    def _get_body_support(self, frame: np.ndarray, now: float) -> list[dict]:
        try:
            from processor.body_detector import detect_bodies

            body_frame, scale_x, scale_y = self._prepare_body_frame(frame)
            with self._metrics.measure("body_inference"):
                with gpu_inference_gate.live():
                    detected = detect_bodies(
                        body_frame,
                        conf=0.28,
                        camera_key=self.camera_id,
                    )
            bodies = []
            for body in detected:
                payload = {
                    "box": self._rescale_box(
                        body["box"],
                        frame.shape[1],
                        frame.shape[0],
                        scale_x,
                        scale_y,
                    ),
                    "confidence": body.get("confidence"),
                }
                keypoints = body.get("keypoints")
                if isinstance(keypoints, list):
                    mapped_keypoints = []
                    for point in keypoints:
                        if isinstance(point, (list, tuple)) and len(point) >= 2:
                            mapped_keypoints.append([float(point[0]) * scale_x, float(point[1]) * scale_y])
                        else:
                            mapped_keypoints.append([0.0, 0.0])
                    payload["keypoints"] = mapped_keypoints
                keypoint_conf = body.get("keypoint_conf")
                if isinstance(keypoint_conf, list):
                    payload["keypoint_conf"] = [float(value) for value in keypoint_conf]
                track_id = body.get("track_id")
                if track_id is not None:
                    try:
                        payload["track_id"] = int(track_id)
                    except (TypeError, ValueError):
                        pass
                self._apply_body_pose_metadata(payload, frame.shape[1], frame.shape[0])
                bodies.append(payload)
        except Exception:
            logger.exception("Body support scan failed on camera %s", self.camera_id)
            bodies = []

        with self._analysis_lock:
            self._body_support_cache = bodies
            self._body_support_ts = now
        return bodies

    def _prepare_body_frame(self, frame: np.ndarray) -> tuple[np.ndarray, float, float]:
        height, width = frame.shape[:2]
        max_side = max(height, width)
        if max_side <= self._body_max_side:
            return frame, 1.0, 1.0
        scale = self._body_max_side / float(max_side)
        resized = cv2.resize(
            frame,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
        return resized, width / float(resized.shape[1]), height / float(resized.shape[0])

    def _apply_body_pose_metadata(
        self,
        body: dict[str, object],
        frame_width: int,
        frame_height: int,
    ) -> None:
        body_box = body.get("box")
        if not isinstance(body_box, tuple):
            return
        body["frame_size"] = (int(frame_width), int(frame_height))

        head_points = self._body_confident_points(body, (0, 1, 2, 3, 4), min_conf=0.16)
        facial_points = self._body_confident_points(body, (1, 2, 3, 4), min_conf=0.16)
        shoulder_points = self._body_confident_points(body, (5, 6), min_conf=0.18)

        body["head_only"] = False
        body["tracking_box"] = body_box
        if not head_points:
            return

        head_box = self._head_box_from_points(head_points, frame_width, frame_height, pad_x=0.35, pad_top=0.4, pad_bottom=0.8)
        tracking_head_box = self._head_box_from_points(
            head_points,
            frame_width,
            frame_height,
            pad_x=0.85 if len(shoulder_points) == 0 else 0.6,
            pad_top=0.55,
            pad_bottom=2.0 if len(shoulder_points) == 0 else 1.4,
        )
        if head_box is not None:
            body["head_box"] = head_box
            body["head_points"] = [[float(px), float(py)] for px, py in head_points]
        head_only = len(shoulder_points) == 0 and len(facial_points) >= 3
        body["head_only"] = head_only
        if tracking_head_box is None:
            return
        body["tracking_box"] = tracking_head_box if head_only else self._union_boxes(body_box, tracking_head_box)

    def _body_anchor(self, body: dict[str, object]) -> tuple[float, float] | None:
        head_points = body.get("head_points")
        if isinstance(head_points, list) and head_points:
            xs = [float(point[0]) for point in head_points if isinstance(point, (list, tuple)) and len(point) >= 2]
            ys = [float(point[1]) for point in head_points if isinstance(point, (list, tuple)) and len(point) >= 2]
            if xs and ys:
                return sum(xs) / len(xs), sum(ys) / len(ys)
        head_box = body.get("head_box")
        if isinstance(head_box, tuple):
            hx1, hy1, hx2, hy2 = head_box
            return (hx1 + hx2) / 2, (hy1 + hy2) / 2
        box = body.get("tracking_box")
        if not isinstance(box, tuple):
            box = body.get("box")
        if isinstance(box, tuple):
            x1, y1, x2, y2 = box
            return (x1 + x2) / 2, y1 + (y2 - y1) * 0.32
        return None

    def _predict_track_box(
        self,
        state: dict[str, object],
        now: float,
    ) -> tuple[int, int, int, int] | None:
        raw_box = state.get("tracking_box")
        if not isinstance(raw_box, tuple):
            raw_box = state.get("box")
        if not isinstance(raw_box, tuple):
            return None
        x1, y1, x2, y2 = [float(value) for value in raw_box]
        last_position_ts = float(
            state.get("last_flow_seen", state.get("last_seen", now)),
        )
        dt = max(0.0, min(now - last_position_ts, 0.5))
        velocity = state.get("velocity")
        if not isinstance(velocity, tuple) or len(velocity) != 4:
            return tuple(int(round(value)) for value in (x1, y1, x2, y2))
        vx, vy, vw, vh = [float(value) for value in velocity]
        cx = (x1 + x2) / 2.0 + vx * dt
        cy = (y1 + y2) / 2.0 + vy * dt
        width = max(8.0, (x2 - x1) + vw * dt)
        height = max(8.0, (y2 - y1) + vh * dt)
        return (
            int(round(cx - width / 2.0)),
            int(round(cy - height / 2.0)),
            int(round(cx + width / 2.0)),
            int(round(cy + height / 2.0)),
        )

    def _body_track_match_score(
        self,
        body: dict[str, object],
        state: dict[str, object],
        now: float,
    ) -> float:
        body_box = body.get("tracking_box")
        if not isinstance(body_box, tuple):
            body_box = body.get("box")
        predicted_box = self._predict_track_box(state, now)
        if not isinstance(body_box, tuple) or predicted_box is None:
            return 0.0

        bw = max(float(body_box[2] - body_box[0]), 1.0)
        bh = max(float(body_box[3] - body_box[1]), 1.0)
        pw = max(float(predicted_box[2] - predicted_box[0]), 1.0)
        ph = max(float(predicted_box[3] - predicted_box[1]), 1.0)
        scale_ratio = max(bw / pw, pw / bw, bh / ph, ph / bh)
        body_cx = (body_box[0] + body_box[2]) / 2.0
        body_cy = (body_box[1] + body_box[3]) / 2.0
        predicted_cx = (predicted_box[0] + predicted_box[2]) / 2.0
        predicted_cy = (predicted_box[1] + predicted_box[3]) / 2.0
        center_distance = float(
            np.hypot(body_cx - predicted_cx, body_cy - predicted_cy)
        )
        normalized_distance = center_distance / max(
            float(np.hypot(pw, ph)),
            float(np.hypot(bw, bh)),
            1.0,
        )
        identity_locked = self._track_has_recent_identity(state, now)
        if scale_ratio > (1.8 if identity_locked else 2.25):
            return 0.0
        if normalized_distance > (0.62 if identity_locked else 1.05):
            return 0.0

        iou_score = self._box_iou(body_box, predicted_box)
        anchor_score = max(0.0, 1.0 - normalized_distance)
        scale_score = 1.0 / scale_ratio
        keypoint_score = self._keypoint_geometry_score(body, state, predicted_box)
        score = (
            iou_score * 0.45
            + anchor_score * 0.25
            + keypoint_score * 0.20
            + scale_score * 0.10
        )
        if (
            body.get("track_id") is not None
            and body.get("track_id") == state.get("external_track_id")
        ):
            score += 0.08
        return min(1.0, score)

    def _keypoint_geometry_score(
        self,
        body: dict[str, object],
        state: dict[str, object],
        predicted_box: tuple[int, int, int, int],
    ) -> float:
        current_points = body.get("keypoints")
        previous_points = state.get("keypoints")
        current_conf = body.get("keypoint_conf")
        previous_conf = state.get("keypoint_conf")
        if not isinstance(current_points, list) or not isinstance(previous_points, list):
            return 0.5
        distances: list[float] = []
        diagonal = max(
            float(
                np.hypot(
                    predicted_box[2] - predicted_box[0],
                    predicted_box[3] - predicted_box[1],
                )
            ),
            1.0,
        )
        for index in range(min(len(current_points), len(previous_points), 17)):
            if (
                isinstance(current_conf, list)
                and index < len(current_conf)
                and float(current_conf[index]) < 0.2
            ):
                continue
            if (
                isinstance(previous_conf, list)
                and index < len(previous_conf)
                and float(previous_conf[index]) < 0.2
            ):
                continue
            current = current_points[index]
            previous = previous_points[index]
            if (
                not isinstance(current, (list, tuple))
                or not isinstance(previous, (list, tuple))
                or len(current) < 2
                or len(previous) < 2
            ):
                continue
            distances.append(
                float(
                    np.hypot(
                        float(current[0]) - float(previous[0]),
                        float(current[1]) - float(previous[1]),
                    )
                )
                / diagonal
            )
        if len(distances) < 2:
            return 0.5
        return max(0.0, 1.0 - min(1.0, float(np.median(distances)) / 0.45))

    def _track_geometry_scores(self, body: dict[str, object], state: dict[str, object]) -> tuple[float, float]:
        body_box = body.get("tracking_box")
        if not isinstance(body_box, tuple):
            body_box = body.get("box")
        state_box = state.get("tracking_box")
        if not isinstance(state_box, tuple):
            state_box = state.get("box")
        if not isinstance(body_box, tuple) or not isinstance(state_box, tuple):
            return 0.0, 0.0

        iou_score = self._box_iou(body_box, state_box)
        anchor_score = 0.0
        body_anchor = self._body_anchor(body)
        state_anchor = self._body_anchor(state)
        if body_anchor and state_anchor:
            dist = abs(body_anchor[0] - state_anchor[0]) + abs(body_anchor[1] - state_anchor[1])
            max_side = max(body_box[2] - body_box[0], body_box[3] - body_box[1], state_box[2] - state_box[0], state_box[3] - state_box[1], 1)
            max_dist = max(32.0, max_side * 0.9)
            anchor_score = 1.0 - min(1.0, dist / max_dist)
        return iou_score, anchor_score

    def _track_has_recent_identity(self, state: dict[str, object], now: float) -> bool:
        if not state.get("recognized"):
            return False
        last_identity_seen = float(state.get("last_identity_seen", 0.0) or 0.0)
        if last_identity_seen <= 0.0:
            return False
        return (now - last_identity_seen) <= self._recognized_track_hold_seconds

    def _remember_track_liveness(
        self,
        track_id: int,
        now: float,
        face_box: tuple[int, int, int, int],
    ) -> None:
        state = self._body_tracks.get(track_id)
        if not state:
            return
        if self._face_pose_support_score(face_box, state, strict=False) < 0.62:
            return
        state["last_live_face_seen"] = now
        state["live_face_box"] = face_box

    def _track_has_recent_live_face(self, state: dict[str, object], now: float) -> bool:
        last_seen = float(state.get("last_live_face_seen", 0.0) or 0.0)
        if last_seen <= 0.0:
            return False
        return (now - last_seen) <= self._liveness_live_hold_seconds

    def _track_match_score(self, body: dict[str, object], state: dict[str, object], now: float) -> float:
        base_score = self._body_track_match_score(body, state, now)
        if not self._track_has_recent_identity(state, now):
            return base_score

        iou_score, anchor_score = self._track_geometry_scores(body, state)

        # Recognized tracks should stay attached to the same body.
        if iou_score < 0.12 and anchor_score < 0.62:
            return 0.0

        locked_score = max(base_score, (iou_score * 0.58) + (anchor_score * 0.42) + 0.08)
        return min(1.0, locked_score)

    def _track_match_threshold(self, state: dict[str, object], now: float) -> float:
        return 0.48 if self._track_has_recent_identity(state, now) else 0.28

    def _box_iou(self, box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int]) -> float:
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter = max(0, inter_x2 - inter_x1) * max(0, inter_y2 - inter_y1)
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        return inter / float(area_a + area_b - inter + 1e-6)

    def _box_intersection_ratio(
        self,
        box_a: tuple[int, int, int, int],
        box_b: tuple[int, int, int, int],
    ) -> float:
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter = max(0, inter_x2 - inter_x1) * max(0, inter_y2 - inter_y1)
        smaller_area = min(max(1, (ax2 - ax1) * (ay2 - ay1)), max(1, (bx2 - bx1) * (by2 - by1)))
        return inter / float(smaller_area + 1e-6)

    def _prune_spoof_faces(self, now: float) -> None:
        if not self._spoof_face_boxes:
            return
        self._spoof_face_boxes = [
            (box, ts)
            for box, ts in self._spoof_face_boxes
            if now - ts <= self._spoof_face_ttl
        ][-12:]

    def _prune_blocked_faces(self, now: float) -> None:
        if not self._blocked_face_boxes:
            return
        ttl = max(
            1.5,
            min(
                self._spoof_face_ttl,
                float(getattr(settings, "antispoof_pending_timeout_seconds", 2.8))
                + self._target_scan_interval * 2.0,
            ),
        )
        self._blocked_face_boxes = [
            (box, ts)
            for box, ts in self._blocked_face_boxes
            if now - ts <= ttl
        ][-16:]

    def _remember_spoof_face(self, box: tuple[int, int, int, int], now: float) -> None:
        self._prune_spoof_faces(now)
        for idx, (known_box, _ts) in enumerate(self._spoof_face_boxes):
            if self._box_intersection_ratio(box, known_box) >= 0.35:
                self._spoof_face_boxes[idx] = (box, now)
                self._remember_blocked_face(box, now)
                return
        self._spoof_face_boxes.append((box, now))
        self._remember_blocked_face(box, now)

    def _remember_blocked_face(self, box: tuple[int, int, int, int], now: float) -> None:
        self._prune_blocked_faces(now)
        for idx, (known_box, _ts) in enumerate(self._blocked_face_boxes):
            if self._box_intersection_ratio(box, known_box) >= 0.25:
                self._blocked_face_boxes[idx] = (box, now)
                return
        self._blocked_face_boxes.append((box, now))

    def _forget_spoof_face(self, box: tuple[int, int, int, int], now: float) -> None:
        self._prune_spoof_faces(now)
        self._spoof_face_boxes = [
            (known_box, ts)
            for known_box, ts in self._spoof_face_boxes
            if self._box_intersection_ratio(box, known_box) < 0.35
        ]
        self._forget_blocked_face(box, now)

    def _forget_blocked_face(self, box: tuple[int, int, int, int], now: float) -> None:
        self._prune_blocked_faces(now)
        self._blocked_face_boxes = [
            (known_box, ts)
            for known_box, ts in self._blocked_face_boxes
            if self._box_intersection_ratio(box, known_box) < 0.25
        ]

    def _drop_spoofed_face_overlay(self, box: tuple[int, int, int, int], now: float) -> None:
        self._prune_spoof_faces(now)
        if not self._last_faces_info:
            return
        self._last_faces_info = [
            item
            for item in self._last_faces_info
            if self._box_intersection_ratio(item[0], box) < 0.35
        ]
        if not self._last_faces_info:
            self._last_faces_ts = 0.0
            self._last_faces_flow_ts = 0.0

    def _drop_spoofed_body_overlay(self, box: tuple[int, int, int, int], now: float) -> None:
        self._prune_spoof_faces(now)
        if not self._last_body_info:
            return
        kept: list[dict[str, object]] = []
        for item in self._last_body_info:
            raw_box = item.get("box")
            if not isinstance(raw_box, tuple):
                kept.append(item)
                continue
            x1, y1, x2, y2 = raw_box
            height = max(y2 - y1, 1)
            upper_box = (x1, y1, x2, int(y1 + height * 0.55))
            if self._box_intersection_ratio(upper_box, box) < 0.18:
                kept.append(item)
        self._last_body_info = kept
        if not self._last_body_info:
            self._last_body_ts = 0.0
            self._last_body_flow_ts = 0.0

    def _overlay_active_flags(self, now: float | None = None) -> tuple[bool, bool]:
        now = time.time() if now is None else now
        face_age = now - self._last_faces_ts
        body_age = now - self._last_body_ts
        face_active = bool(self._last_faces_info) and face_age <= self._face_overlay_ttl
        body_active = bool(self._last_body_info) and body_age <= self._body_overlay_ttl
        return face_active, body_active

    def _body_overlaps_spoof_face(self, state: dict[str, object], now: float) -> bool:
        self._prune_spoof_faces(now)
        self._prune_blocked_faces(now)
        blocked_faces = [*self._spoof_face_boxes, *self._blocked_face_boxes]
        if not blocked_faces:
            return False
        candidates: list[tuple[int, int, int, int]] = []
        head_box = state.get("head_box")
        if isinstance(head_box, tuple):
            candidates.append(head_box)
        box = state.get("tracking_box")
        if not isinstance(box, tuple):
            box = state.get("box")
        if isinstance(box, tuple):
            x1, y1, x2, y2 = box
            height = max(y2 - y1, 1)
            candidates.append((x1, y1, x2, int(y1 + height * 0.55)))
        for probe in candidates:
            for spoof_box, _ts in blocked_faces:
                if self._box_intersection_ratio(probe, spoof_box) >= 0.28:
                    return True
        return False

    def _update_body_tracks(self, bodies: list[dict], now: float) -> list[dict]:
        # MMDeploy track ids may be reused after occlusions; keep identity on local geometry tracks.
        stale_track_ids = [
            track_id
            for track_id, state in self._body_tracks.items()
            if now - float(state.get("last_seen", 0.0))
            > (
                self._recognized_track_hold_seconds
                if self._track_has_recent_identity(state, now)
                else self._track_reacquire_ttl
            )
        ]
        for track_id in stale_track_ids:
            self._body_tracks.pop(track_id, None)

        normalized_bodies: list[dict[str, object]] = []
        for body in bodies:
            box = tuple(int(round(v)) for v in body["box"])
            tracking_box = body.get("tracking_box")
            if not isinstance(tracking_box, tuple):
                tracking_box = box
            normalized = dict(body)
            normalized["box"] = box
            normalized["tracking_box"] = tracking_box
            normalized_bodies.append(normalized)

        unmatched_body_indices = set(range(len(normalized_bodies)))
        track_ids = list(self._body_tracks.keys())
        unmatched_track_ids = set(track_ids)
        if normalized_bodies and track_ids:
            cost_matrix = np.full(
                (len(normalized_bodies), len(track_ids)),
                1_000.0,
                dtype=np.float32,
            )
            for body_idx, body in enumerate(normalized_bodies):
                for track_index, track_id in enumerate(track_ids):
                    state = self._body_tracks.get(track_id)
                    if not state:
                        continue
                    score = self._track_match_score(body, state, now)
                    if score >= self._track_match_threshold(state, now):
                        cost_matrix[body_idx, track_index] = 1.0 - score
            body_rows, track_columns = linear_sum_assignment(cost_matrix)
            matches = [
                (int(body_idx), track_ids[int(track_index)])
                for body_idx, track_index in zip(
                    body_rows,
                    track_columns,
                    strict=False,
                )
                if float(cost_matrix[body_idx, track_index]) < 999.0
            ]
        else:
            matches = []

        for body_idx, track_id in matches:
            state = self._body_tracks[track_id]
            body = normalized_bodies[body_idx]
            previous_box = state.get("tracking_box")
            previous_seen = float(state.get("last_seen", now))
            if not isinstance(previous_box, tuple):
                previous_box = state.get("box")
            if isinstance(previous_box, tuple):
                dt = max(now - previous_seen, 1e-3)
                previous_cx = (previous_box[0] + previous_box[2]) / 2.0
                previous_cy = (previous_box[1] + previous_box[3]) / 2.0
                previous_w = max(previous_box[2] - previous_box[0], 1)
                previous_h = max(previous_box[3] - previous_box[1], 1)
                current_box = body["tracking_box"]
                current_cx = (current_box[0] + current_box[2]) / 2.0
                current_cy = (current_box[1] + current_box[3]) / 2.0
                current_w = max(current_box[2] - current_box[0], 1)
                current_h = max(current_box[3] - current_box[1], 1)
                measured_velocity = (
                    (current_cx - previous_cx) / dt,
                    (current_cy - previous_cy) / dt,
                    (current_w - previous_w) / dt,
                    (current_h - previous_h) / dt,
                )
                previous_velocity = state.get("velocity")
                if not isinstance(previous_velocity, tuple):
                    previous_velocity = (0.0, 0.0, 0.0, 0.0)
                state["velocity"] = tuple(
                    float(previous_velocity[index]) * 0.65
                    + measured_velocity[index] * 0.35
                    for index in range(4)
                )
            state["box"] = body["box"]
            state["tracking_box"] = body["tracking_box"]
            state["confidence"] = body.get("confidence")
            state["keypoints"] = body.get("keypoints")
            state["keypoint_conf"] = body.get("keypoint_conf")
            state["frame_size"] = body.get("frame_size")
            state["head_points"] = body.get("head_points")
            state["head_box"] = body.get("head_box")
            state["head_only"] = bool(body.get("head_only"))
            state["external_track_id"] = body.get("track_id")
            state["last_seen"] = now
            state["visible"] = True
            state["hits"] = int(state.get("hits", 0)) + 1
            unmatched_body_indices.discard(body_idx)
            unmatched_track_ids.discard(track_id)

        for track_id in unmatched_track_ids:
            state = self._body_tracks.get(track_id)
            if state is not None:
                state["visible"] = False

        for body_idx in sorted(unmatched_body_indices):
            body = normalized_bodies[body_idx]
            track_id = self._next_body_track_id
            self._next_body_track_id += 1
            self._body_tracks[track_id] = {
                "track_id": track_id,
                "external_track_id": body.get("track_id"),
                "box": body["box"],
                "tracking_box": body["tracking_box"],
                "confidence": body.get("confidence"),
                "last_seen": now,
                "visible": True,
                "hits": 1,
                "velocity": (0.0, 0.0, 0.0, 0.0),
                "keypoints": body.get("keypoints"),
                "keypoint_conf": body.get("keypoint_conf"),
                "frame_size": body.get("frame_size"),
                "head_points": body.get("head_points"),
                "head_box": body.get("head_box"),
                "head_only": bool(body.get("head_only")),
                "person_id": None,
                "label": None,
                "recognized": False,
                "last_identity_seen": 0.0,
                "last_live_face_seen": 0.0,
            }

        self._dedupe_body_tracks()
        return [dict(state) for state in self._body_tracks.values()]

    def _update_external_body_tracks(self, bodies: list[dict], now: float) -> list[dict]:
        seen_track_ids: set[int] = set()
        for body in bodies:
            ext_track_id = body.get("track_id")
            if not isinstance(ext_track_id, int):
                continue
            seen_track_ids.add(ext_track_id)
            box = tuple(int(round(v)) for v in body["box"])
            tracking_box = body.get("tracking_box")
            if not isinstance(tracking_box, tuple):
                tracking_box = box

            state = self._body_tracks.get(ext_track_id)
            if state is None:
                state = {
                    "track_id": ext_track_id,
                    "person_id": None,
                    "label": None,
                    "recognized": False,
                    "last_identity_seen": 0.0,
                    "last_live_face_seen": 0.0,
                    "hits": 0,
                }
                self._body_tracks[ext_track_id] = state

            state["box"] = box
            state["tracking_box"] = tracking_box
            state["confidence"] = body.get("confidence")
            state["keypoints"] = body.get("keypoints")
            state["keypoint_conf"] = body.get("keypoint_conf")
            state["frame_size"] = body.get("frame_size")
            state["head_points"] = body.get("head_points")
            state["head_box"] = body.get("head_box")
            state["head_only"] = bool(body.get("head_only"))
            state["last_seen"] = now
            state["hits"] = int(state.get("hits", 0)) + 1

        stale_track_ids = [
            track_id
            for track_id, state in self._body_tracks.items()
            if track_id not in seen_track_ids
            and now - float(state.get("last_seen", 0.0))
            > (5.0 if self._track_has_recent_identity(state, now) else 3.5)
        ]
        for track_id in stale_track_ids:
            self._body_tracks.pop(track_id, None)

        return [dict(state) for state in self._body_tracks.values()]

    def _dedupe_body_tracks(self) -> None:
        track_ids = list(self._body_tracks.keys())
        to_remove: set[int] = set()
        for idx, track_id in enumerate(track_ids):
            if track_id in to_remove:
                continue
            state = self._body_tracks.get(track_id)
            if not state:
                continue
            box = state.get("tracking_box")
            if not isinstance(box, tuple):
                box = state.get("box")
            if not isinstance(box, tuple):
                continue
            person_id = state.get("person_id")
            for other_id in track_ids[idx + 1:]:
                if other_id in to_remove:
                    continue
                other = self._body_tracks.get(other_id)
                if not other:
                    continue
                other_box = other.get("tracking_box")
                if not isinstance(other_box, tuple):
                    other_box = other.get("box")
                if not isinstance(other_box, tuple):
                    continue
                same_person = person_id is not None and person_id == other.get("person_id")
                overlap = self._box_iou(box, other_box)
                if not same_person and overlap < 0.55:
                    continue
                state_recognized = bool(state.get("recognized"))
                other_recognized = bool(other.get("recognized"))
                if state_recognized != other_recognized:
                    keep_first = state_recognized
                elif same_person:
                    keep_first = (
                        float(state.get("last_identity_seen", 0.0))
                        >= float(other.get("last_identity_seen", 0.0))
                    )
                else:
                    keep_first = (
                        int(state.get("hits", 0)) >= int(other.get("hits", 0))
                        and float(state.get("last_seen", 0.0)) >= float(other.get("last_seen", 0.0)) - 0.2
                    )
                to_remove.add(other_id if keep_first else track_id)
                if not keep_first:
                    break
        for track_id in to_remove:
            self._body_tracks.pop(track_id, None)

    def _find_body_track_for_face(
        self,
        face_box: tuple[int, int, int, int],
        body_tracks: list[dict],
    ) -> int | None:
        x1, y1, x2, y2 = face_box
        face_cx = (x1 + x2) / 2
        face_cy = (y1 + y2) / 2
        face_width = max(x2 - x1, 1)
        face_height = max(y2 - y1, 1)
        best_track_id: int | None = None
        best_score = 0.0
        for state in body_tracks:
            body_box = state.get("tracking_box")
            if not isinstance(body_box, tuple):
                body_box = state.get("box")
            track_id = state.get("track_id")
            if not isinstance(body_box, tuple) or track_id is None:
                continue
            head_only = bool(state.get("head_only"))
            pose_score = self._face_pose_support_score(face_box, state, strict=head_only)
            if pose_score > 0.0:
                score = 0.62 + (pose_score * 0.38)
                if score > best_score:
                    best_score = score
                    best_track_id = int(track_id)
            bx1, by1, bx2, by2 = body_box
            body_width = max(bx2 - bx1, 1)
            body_height = max(by2 - by1, 1)
            if not (bx1 <= face_cx <= bx2):
                continue
            if not (by1 <= face_cy <= by1 + body_height * (0.58 if head_only else 0.45)):
                continue
            width_ratio = face_width / body_width
            height_ratio = face_height / body_height
            max_width_ratio = 0.82 if head_only else 0.55
            max_height_ratio = 0.78 if head_only else 0.42
            if not (0.08 <= width_ratio <= max_width_ratio and 0.07 <= height_ratio <= max_height_ratio):
                continue
            body_cx = (bx1 + bx2) / 2
            center_score = 1.0 - min(1.0, abs(face_cx - body_cx) / max(body_width * (0.48 if head_only else 0.35), 1.0))
            target_ratio = 0.46 if head_only else 0.24
            scale_score = 1.0 - min(1.0, abs(width_ratio - target_ratio) / max(target_ratio, 0.12))
            score = (center_score * 0.7) + (scale_score * 0.3)
            if score > best_score:
                best_score = score
                best_track_id = int(track_id)
        return best_track_id if best_score >= 0.55 else None

    def _remember_track_identity(
        self,
        track_id: int,
        person_id: int | None,
        label: str,
        now: float,
        face_box: tuple[int, int, int, int] | None = None,
        sim: float | None = None,
    ) -> None:
        if person_id is None:
            return
        state = self._body_tracks.get(track_id)
        if not state:
            return
        previous_person_id = state.get("person_id")
        if (
            previous_person_id is not None
            and previous_person_id != person_id
            and self._track_has_recent_identity(state, now)
            and (sim is None or sim < max(settings.face_match_threshold + 0.08, 0.66))
        ):
            return
        if face_box is not None and self._face_pose_support_score(face_box, state, strict=False) < 0.72:
            return
        state["person_id"] = person_id
        state["label"] = label
        state["recognized"] = True
        state["last_identity_seen"] = now
        state["identity_face_box"] = face_box
        state["identity_sim"] = float(sim or 0.0)

    def _recover_track_identity(
        self,
        track_id: int,
        sim: float | None,
        now: float,
        face_box: tuple[int, int, int, int] | None = None,
    ) -> int | None:
        state = self._body_tracks.get(track_id)
        if not state or not self._track_has_recent_identity(state, now):
            return None
        if sim is None or sim < max(settings.face_match_threshold + 0.04, 0.60):
            return None
        if face_box is not None and self._face_pose_support_score(face_box, state, strict=False) < 0.72:
            return None
        person_id = state.get("person_id")
        return int(person_id) if person_id is not None else None

    def _track_has_independent_body_motion(self, state: dict[str, object], now: float) -> bool:
        if int(state.get("hits", 0) or 0) < 4:
            return False
        if bool(state.get("head_only")):
            return False
        if not self._track_has_minimum_upper_pose(state):
            return False
        box = state.get("tracking_box")
        if not isinstance(box, tuple):
            box = state.get("box")
        if not isinstance(box, tuple):
            return False
        velocity = state.get("velocity")
        if not isinstance(velocity, tuple) or len(velocity) < 4:
            return False
        vx, vy, vw, vh = (float(value) for value in velocity[:4])
        width = max(box[2] - box[0], 1)
        height = max(box[3] - box[1], 1)
        scale = max(width, height)
        center_speed = float(np.hypot(vx, vy))
        size_speed = abs(vw) + abs(vh)
        return center_speed >= max(45.0, scale * 0.16) or size_speed >= max(35.0, scale * 0.12)

    def _build_body_overlay_items(
        self,
        body_tracks: list[dict],
        now: float,
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for state in body_tracks:
            if now - float(state.get("last_seen", 0.0)) > self._track_visible_ttl:
                continue
            recognized = bool(state.get("recognized")) and self._track_has_recent_identity(state, now)
            box = state.get("tracking_box")
            if not isinstance(box, tuple):
                box = state.get("box")
            if not isinstance(box, tuple):
                continue
            if self._body_overlaps_spoof_face(state, now):
                continue
            if not self._track_has_minimum_upper_pose(state):
                continue
            if not recognized:
                hits = int(state.get("hits", 0) or 0)
                if hits < 2:
                    continue
                if not self._track_has_recent_live_face(state, now) and not self._track_has_independent_body_motion(state, now):
                    continue
            label = state.get("label") if recognized else f"Неизвестно #{state.get('track_id', '?')}"
            items.append(
                {
                    "box": box,
                    "label": str(label),
                    "recognized": recognized,
                    "track_id": state.get("track_id"),
                    "keypoints": state.get("keypoints"),
                    "keypoint_conf": state.get("keypoint_conf"),
                }
            )
        return items

    def _body_label_position(
        self,
        box: tuple[int, int, int, int],
        keypoints: object,
        keypoint_conf: object,
    ) -> tuple[int, int]:
        x1, y1, _, _ = box
        if isinstance(keypoints, list) and len(keypoints) >= 7:
            confs = keypoint_conf if isinstance(keypoint_conf, list) else None
            head_points: list[tuple[float, float]] = []
            for kp_idx in (0, 1, 2, 3, 4, 5, 6):
                if kp_idx >= len(keypoints):
                    continue
                if confs is not None and kp_idx < len(confs) and float(confs[kp_idx]) < 0.28:
                    continue
                point = keypoints[kp_idx]
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    head_points.append((float(point[0]), float(point[1])))
            if head_points:
                min_x = min(point[0] for point in head_points)
                min_y = min(point[1] for point in head_points)
                return int(min_x), max(6, int(min_y) - 28)
        return x1, max(y1 - 28, 6)

    def _face_key(self, box: tuple[int, int, int, int]) -> str:
        x1, y1, x2, y2 = box
        width = max(x2 - x1, 1)
        height = max(y2 - y1, 1)
        cx = x1 + width / 2
        cy = y1 + height / 2
        return f"{round(cx / 40)}:{round(cy / 40)}:{round(width / 40)}:{round(height / 40)}"

    def _face_state_key(
        self,
        box: tuple[int, int, int, int],
        track_id: int | None = None,
        now: float | None = None,
    ) -> str:
        now = time.time() if now is None else now
        x1, y1, x2, y2 = box
        width = max(x2 - x1, 1)
        height = max(y2 - y1, 1)
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        best_key: str | None = None
        best_score = 0.0
        for key, state in self._liveness_state.items():
            if now - float(state.get("last_seen", 0.0)) > 3.0:
                continue
            previous_box = state.get("box")
            if not isinstance(previous_box, tuple):
                continue
            px1, py1, px2, py2 = previous_box
            previous_width = max(px2 - px1, 1)
            previous_height = max(py2 - py1, 1)
            size_ratio = min(
                width / previous_width,
                previous_width / width,
                height / previous_height,
                previous_height / height,
            )
            if size_ratio < 0.42:
                continue
            previous_cx = (px1 + px2) / 2
            previous_cy = (py1 + py2) / 2
            center_distance = float(np.hypot(cx - previous_cx, cy - previous_cy))
            normalized_distance = center_distance / max(width, height, previous_width, previous_height, 1)
            iou = self._box_iou(box, previous_box)
            same_track = track_id is not None and state.get("track_id") == track_id
            if iou < 0.08 and normalized_distance > (1.6 if same_track else 0.68):
                continue
            score = (max(iou, 1.0 - normalized_distance) * 0.68) + (size_ratio * 0.32)
            if same_track:
                score += 0.18
            if score > best_score:
                best_score = score
                best_key = key
        if best_key is not None and best_score >= 0.44:
            return best_key
        key = f"face:{self._next_liveness_state_id}"
        self._next_liveness_state_id += 1
        return key

    def _should_skip_unknown_embedding(
        self,
        embedding: np.ndarray,
        ttl: float | None = None,
        sim_thr: float | None = None,
    ) -> bool:
        ttl = self._unknown_event_dedup_seconds if ttl is None else ttl
        sim_thr = max(settings.face_match_threshold + 0.08, 0.64) if sim_thr is None else sim_thr
        probe = np.asarray(embedding, dtype=np.float32)
        norm = float(np.linalg.norm(probe))
        if norm <= 1e-6:
            return False
        probe = probe / norm
        now = time.time()
        self._unknown_event_cache = [
            (cached, ts)
            for cached, ts in self._unknown_event_cache
            if now - ts < ttl
        ]
        for cached, _ in self._unknown_event_cache:
            sim = float(np.dot(probe, cached))
            if sim >= sim_thr:
                return True
        self._unknown_event_cache.append((probe, now))
        return False

    def _crop_face(self, frame: np.ndarray, box: tuple[int, int, int, int], pad_ratio: float = 0.15) -> np.ndarray | None:
        x1, y1, x2, y2 = box
        width = max(x2 - x1, 1)
        height = max(y2 - y1, 1)
        pad_x = int(width * pad_ratio)
        pad_y = int(height * pad_ratio)
        h, w = frame.shape[:2]
        xs1 = max(0, x1 - pad_x)
        ys1 = max(0, y1 - pad_y)
        xs2 = min(w, x2 + pad_x)
        ys2 = min(h, y2 + pad_y)
        if xs2 <= xs1 or ys2 <= ys1:
            return None
        crop = frame[ys1:ys2, xs1:xs2]
        if crop.size == 0:
            return None
        return crop

    def _crop_context(self, frame: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray | None:
        return self._crop_face(frame, box, pad_ratio=0.7)

    @staticmethod
    def _is_infrared_like_frame(frame: np.ndarray) -> bool:
        """Detect the monochrome output produced by a camera in IR mode."""
        if frame.ndim != 3 or frame.shape[2] < 3:
            return False
        sample = cv2.resize(frame[:, :, :3], (64, 36), interpolation=cv2.INTER_AREA).astype(np.int16)
        channel_spread = sample.max(axis=2) - sample.min(axis=2)
        return bool(
            float(channel_spread.mean()) <= 2.0
            and float(np.percentile(channel_spread, 90)) <= 4.0
        )

    def _face_supported_by_body(self, box: tuple[int, int, int, int], bodies: list[dict]) -> bool:
        x1, y1, x2, y2 = box
        face_cx = (x1 + x2) / 2
        face_cy = (y1 + y2) / 2
        face_width = max(x2 - x1, 1)
        face_height = max(y2 - y1, 1)
        for body in bodies:
            raw_box = body.get("tracking_box")
            if not isinstance(raw_box, tuple):
                raw_box = body.get("box")
            if not isinstance(raw_box, tuple):
                continue
            bx1, by1, bx2, by2 = [float(v) for v in raw_box]
            body_width = max(bx2 - bx1, 1.0)
            body_height = max(by2 - by1, 1.0)
            face_inside = bx1 <= face_cx <= bx2 and by1 <= face_cy <= by1 + body_height * 0.55
            scale_ok = face_width <= body_width * 0.85 and face_height <= body_height * 0.55
            if face_inside and scale_ok:
                return True
        return False

    def _body_confident_points(
        self,
        body: dict,
        indices: tuple[int, ...],
        min_conf: float = 0.28,
    ) -> list[tuple[float, float]]:
        keypoints = body.get("keypoints")
        keypoint_conf = body.get("keypoint_conf")
        if not isinstance(keypoints, list):
            return []
        confs = keypoint_conf if isinstance(keypoint_conf, list) else None
        points: list[tuple[float, float]] = []
        for idx in indices:
            if idx >= len(keypoints):
                continue
            if confs is not None and idx < len(confs) and float(confs[idx]) < min_conf:
                continue
            point = keypoints[idx]
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                points.append((float(point[0]), float(point[1])))
        return points

    def _face_pose_support_score(
        self,
        box: tuple[int, int, int, int],
        body: dict,
        strict: bool = False,
    ) -> float:
        x1, y1, x2, y2 = box
        face_width = max(x2 - x1, 1.0)
        face_height = max(y2 - y1, 1.0)
        pad_x = face_width * (0.2 if strict else 0.3)
        pad_y = face_height * (0.16 if strict else 0.28)
        expanded_x1 = x1 - pad_x
        expanded_y1 = y1 - pad_y
        expanded_x2 = x2 + pad_x
        expanded_y2 = y2 + pad_y
        face_cx = (x1 + x2) / 2

        head_points = self._body_confident_points(body, (0, 1, 2, 3, 4), min_conf=0.2 if strict else 0.16)
        facial_points = self._body_confident_points(body, (1, 2, 3, 4), min_conf=0.18 if strict else 0.16)
        shoulder_points = self._body_confident_points(body, (5, 6), min_conf=0.2)
        if not head_points:
            return 0.0

        face_hits = sum(
            1
            for px, py in head_points
            if expanded_x1 <= px <= expanded_x2 and expanded_y1 <= py <= expanded_y2
        )
        facial_hits = sum(
            1
            for px, py in facial_points
            if expanded_x1 <= px <= expanded_x2 and expanded_y1 <= py <= expanded_y2
        )
        if face_hits < (3 if strict else 2):
            return 0.0

        min_head_x = min(point[0] for point in head_points)
        max_head_x = max(point[0] for point in head_points)
        max_head_y = max(point[1] for point in head_points)
        face_center_aligned = (min_head_x - face_width * 0.45) <= face_cx <= (max_head_x + face_width * 0.45)
        head_cluster_wide = (max_head_x - min_head_x) >= face_width * (0.34 if strict else 0.24)

        if shoulder_points:
            shoulder_min_x = min(point[0] for point in shoulder_points)
            shoulder_max_x = max(point[0] for point in shoulder_points)
            shoulder_min_y = min(point[1] for point in shoulder_points)
            shoulder_span_ok = shoulder_min_x - face_width * 0.45 <= face_cx <= shoulder_max_x + face_width * 0.45
            shoulder_vertical_ok = shoulder_min_y >= y1 + face_height * 0.12
            if shoulder_span_ok and shoulder_vertical_ok:
                return 1.0
            if strict:
                return 0.0

        head_only_supported = facial_hits >= (3 if strict else 2) and head_cluster_wide and face_center_aligned
        if head_only_supported:
            return 0.92 if strict else 0.84
        if not strict and len(head_points) >= 4 and max_head_y >= y1 + face_height * 0.15 and face_center_aligned:
            return 0.72
        return 0.0

    def _face_supported_by_pose(
        self,
        box: tuple[int, int, int, int],
        bodies: list[dict],
        strict: bool = False,
    ) -> bool:
        for body in bodies:
            if self._face_pose_support_score(box, body, strict=strict) >= (0.88 if strict else 0.72):
                return True
        return False

    def _face_strictly_supported_by_body(self, box: tuple[int, int, int, int], bodies: list[dict]) -> bool:
        x1, y1, x2, y2 = box
        face_cx = (x1 + x2) / 2
        face_cy = (y1 + y2) / 2
        face_width = max(x2 - x1, 1)
        face_height = max(y2 - y1, 1)
        for body in bodies:
            raw_box = body.get("tracking_box")
            if not isinstance(raw_box, tuple):
                raw_box = body.get("box")
            if not isinstance(raw_box, tuple):
                continue
            bx1, by1, bx2, by2 = [float(v) for v in raw_box]
            body_width = max(bx2 - bx1, 1.0)
            body_height = max(by2 - by1, 1.0)
            body_cx = (bx1 + bx2) / 2

            if not (bx1 <= face_cx <= bx2):
                continue
            if not (by1 <= face_cy <= by1 + body_height * 0.42):
                continue

            horizontal_offset_ok = abs(face_cx - body_cx) <= body_width * 0.26
            width_ratio = face_width / body_width
            height_ratio = face_height / body_height
            scale_ok = 0.10 <= width_ratio <= 0.52 and 0.08 <= height_ratio <= 0.40
            if horizontal_offset_ok and scale_ok:
                return True
        return False

    def _track_has_pose_support(self, state: dict[str, object] | None, strict: bool = False) -> bool:
        if not state:
            return False
        box = state.get("head_box")
        if not isinstance(box, tuple):
            box = state.get("tracking_box")
        if not isinstance(box, tuple):
            box = state.get("box")
        if not isinstance(box, tuple):
            return False
        probe = {
            "box": state.get("tracking_box") if isinstance(state.get("tracking_box"), tuple) else box,
            "keypoints": state.get("keypoints"),
            "keypoint_conf": state.get("keypoint_conf"),
        }
        return self._face_supported_by_pose(box, [probe], strict=strict)

    def _track_has_minimum_upper_pose(self, state: dict[str, object] | None) -> bool:



        if not state:
            return False
        keypoints = state.get("keypoints")
        confidence = state.get("keypoint_conf")
        if not isinstance(keypoints, list):
            return False
        confs = confidence if isinstance(confidence, list) else None

        def visible_point(index: int, threshold: float) -> tuple[float, float] | None:
            if index >= len(keypoints):
                return None
            point = keypoints[index]
            if (
                not isinstance(point, (list, tuple))
                or len(point) < 2
                or (float(point[0]) == 0.0 and float(point[1]) == 0.0)
            ):
                return None
            if confs is not None and index < len(confs):
                if float(confs[index]) < threshold:
                    return None
            px = float(point[0])
            py = float(point[1])
            if not np.isfinite(px) or not np.isfinite(py):
                return None
            return px, py

        head_points = {
            index: point
            for index in range(5)
            if (point := visible_point(index, 0.16)) is not None
        }
        left_shoulder = visible_point(5, 0.18)
        right_shoulder = visible_point(6, 0.18)
        if left_shoulder is None or right_shoulder is None:
            return False

        raw_box = state.get("box")
        if not isinstance(raw_box, tuple):
            raw_box = state.get("tracking_box")
        if not isinstance(raw_box, tuple):
            return False
        x1, y1, x2, y2 = [float(v) for v in raw_box]
        body_width = max(x2 - x1, 1.0)
        body_height = max(y2 - y1, 1.0)
        raw_frame_size = state.get("frame_size")
        frame_width = frame_height = None
        if (
            isinstance(raw_frame_size, (list, tuple))
            and len(raw_frame_size) >= 2
        ):
            try:
                frame_width = float(raw_frame_size[0])
                frame_height = float(raw_frame_size[1])
            except (TypeError, ValueError):
                frame_width = frame_height = None
        margin_x = max(24.0, body_width * 0.24)
        margin_top = max(14.0, body_height * 0.16)
        margin_bottom = max(24.0, body_height * 0.24)

        for px, py in (left_shoulder, right_shoulder):
            if not (x1 - margin_x <= px <= x2 + margin_x):
                return False
            if not (y1 - margin_top <= py <= y2 + margin_bottom):
                return False

        nose_visible = 0 in head_points
        head_ok = nose_visible and len(head_points) >= 2
        if not head_ok:
            return False

        head_x = sum(point[0] for point in head_points.values()) / len(head_points)
        head_y = sum(point[1] for point in head_points.values()) / len(head_points)
        shoulder_y = (left_shoulder[1] + right_shoulder[1]) / 2.0
        shoulder_span = abs(right_shoulder[0] - left_shoulder[0])
        shoulder_center_x = (left_shoulder[0] + right_shoulder[0]) / 2.0

        if shoulder_span < max(8.0, body_width * 0.05):
            return False
        if shoulder_span > max(160.0, body_width * 1.05):
            return False
        if abs(left_shoulder[1] - right_shoulder[1]) > max(48.0, body_height * 0.32):
            return False
        if shoulder_y < head_y + max(3.0, body_height * 0.01):
            return False
        if abs(shoulder_center_x - head_x) > max(90.0, shoulder_span * 1.1, body_width * 0.55):
            return False

        min_shoulder_x = min(left_shoulder[0], right_shoulder[0])
        max_shoulder_x = max(left_shoulder[0], right_shoulder[0])
        if not (min_shoulder_x - shoulder_span * 0.75 <= head_x <= max_shoulder_x + shoulder_span * 0.75):
            return False

        def arm_side_supported(
            shoulder: tuple[float, float],
            elbow_index: int,
            wrist_index: int,
        ) -> bool:
            for index, threshold in ((elbow_index, 0.14), (wrist_index, 0.18)):
                point = visible_point(index, threshold)
                if point is None:
                    continue
                if frame_width is not None and not (4.0 <= point[0] <= frame_width - 4.0):
                    continue
                if frame_height is not None and not (4.0 <= point[1] <= frame_height - 4.0):
                    continue
                horizontal_margin = max(70.0, body_width * 0.55, shoulder_span * 1.65)
                if not (x1 - horizontal_margin <= point[0] <= x2 + horizontal_margin):
                    continue
                if not (y1 - margin_top <= point[1] <= y2 + max(72.0, body_height * 0.46)):
                    continue
                distance = float(np.hypot(point[0] - shoulder[0], point[1] - shoulder[1]))
                max_distance = max(175.0, shoulder_span * 3.5, body_width * 1.45, body_height * 0.78)
                if distance <= max_distance:
                    return True
            return False

        return arm_side_supported(left_shoulder, 7, 9) or arm_side_supported(right_shoulder, 8, 10)

    def _body_drawable_keypoints(
        self,
        state: dict[str, object] | None,
        frame_shape: tuple[int, ...] | None = None,
    ) -> dict[int, tuple[float, float]]:
        if not self._track_has_minimum_upper_pose(state):
            return {}
        if not state:
            return {}
        keypoints = state.get("keypoints")
        confidence = state.get("keypoint_conf")
        if not isinstance(keypoints, list):
            return {}
        confs = confidence if isinstance(confidence, list) else None
        raw_box = state.get("box")
        if not isinstance(raw_box, tuple):
            raw_box = state.get("tracking_box")
        if not isinstance(raw_box, tuple):
            return {}
        x1, y1, x2, y2 = [float(value) for value in raw_box]
        body_width = max(x2 - x1, 1.0)
        body_height = max(y2 - y1, 1.0)
        frame_width = float(frame_shape[1]) if frame_shape is not None and len(frame_shape) >= 2 else None
        frame_height = float(frame_shape[0]) if frame_shape is not None and len(frame_shape) >= 2 else None
        if frame_width is None or frame_height is None:
            raw_frame_size = state.get("frame_size")
            if (
                isinstance(raw_frame_size, (list, tuple))
                and len(raw_frame_size) >= 2
            ):
                try:
                    frame_width = float(raw_frame_size[0])
                    frame_height = float(raw_frame_size[1])
                except (TypeError, ValueError):
                    frame_width = frame_height = None

        def valid_point(index: int, threshold: float) -> tuple[float, float] | None:
            if index >= len(keypoints):
                return None
            point = keypoints[index]
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                return None
            if confs is not None and index < len(confs) and float(confs[index]) < threshold:
                return None
            px = float(point[0])
            py = float(point[1])
            if not np.isfinite(px) or not np.isfinite(py):
                return None
            if px == 0.0 and py == 0.0:
                return None
            if frame_width is not None and not (0.0 <= px <= frame_width):
                return None
            if frame_height is not None and not (0.0 <= py <= frame_height):
                return None
            return px, py

        left_shoulder = valid_point(5, 0.18)
        right_shoulder = valid_point(6, 0.18)
        if left_shoulder is None or right_shoulder is None:
            return {}

        shoulder_y = (left_shoulder[1] + right_shoulder[1]) / 2.0
        shoulder_span = max(abs(right_shoulder[0] - left_shoulder[0]), 1.0)
        head_anchor_points = [
            point
            for index in range(5)
            if (point := valid_point(index, 0.16)) is not None
        ]
        head_y = (
            sum(point[1] for point in head_anchor_points) / len(head_anchor_points)
            if head_anchor_points
            else shoulder_y - body_height * 0.2
        )
        upper_height = max(shoulder_y - head_y, body_height * 0.22, shoulder_span * 0.65, 1.0)

        drawable: dict[int, tuple[float, float]] = {
            5: left_shoulder,
            6: right_shoulder,
        }

        def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
            return float(np.hypot(a[0] - b[0], a[1] - b[1]))

        def near_body(point: tuple[float, float], *, top_factor: float = 0.14, bottom_factor: float = 0.18) -> bool:
            margin_x = max(30.0, body_width * 0.28, shoulder_span * 0.9)
            margin_top = max(14.0, body_height * top_factor)
            margin_bottom = max(18.0, body_height * bottom_factor)
            return (
                x1 - margin_x <= point[0] <= x2 + margin_x
                and y1 - margin_top <= point[1] <= y2 + margin_bottom
            )

        head_points = {
            index: point
            for index in range(5)
            if (point := valid_point(index, 0.16)) is not None
        }
        shoulder_center_x = (left_shoulder[0] + right_shoulder[0]) / 2.0
        for index, point in head_points.items():
            if not near_body(point, top_factor=0.22, bottom_factor=0.02):
                continue
            if point[1] > shoulder_y + max(12.0, upper_height * 0.34):
                continue
            if abs(point[0] - shoulder_center_x) > max(85.0, shoulder_span * 1.05, body_width * 0.45):
                continue
            drawable[index] = point
        if not any(index in drawable for index in range(5)):
            return {}

        for index, shoulder_index in ((7, 5), (8, 6)):
            point = valid_point(index, 0.18)
            shoulder = drawable.get(shoulder_index)
            if point is None or shoulder is None or not near_body(point):
                continue
            max_distance = max(110.0, shoulder_span * 2.35, body_width * 0.95, upper_height * 1.9)
            if distance(point, shoulder) <= max_distance:
                drawable[index] = point

        for index, elbow_index in ((9, 7), (10, 8)):
            point = valid_point(index, 0.22)
            elbow = drawable.get(elbow_index)
            if point is None or elbow is None or not near_body(point, bottom_factor=0.36):
                continue
            max_distance = max(118.0, shoulder_span * 2.25, body_width * 0.95, upper_height * 1.9)
            if distance(point, elbow) <= max_distance:
                drawable[index] = point

        left_hip = valid_point(11, 0.20)
        right_hip = valid_point(12, 0.20)
        hips_drawable = False
        if left_hip is not None and right_hip is not None:
            hip_y = (left_hip[1] + right_hip[1]) / 2.0
            hip_span = max(abs(right_hip[0] - left_hip[0]), 1.0)
            hip_center_x = (left_hip[0] + right_hip[0]) / 2.0
            torso_height = hip_y - shoulder_y
            hips_drawable = (
                hip_span >= max(10.0, shoulder_span * 0.28)
                and hip_span <= max(130.0, shoulder_span * 1.65, body_width * 0.82)
                and abs(left_hip[1] - right_hip[1]) <= max(42.0, body_height * 0.22)
                and max(24.0, body_height * 0.12) <= torso_height <= max(260.0, body_height * 0.78)
                and abs(hip_center_x - shoulder_center_x) <= max(70.0, shoulder_span * 0.85, body_width * 0.32)
                and near_body(left_hip, bottom_factor=0.24)
                and near_body(right_hip, bottom_factor=0.24)
            )
            if hips_drawable:
                drawable[11] = left_hip
                drawable[12] = right_hip
        if not hips_drawable:
            return drawable

        hip_span = max(abs(right_hip[0] - left_hip[0]), 1.0)
        torso_height = max(((left_hip[1] + right_hip[1]) / 2.0) - shoulder_y, 1.0)

        for index, hip_index in ((13, 11), (14, 12)):
            point = valid_point(index, 0.36)
            hip = drawable.get(hip_index)
            if point is None or hip is None or not near_body(point, bottom_factor=0.38):
                continue
            max_distance = max(86.0, torso_height * 0.82, hip_span * 1.8)
            if point[1] >= hip[1] - 10.0 and distance(point, hip) <= max_distance:
                drawable[index] = point

        for index, knee_index in ((15, 13), (16, 14)):
            point = valid_point(index, 0.40)
            knee = drawable.get(knee_index)
            if point is None or knee is None or not near_body(point, bottom_factor=0.45):
                continue
            max_distance = max(86.0, torso_height * 0.82, hip_span * 1.8)
            if point[1] >= knee[1] - 10.0 and distance(point, knee) <= max_distance:
                drawable[index] = point

        return drawable

    def _prune_liveness_state(self, now: float) -> None:
        stale_keys = [
            key
            for key, state in self._liveness_state.items()
            if now - float(state.get("last_seen", 0.0)) > 12.0
        ]
        for key in stale_keys:
            self._liveness_state.pop(key, None)

    def _prune_identity_state(self, now: float) -> None:
        stale_keys = [
            key
            for key, state in self._identity_state.items()
            if now - float(state.get("last_seen", 0.0)) > 4.0
        ]
        for key in stale_keys:
            self._identity_state.pop(key, None)

    def _remember_identity(
        self,
        box: tuple[int, int, int, int],
        person_id: int | None,
        sim: float | None,
        now: float,
    ) -> None:
        if person_id is None:
            return
        key = self._face_key(box)
        self._identity_state[key] = {
            "person_id": person_id,
            "sim": float(sim or 0.0),
            "box": box,
            "last_seen": now,
        }

    def _recover_recent_identity(
        self,
        box: tuple[int, int, int, int],
        sim: float | None,
        now: float,
    ) -> int | None:
        self._prune_identity_state(now)
        gallery_person_ids = {int(entry["person_id"]) for entry in self._gallery if entry.get("person_id") is not None}
        if len(gallery_person_ids) != 1:
            return None
        if sim is None or sim < max(settings.face_match_threshold - 0.03, 0.54):
            return None
        state = self._identity_state.get(self._face_key(box))
        if state:
            person_id = state.get("person_id")
            return int(person_id) if person_id is not None else None

        x1, y1, x2, y2 = box
        curr_cx = (x1 + x2) / 2
        curr_cy = (y1 + y2) / 2
        curr_size = max(x2 - x1, y2 - y1)
        best_person_id: int | None = None
        best_score = 0.0
        for state in self._identity_state.values():
            prev_box = state.get("box")
            person_id = state.get("person_id")
            if not isinstance(prev_box, tuple) or person_id is None:
                continue
            px1, py1, px2, py2 = prev_box
            prev_cx = (px1 + px2) / 2
            prev_cy = (py1 + py2) / 2
            prev_size = max(px2 - px1, py2 - py1)
            dist = abs(curr_cx - prev_cx) + abs(curr_cy - prev_cy)
            max_dist = max(48.0, max(curr_size, prev_size) * 0.7)
            if dist > max_dist:
                continue
            overlap_x1 = max(x1, px1)
            overlap_y1 = max(y1, py1)
            overlap_x2 = min(x2, px2)
            overlap_y2 = min(y2, py2)
            overlap = max(0, overlap_x2 - overlap_x1) * max(0, overlap_y2 - overlap_y1)
            area = max((x2 - x1) * (y2 - y1), 1)
            iou_like = overlap / area
            score = max(iou_like, 1.0 - min(1.0, dist / max_dist))
            if score > best_score:
                best_score = score
                best_person_id = int(person_id)
        if best_person_id is not None and best_score >= 0.35:
            return best_person_id
        return None

    def _evaluate_face_liveness(
        self,
        frame: np.ndarray,
        box: tuple[int, int, int, int],
        bodies: list[dict] | None,
        now: float,
        track_id: int | None = None,
        recognized: bool = False,
    ) -> dict[str, object]:
        from processor.antispoof import lbp_texture_score, micro_movement_check, predict_face_liveness

        self._prune_liveness_state(now)
        self._prune_identity_state(now)
        crop = self._crop_face(frame, box)
        if crop is None:
            return {"candidate": False, "confirmed": False, "stable_hits": 0}

        x1, y1, x2, y2 = box
        frame_area = max(frame.shape[0] * frame.shape[1], 1)
        face_area_ratio = ((x2 - x1) * (y2 - y1)) / frame_area
        face_min_side = min(x2 - x1, y2 - y1)
        infrared_like = self._is_infrared_like_frame(frame)
        texture_score = lbp_texture_score(crop) if min(crop.shape[:2]) >= 32 else 0.0
        key = self._face_state_key(box, track_id=track_id, now=now)
        prev = self._liveness_state.get(key)
        first_seen = float(prev.get("first_seen", now)) if prev else now
        model_prediction = prev.get("model_prediction") if prev else None
        model_checked_at = float(prev.get("model_checked_at", 0.0)) if prev else 0.0
        should_run_model = (
            settings.antispoof_model_enabled
            and (
                model_prediction is None
                or now - model_checked_at >= self._antispoof_inference_interval
            )
        )
        if should_run_model:
            with self._metrics.measure("antispoof"):
                with gpu_inference_gate.live():
                    model_prediction = predict_face_liveness(frame, box)
            model_checked_at = now
        primary_real_ok = bool(
            model_prediction
            and model_prediction.primary_real_score is not None
            and model_prediction.primary_fake_score is not None
            and model_prediction.primary_real_score >= settings.antispoof_model_real_threshold
            and model_prediction.primary_real_score >= model_prediction.primary_fake_score
        )
        primary_fake_ok = bool(
            model_prediction
            and model_prediction.primary_real_score is not None
            and model_prediction.primary_fake_score is not None
            and model_prediction.primary_fake_score >= settings.antispoof_model_fake_threshold
            and model_prediction.primary_fake_score > model_prediction.primary_real_score
        )
        secondary_real_ok = bool(
            model_prediction
            and model_prediction.secondary_real_score is not None
            and model_prediction.secondary_fake_score is not None
            and model_prediction.secondary_real_score >= settings.antispoof_model_real_threshold
            and model_prediction.secondary_real_score >= model_prediction.secondary_fake_score
        )
        secondary_fake_ok = bool(
            model_prediction
            and model_prediction.secondary_real_score is not None
            and model_prediction.secondary_fake_score is not None
            and model_prediction.secondary_fake_score >= settings.antispoof_model_fake_threshold
            and model_prediction.secondary_fake_score > model_prediction.secondary_real_score
        )
        strong_secondary_real_ok = bool(
            model_prediction
            and model_prediction.secondary_real_score is not None
            and model_prediction.secondary_real_score
            >= max(settings.antispoof_model_real_threshold, 0.90)
        )
        has_ensemble = bool(model_prediction and model_prediction.has_primary and model_prediction.has_secondary)
        model_reliable = face_min_side >= 64








        consensus_real = model_reliable and strong_secondary_real_ok and not infrared_like
        consensus_fake = model_reliable and primary_fake_ok and secondary_fake_ok
        model_disagreement = model_reliable and has_ensemble and not consensus_real and not consensus_fake
        pose_supported = False
        if not bodies:
            body_supported = face_area_ratio >= max(settings.antispoof_small_face_ratio * 0.6, 0.03)
        else:
            pose_supported = self._face_supported_by_pose(box, bodies, strict=False)
            body_supported = pose_supported or self._face_supported_by_body(box, bodies) or face_area_ratio >= 0.2

        gray = cv2.cvtColor(cv2.resize(crop, (96, 96)), cv2.COLOR_BGR2GRAY)
        context = self._crop_context(frame, box)
        context_gray = None
        if context is not None:
            context_gray = cv2.cvtColor(cv2.resize(context, (128, 128)), cv2.COLOR_BGR2GRAY)

        face_motion_ok = False
        context_motion_ok = False
        shift_motion_ok = False
        stable_hits = 1
        if prev:
            prev_gray = prev.get("gray")
            prev_context_gray = prev.get("context_gray")
            prev_box = prev.get("box")
            stable_hits = int(prev.get("stable_hits", 0)) + 1
            if isinstance(prev_gray, np.ndarray):
                face_motion_ok = micro_movement_check(
                    prev_gray,
                    gray,
                    threshold=settings.antispoof_face_motion_threshold,
                    pixel_threshold=20.0,
                    min_active_ratio=settings.antispoof_active_ratio,
                )
            if isinstance(prev_context_gray, np.ndarray) and isinstance(context_gray, np.ndarray):
                context_motion_ok = micro_movement_check(
                    prev_context_gray,
                    context_gray,
                    threshold=settings.antispoof_context_motion_threshold,
                    pixel_threshold=14.0,
                    min_active_ratio=settings.antispoof_active_ratio,
                )
            if isinstance(prev_box, tuple):
                px1, py1, px2, py2 = prev_box
                prev_cx = (px1 + px2) / 2
                prev_cy = (py1 + py2) / 2
                curr_cx = (x1 + x2) / 2
                curr_cy = (y1 + y2) / 2
                shift = abs(curr_cx - prev_cx) + abs(curr_cy - prev_cy)
                shift_motion_ok = shift >= max(8.0, max(x2 - x1, y2 - y1) * 0.08)

        if not recognized and consensus_real:
            unknown_live_anchor = bool(
                face_motion_ok
                and (
                    (pose_supported and body_supported and context_motion_ok)
                    or (context_motion_ok and shift_motion_ok)
                    or (face_area_ratio >= 0.12 and (context_motion_ok or shift_motion_ok))
                )
            )
            if not unknown_live_anchor:
                consensus_real = False
        model_disagreement = model_reliable and has_ensemble and not consensus_real and not consensus_fake

        real_hits = int(prev.get("real_hits", 0)) if prev else 0
        fake_hits = int(prev.get("fake_hits", 0)) if prev else 0
        disagreement_hits = int(prev.get("disagreement_hits", 0)) if prev else 0
        live_until = float(prev.get("live_until", 0.0)) if prev else 0.0
        spoof_until = float(prev.get("spoof_until", 0.0)) if prev else 0.0
        suppressed_until = float(prev.get("suppressed_until", 0.0)) if prev else 0.0






        infrared_live_evidence = bool(
            infrared_like
            and stable_hits >= 2
            and (recognized or body_supported or pose_supported)
            and face_motion_ok
            and (
                context_motion_ok
                or shift_motion_ok
                or face_area_ratio >= 0.12
            )
        )
        recognized_body_live_evidence = bool(
            recognized
            and stable_hits >= 2
            and face_area_ratio >= 0.035
            and (body_supported or pose_supported)
        )
        if consensus_fake and recognized_body_live_evidence:
            consensus_fake = False
            model_disagreement = True

        if consensus_real or infrared_live_evidence or recognized_body_live_evidence:
            real_hits = min(real_hits + 1, 12)
            fake_hits = 0
            disagreement_hits = 0
            spoof_until = 0.0
            suppressed_until = 0.0
            self._forget_spoof_face(box, now)
            if real_hits >= 2:
                live_until = now + self._liveness_live_hold_seconds
        elif consensus_fake:
            fake_hits = min(fake_hits + 1, 12)
            real_hits = max(real_hits - 1, 0)
            disagreement_hits = 0
            if (
                live_until > now
                or recognized
                or body_supported
                or pose_supported
                or face_area_ratio >= 0.08
            ):
                fake_threshold = 10
            elif face_area_ratio >= 0.05:
                fake_threshold = 6
            else:
                fake_threshold = 3
            if fake_hits >= fake_threshold:
                live_until = 0.0
                spoof_until = now + self._spoof_face_ttl
        elif model_disagreement:
            disagreement_hits = min(disagreement_hits + 1, 12)
            fake_hits = 0
            real_hits = max(real_hits - 1, 0)
            if live_until > now and secondary_real_ok:
                live_until = now + self._liveness_live_hold_seconds
                spoof_until = 0.0
                suppressed_until = 0.0
                disagreement_hits = 0
                self._forget_spoof_face(box, now)
            elif (
                face_motion_ok
                and shift_motion_ok
                and secondary_real_ok
                and (recognized or body_supported or pose_supported)
            ):
                live_until = now + self._liveness_live_hold_seconds
                spoof_until = 0.0
                suppressed_until = 0.0
                disagreement_hits = 0
                self._forget_spoof_face(box, now)
            elif (
                live_until <= now
                and not recognized
                and not body_supported
                and not pose_supported
                and not face_motion_ok
                and disagreement_hits >= self._liveness_disagreement_suppress_hits
            ):
                spoof_until = now + self._spoof_face_ttl
        else:
            real_hits = max(real_hits - 1, 0)
            fake_hits = max(fake_hits - 1, 0)
            disagreement_hits = max(disagreement_hits - 1, 0)

        ensemble_unavailable = not has_ensemble
        fallback_live = False
        fallback_spoof = False
        if ensemble_unavailable:
            fallback_live = bool(
                primary_real_ok
                and stable_hits >= 2
                and (recognized or body_supported or pose_supported)
            )
            fallback_spoof = bool(
                primary_fake_ok
                and model_reliable
                and stable_hits >= 4
                and live_until <= now
                and not recognized
                and not body_supported
                and not pose_supported
            )
        elif not model_reliable:



            fallback_live = bool(
                stable_hits >= 2
                and (recognized or body_supported or pose_supported)
                and (
                    strong_secondary_real_ok
                    or (face_motion_ok and shift_motion_ok and (primary_real_ok or secondary_real_ok))
                )
            )
            fallback_spoof = False

        if fallback_live:
            live_until = now + self._liveness_live_hold_seconds
            spoof_until = 0.0
            suppressed_until = 0.0
            self._forget_spoof_face(box, now)
        elif fallback_spoof:
            spoof_until = now + self._spoof_face_ttl

        pending_timeout = max(
            0.8,
            float(getattr(settings, "antispoof_pending_timeout_seconds", 2.8)),
        )
        pending_timed_out = bool(
            live_until <= now
            and spoof_until <= now
            and stable_hits >= 2
            and now - first_seen >= pending_timeout
        )
        if pending_timed_out:
            fake_hits = max(fake_hits, 1)
            real_hits = 0
            live_until = 0.0
            suppressed_until = now + pending_timeout

        confirmed = live_until > now
        spoofed = spoof_until > now and not confirmed
        suppressed = suppressed_until > now and not confirmed and not spoofed
        if spoofed:
            self._remember_spoof_face(box, now)
            if now - self._last_spoof_log_ts >= 5.0:
                logger.info(
                    "Camera %s: suppressed spoof-like face primary=(%s,%s) secondary=(%s,%s) box=%s",
                    self.camera_id,
                    f"{model_prediction.primary_real_score:.3f}"
                    if model_prediction and model_prediction.primary_real_score is not None
                    else "-",
                    f"{model_prediction.primary_fake_score:.3f}"
                    if model_prediction and model_prediction.primary_fake_score is not None
                    else "-",
                    f"{model_prediction.secondary_real_score:.3f}"
                    if model_prediction and model_prediction.secondary_real_score is not None
                    else "-",
                    f"{model_prediction.secondary_fake_score:.3f}"
                    if model_prediction and model_prediction.secondary_fake_score is not None
                    else "-",
                    box,
                )
                self._last_spoof_log_ts = now

        self._liveness_state[key] = {
            "gray": gray,
            "context_gray": context_gray,
            "box": box,
            "track_id": track_id,
            "first_seen": first_seen,
            "stable_hits": stable_hits,
            "real_hits": real_hits,
            "fake_hits": fake_hits,
            "disagreement_hits": disagreement_hits,
            "live_until": live_until,
            "spoof_until": spoof_until,
            "suppressed_until": suppressed_until,
            "model_prediction": model_prediction,
            "model_checked_at": model_checked_at,
            "last_seen": now,
        }

        return {
            "spoof": spoofed,
            "candidate": not spoofed and not suppressed,
            "confirmed": confirmed,
            "state": "live" if confirmed else ("spoof" if spoofed else ("suppressed" if suppressed else "pending")),
            "pending_timed_out": pending_timed_out,
            "stable_hits": stable_hits,
            "consensus_real": consensus_real,
            "consensus_fake": consensus_fake,
            "model_disagreement": model_disagreement,
            "infrared_like": infrared_like,
            "infrared_live_evidence": infrared_live_evidence,
            "face_motion_ok": face_motion_ok,
            "context_motion_ok": context_motion_ok,
            "shift_motion_ok": shift_motion_ok,
            "texture_score": texture_score,
        }

    def _snapshot_bytes_from_box(self, frame: np.ndarray, box: tuple[int, int, int, int]) -> bytes:
        x1, y1, x2, y2 = box
        pad = int(0.2 * max(x2 - x1, y2 - y1))
        h, w = frame.shape[:2]
        xs1, ys1 = max(0, x1 - pad), max(0, y1 - pad)
        xs2, ys2 = min(w, x2 + pad), min(h, y2 + pad)
        crop = frame[ys1:ys2, xs1:xs2] if xs2 > xs1 and ys2 > ys1 else frame
        ok, buf = cv2.imencode(".jpg", crop)
        return buf.tobytes() if ok else b""

    def _store_event_snapshot(self, event_id: int, snapshot: bytes) -> None:
        if not snapshot:
            return
        path = SNAPSHOTS_DIR / f"event_{event_id}.jpg"
        try:
            path.write_bytes(snapshot)
        except Exception:
            logger.exception("Failed to store snapshot for event %s", event_id)

    def _make_flow_reference(self, frame: np.ndarray) -> tuple[np.ndarray, float, float]:
        height, width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        max_side = max(height, width)
        if max_side > self._flow_max_side:
            scale = self._flow_max_side / float(max_side)
            gray = cv2.resize(
                gray,
                (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
                interpolation=cv2.INTER_AREA,
            )
        return gray, width / float(gray.shape[1]), height / float(gray.shape[0])

    def _track_overlay_points(
        self,
        previous: tuple[np.ndarray, float, float],
        current: tuple[np.ndarray, float, float],
        points: list[tuple[float, float]],
        frame_shape: tuple[int, ...],
    ) -> tuple[dict[int, tuple[float, float]], tuple[float, float]] | None:
        if not points:
            return None
        previous_gray, previous_scale_x, previous_scale_y = previous
        current_gray, current_scale_x, current_scale_y = current
        if previous_gray.shape != current_gray.shape:
            return None

        previous_points = np.asarray(
            [
                [float(point[0]) / previous_scale_x, float(point[1]) / previous_scale_y]
                for point in points
            ],
            dtype=np.float32,
        ).reshape(-1, 1, 2)
        next_points, status, errors = cv2.calcOpticalFlowPyrLK(
            previous_gray,
            current_gray,
            previous_points,
            None,
            winSize=(31, 31),
            maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.01),
        )
        if next_points is None or status is None:
            return None

        status_mask = status.reshape(-1).astype(bool)
        error_values = errors.reshape(-1) if errors is not None else np.zeros(len(points), dtype=np.float32)
        tracked: dict[int, tuple[float, float]] = {}
        deltas: list[tuple[float, float]] = []
        frame_height, frame_width = frame_shape[:2]
        for index, ok in enumerate(status_mask):
            if not ok or float(error_values[index]) > 45.0:
                continue
            nx = float(next_points[index, 0, 0]) * current_scale_x
            ny = float(next_points[index, 0, 1]) * current_scale_y
            if not (0.0 <= nx < frame_width and 0.0 <= ny < frame_height):
                continue
            dx = nx - float(points[index][0])
            dy = ny - float(points[index][1])
            if abs(dx) > frame_width * 0.24 or abs(dy) > frame_height * 0.24:
                continue
            tracked[index] = (nx, ny)
            deltas.append((dx, dy))
        if not deltas:
            return None

        delta_array = np.asarray(deltas, dtype=np.float32)
        median_delta = np.median(delta_array, axis=0)
        residuals = np.linalg.norm(delta_array - median_delta, axis=1)
        residual_limit = max(14.0, float(np.median(residuals)) * 3.0)
        accepted_indices = {
            index
            for index, residual in zip(tracked.keys(), residuals, strict=False)
            if float(residual) <= residual_limit
        }
        tracked = {index: point for index, point in tracked.items() if index in accepted_indices}
        if not tracked:
            return None
        accepted_deltas = np.asarray(
            [
                (
                    tracked[index][0] - float(points[index][0]),
                    tracked[index][1] - float(points[index][1]),
                )
                for index in tracked
            ],
            dtype=np.float32,
        )
        dx, dy = np.median(accepted_deltas, axis=0)
        return tracked, (float(dx), float(dy))

    def _shift_overlay_box(
        self,
        box: tuple[int, int, int, int],
        dx: float,
        dy: float,
        frame_shape: tuple[int, ...],
    ) -> tuple[int, int, int, int]:
        height, width = frame_shape[:2]
        x1, y1, x2, y2 = box
        return (
            max(0, min(width, int(round(x1 + dx)))),
            max(0, min(height, int(round(y1 + dy)))),
            max(0, min(width, int(round(x2 + dx)))),
            max(0, min(height, int(round(y2 + dy)))),
        )

    def _flow_box_points(self, box: tuple[int, int, int, int]) -> list[tuple[float, float]]:
        x1, y1, x2, y2 = box
        width = max(x2 - x1, 1)
        height = max(y2 - y1, 1)
        return [
            (x1 + width * fx, y1 + height * fy)
            for fy in (0.22, 0.5, 0.78)
            for fx in (0.22, 0.5, 0.78)
        ]

    def _advance_body_overlay_item(
        self,
        item: dict[str, object],
        previous: tuple[np.ndarray, float, float],
        current: tuple[np.ndarray, float, float],
        frame_shape: tuple[int, ...],
    ) -> dict[str, object] | None:
        box = item.get("box")
        if not isinstance(box, tuple):
            return None

        keypoints = item.get("keypoints")
        confidences = item.get("keypoint_conf")
        source_points: list[tuple[float, float]] = []
        source_keypoint_indices: list[int | None] = []
        drawable = self._body_drawable_keypoints(item, frame_shape)
        if drawable:
            for index, point in drawable.items():
                source_points.append((float(point[0]), float(point[1])))
                source_keypoint_indices.append(index)
        if len(source_points) < 3:
            source_points = self._flow_box_points(box)
            source_keypoint_indices = [None] * len(source_points)

        tracked_result = self._track_overlay_points(previous, current, source_points, frame_shape)
        if tracked_result is None:
            return None
        tracked_points, (dx, dy) = tracked_result
        updated = dict(item)
        updated["box"] = self._shift_overlay_box(box, dx, dy, frame_shape)

        if isinstance(keypoints, list):
            frame_height, frame_width = frame_shape[:2]
            moved_keypoints: list[list[float]] = []
            for point in keypoints:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    moved_keypoints.append(
                        [
                            max(0.0, min(float(frame_width), float(point[0]) + dx)),
                            max(0.0, min(float(frame_height), float(point[1]) + dy)),
                        ]
                    )
                else:
                    moved_keypoints.append([0.0, 0.0])
            for source_index, new_point in tracked_points.items():
                keypoint_index = source_keypoint_indices[source_index]
                if keypoint_index is not None and keypoint_index < len(moved_keypoints):
                    moved_keypoints[keypoint_index] = [float(new_point[0]), float(new_point[1])]
            updated["keypoints"] = moved_keypoints
        return updated

    def _advance_overlay_geometry(self, frame: np.ndarray) -> None:
        now = time.time()
        face_active = bool(self._last_faces_info) and (now - self._last_faces_ts) <= self._face_flow_ttl
        body_active = bool(self._last_body_info) and (now - self._last_body_ts) <= self._body_flow_ttl
        if not face_active and not body_active:
            return

        current_reference = self._make_flow_reference(frame)
        if not self._analysis_lock.acquire(blocking=False):
            return
        try:
            if body_active and self._body_flow_reference is not None:
                updated_bodies: list[dict[str, object]] = []
                moved_body = False
                for item in self._last_body_info:
                    updated = self._advance_body_overlay_item(
                        item,
                        self._body_flow_reference,
                        current_reference,
                        frame.shape,
                    )
                    if updated is None:
                        updated_bodies.append(item)
                        continue
                    if not self._track_has_minimum_upper_pose(updated):
                        updated_bodies.append(item)
                        continue
                    updated_bodies.append(updated)
                    moved_body = True
                    track_id = updated.get("track_id")
                    box = updated.get("box")
                    if isinstance(track_id, int) and isinstance(box, tuple):
                        state = self._body_tracks.get(track_id)
                        if state is not None:
                            state["box"] = box
                            state["tracking_box"] = box
                            state["last_flow_seen"] = now
                if moved_body and updated_bodies:
                    self._last_body_info = updated_bodies
                    self._body_flow_reference = current_reference
                    self._last_body_flow_ts = now

            if face_active and self._face_flow_reference is not None:
                updated_faces: list[tuple[tuple[int, int, int, int], str, bool]] = []
                moved_face = False
                for box, label, recognized in self._last_faces_info:
                    result = self._track_overlay_points(
                        self._face_flow_reference,
                        current_reference,
                        self._flow_box_points(box),
                        frame.shape,
                    )
                    if result is None:
                        updated_faces.append((box, label, recognized))
                        continue
                    _tracked_points, (dx, dy) = result
                    updated_faces.append(
                        (self._shift_overlay_box(box, dx, dy, frame.shape), label, recognized)
                    )
                    moved_face = True
                if moved_face:
                    self._last_faces_info = updated_faces
                    self._face_flow_reference = current_reference
                    self._last_faces_flow_ts = now
        finally:
            self._analysis_lock.release()

    def _draw_overlay(self, frame: np.ndarray, publish_mark: int | None = None) -> np.ndarray:
        now = time.time()
        face_overlay_active, body_overlay_active = self._overlay_active_flags(now)
        if not face_overlay_active and not body_overlay_active:
            return frame
        annotated = frame.copy()
        pil_image = Image.fromarray(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_image)
        font = _load_overlay_font(max(18, frame.shape[1] // 55))
        active_body_boxes: list[tuple[int, int, int, int]] = []
        if body_overlay_active:
            for item in self._last_body_info:
                box = item.get("box")
                label = str(item.get("label") or "")
                recognized = bool(item.get("recognized"))
                keypoints = item.get("keypoints")
                keypoint_conf = item.get("keypoint_conf")
                if not isinstance(box, tuple):
                    continue
                if not self._track_has_minimum_upper_pose(item):
                    continue
                x1, y1, x2, y2 = box
                rgb_color = (0, 215, 70)
                drawable_keypoints = self._body_drawable_keypoints(item, frame.shape)
                if drawable_keypoints:
                    active_body_boxes.append(box)
                    for a_idx, b_idx in _POSE_SKELETON_EDGES:
                        a_point = drawable_keypoints.get(a_idx)
                        b_point = drawable_keypoints.get(b_idx)
                        if a_point is None or b_point is None:
                            continue
                        edge_len = float(np.hypot(a_point[0] - b_point[0], a_point[1] - b_point[1]))
                        edge_limit = max(
                            80.0,
                            float(x2 - x1) * (0.95 if max(a_idx, b_idx) <= 10 else 1.15),
                            float(y2 - y1) * (0.42 if max(a_idx, b_idx) <= 10 else 0.55),
                        )
                        if edge_len > edge_limit:
                            continue
                        draw.line((a_point[0], a_point[1], b_point[0], b_point[1]), fill=rgb_color, width=3)
                    for px, py in drawable_keypoints.values():
                        draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=rgb_color)
                elif isinstance(keypoints, list) and len(keypoints) >= 17:
                    continue
                else:
                    active_body_boxes.append(box)
                    draw.rectangle((x1, y1, x2, y2), outline=rgb_color, width=2)
                body_label = label
                text_pos = self._body_label_position(box, keypoints, keypoint_conf)
                try:
                    bbox = draw.textbbox(text_pos, body_label, font=font)
                    draw.rectangle((bbox[0] - 4, bbox[1] - 2, bbox[2] + 4, bbox[3] + 2), fill=(0, 0, 0))
                except Exception:
                    pass
                draw.text(text_pos, body_label, font=font, fill=rgb_color)
        if face_overlay_active:
            for (x1, y1, x2, y2), label, recognized in self._last_faces_info:
                if recognized:
                    color = (0, 200, 0)
                elif label == "Подмена":
                    color = (0, 0, 220)
                elif label == "Проверка":
                    color = (0, 190, 255)
                else:
                    color = (220, 190, 0)
                rgb_color = (color[2], color[1], color[0])
                draw.rectangle((x1, y1, x2, y2), outline=rgb_color, width=2)
                face_cx = (x1 + x2) / 2
                face_cy = (y1 + y2) / 2
                suppress_face_label = False
                if recognized:
                    for bx1, by1, bx2, by2 in active_body_boxes:
                        if bx1 <= face_cx <= bx2 and by1 <= face_cy <= by1 + (by2 - by1) * 0.5:
                            suppress_face_label = True
                            break
                text_pos = (x1, max(y1 - 28, 6))
                try:
                    if not suppress_face_label:
                        bbox = draw.textbbox(text_pos, label, font=font)
                        draw.rectangle(
                            (bbox[0] - 4, bbox[1] - 2, bbox[2] + 4, bbox[3] + 2),
                            fill=(0, 0, 0),
                        )
                except Exception:
                    pass
                if not suppress_face_label:
                    draw.text(text_pos, label, font=font, fill=rgb_color)

        if publish_mark:
            self._last_overlay_refresh_mark = int(publish_mark)

        if self._last_overlay_refresh_mark:
            active_ts = max(
                self._last_faces_ts if face_overlay_active else 0.0,
                self._last_body_ts if body_overlay_active else 0.0,
            )
            age_ms = int(max(0.0, now - active_ts) * 1000) if active_ts > 0.0 else 0
            debug_text = (
                f"OVR /{self._overlay_frame_divisor} | "
                f"SCN /{self._face_scan_divisor} | {age_ms} ms"
            )
            debug_pos = (max(8, frame.shape[1] - 210), 8)
            try:
                bbox = draw.textbbox(debug_pos, debug_text, font=font)
                draw.rectangle(
                    (bbox[0] - 4, bbox[1] - 2, bbox[2] + 4, bbox[3] + 2),
                    fill=(0, 0, 0),
                )
            except Exception:
                pass
            draw.text(debug_pos, debug_text, font=font, fill=(64, 220, 255))
        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

    def _publish_live_frames(self, frame: np.ndarray, publish_mark: int = 0) -> None:
        put_latest(self._publish_queue, (frame, publish_mark))

    def _start_publish_thread(self) -> None:
        if self._publish_thread and self._publish_thread.is_alive():
            return
        self._publish_stop.clear()
        drain(self._publish_queue)
        self._publish_thread = threading.Thread(
            target=self._publish_loop,
            name=f"camera-{self.camera_id}-publisher",
            daemon=True,
        )
        self._publish_thread.start()

    def _stop_publish_thread(self) -> None:
        self._publish_stop.set()
        put_latest(self._publish_queue, None)
        if self._publish_thread and self._publish_thread.is_alive():
            self._publish_thread.join(timeout=3)
            if self._publish_thread.is_alive():
                logger.warning(
                    "Camera %s: publish thread did not stop in time",
                    self.camera_id,
                )
        self._publish_thread = None

    def _publish_loop(self) -> None:
        encode_opts = [int(cv2.IMWRITE_JPEG_QUALITY), 82]
        while not self._publish_stop.is_set():
            try:
                payload = self._publish_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if payload is None:
                    break
                frame, publish_mark = payload
                now = time.time()
                face_overlay_active, body_overlay_active = self._overlay_active_flags(now)
                overlay_active = face_overlay_active or body_overlay_active
                if overlay_active:
                    self._queue_overlay_frame(frame, publish_mark)

                with self._metrics.measure("raw_jpeg"):
                    raw_ok, raw_buf = cv2.imencode(".jpg", frame, encode_opts)
                raw_bytes = raw_buf.tobytes() if raw_ok else None
                if raw_bytes is not None:
                    with self._frame_ready:
                        self._latest_raw_jpeg = raw_bytes
                        self._stream_frame_sequence += 1
                        self._raw_frame_sequence = self._stream_frame_sequence
                        self._frame_ready.notify_all()

                if not overlay_active and raw_bytes is not None:
                    overlay_stale = (
                        time.monotonic() - self._last_overlay_render_ts
                    ) > max(0.22, self._overlay_render_interval * 2.5)
                    with self._frame_ready:
                        if overlay_stale or self._latest_overlay_jpeg is None:
                            self._latest_overlay_jpeg = raw_bytes
                            self._stream_frame_sequence += 1
                            self._overlay_frame_sequence = self._stream_frame_sequence
                            self._frame_ready.notify_all()
            finally:
                self._publish_queue.task_done()

    def _start_overlay_thread(self) -> None:
        if self._overlay_thread and self._overlay_thread.is_alive():
            return
        self._overlay_stop.clear()
        while True:
            try:
                self._overlay_queue.get_nowait()
                self._overlay_queue.task_done()
            except queue.Empty:
                break
        self._overlay_thread = threading.Thread(
            target=self._overlay_loop,
            name=f"camera-{self.camera_id}-overlay",
            daemon=True,
        )
        self._overlay_thread.start()

    def _stop_overlay_thread(self) -> None:
        self._overlay_stop.set()
        try:
            self._overlay_queue.put_nowait(None)
        except queue.Full:
            try:
                self._overlay_queue.get_nowait()
                self._overlay_queue.task_done()
            except queue.Empty:
                pass
            try:
                self._overlay_queue.put_nowait(None)
            except queue.Full:
                pass
        if self._overlay_thread and self._overlay_thread.is_alive():
            self._overlay_thread.join(timeout=2)
            if self._overlay_thread.is_alive():
                logger.warning("Camera %s: overlay thread did not stop in time", self.camera_id)
        self._overlay_thread = None

    def _queue_overlay_frame(self, frame: np.ndarray, publish_mark: int) -> None:
        payload = (frame, publish_mark)
        try:
            self._overlay_queue.put_nowait(payload)
            return
        except queue.Full:
            pass
        try:
            self._overlay_queue.get_nowait()
            self._overlay_queue.task_done()
        except queue.Empty:
            pass
        try:
            self._overlay_queue.put_nowait(payload)
        except queue.Full:
            pass

    def _overlay_loop(self) -> None:
        encode_opts = [int(cv2.IMWRITE_JPEG_QUALITY), 82]
        try:
            while not self._overlay_stop.is_set():
                try:
                    payload = self._overlay_queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    if payload is None:
                        break
                    frame, publish_mark = payload
                    self._advance_overlay_geometry(frame)
                    with self._metrics.measure("overlay_draw"):
                        overlay_frame = self._draw_overlay(
                            frame,
                            publish_mark=publish_mark,
                        )
                    with self._metrics.measure("overlay_jpeg"):
                        overlay_ok, overlay_buf = cv2.imencode(
                            ".jpg",
                            overlay_frame,
                            encode_opts,
                        )
                    if overlay_ok:
                        with self._frame_ready:
                            self._latest_overlay_jpeg = overlay_buf.tobytes()
                            self._stream_frame_sequence += 1
                            self._overlay_frame_sequence = self._stream_frame_sequence
                            self._frame_ready.notify_all()
                        self._last_overlay_render_ts = time.monotonic()
                finally:
                    self._overlay_queue.task_done()
        except Exception:
            logger.exception("Overlay thread failed for camera %s", self.camera_id)

    def _start_recording_thread(self) -> None:
        if self._record_thread and self._record_thread.is_alive():
            return
        self._record_stop.clear()
        while True:
            try:
                self._record_queue.get_nowait()
                self._record_queue.task_done()
            except queue.Empty:
                break
        self._record_thread = threading.Thread(
            target=self._record_loop,
            name=f"camera-{self.camera_id}-recorder",
            daemon=True,
        )
        self._record_thread.start()

    def _stop_recording_thread(self) -> None:
        self._record_stop.set()
        try:
            self._record_queue.put_nowait(None)
        except queue.Full:
            try:
                self._record_queue.get_nowait()
                self._record_queue.task_done()
            except queue.Empty:
                pass
            try:
                self._record_queue.put_nowait(None)
            except queue.Full:
                pass
        if self._record_thread and self._record_thread.is_alive():
            self._record_thread.join(timeout=5)
            if self._record_thread.is_alive():
                logger.warning("Camera %s: recording thread did not stop in time", self.camera_id)
        self._record_thread = None

    def _record_loop(self) -> None:
        try:
            while True:
                try:
                    frame = self._record_queue.get(timeout=0.2)
                except queue.Empty:
                    if self._record_stop.is_set():
                        break
                    continue
                try:
                    if frame is None:
                        self._finalize_recording()
                        if self._record_stop.is_set():
                            break
                        continue
                    if not self._should_record():
                        self._finalize_recording()
                        continue
                    self._ensure_writer(frame.shape[1], frame.shape[0])
                    if self._writer is not None:
                        with self._metrics.measure("record_write"):
                            self._writer.write(frame)
                finally:
                    self._record_queue.task_done()
        except Exception:
            logger.exception("Recording thread failed for camera %s", self.camera_id)
        finally:
            self._finalize_recording()

    def _should_record(self) -> bool:
        mode = self.assignment.get("recording_mode") or "continuous"
        if mode == "continuous":
            return True
        if mode == "event":
            return (time.time() - self._last_activity_ts) <= self._record_event_tail_seconds
        return False

    def _record_frame(self, frame: np.ndarray, motion: bool) -> None:
        if motion:
            self._last_activity_ts = max(self._last_activity_ts, time.time())
        if not self._should_record():
            try:
                self._record_queue.put_nowait(None)
            except queue.Full:
                pass
            return
        now = time.monotonic()
        if (
            self._last_record_enqueue_monotonic
            and now - self._last_record_enqueue_monotonic
            < self._record_enqueue_interval
        ):
            return
        self._last_record_enqueue_monotonic = now
        put_latest(self._record_queue, frame)

    def _ensure_writer(self, width: int, height: int) -> None:
        frame_size = (width, height)
        rotate = False
        if self._writer is None:
            rotate = True
        elif self._writer_frame_size != frame_size:
            rotate = True
        elif (time.monotonic() - self._writer_started_monotonic) >= settings.recording_segment_seconds:
            rotate = True

        if rotate:
            self._finalize_recording()
            min_free_bytes = int(getattr(settings, "recording_min_free_bytes", 536_870_912))
            if not _recording_has_free_space(RECORDINGS_DIR, min_free_bytes):
                now = time.monotonic()
                if now - self._last_low_disk_log_monotonic >= 60.0:
                    logger.error(
                        "Camera %s: recording paused because free disk space is below %s bytes",
                        self.camera_id,
                        min_free_bytes,
                    )
                    self._last_low_disk_log_monotonic = now
                return
            rel_path, abs_path = self._new_recording_path()
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(
                str(abs_path),
                fourcc,
                self._record_target_fps,
                frame_size,
            )
            if not writer.isOpened():
                logger.error("Cannot start recording writer for camera %s path=%s", self.camera_id, abs_path)
                return
            self._writer = writer
            self._writer_path = abs_path
            self._writer_relative_path = rel_path
            self._writer_frame_size = frame_size
            self._writer_started_monotonic = time.monotonic()
            self._writer_started_dt = datetime.now()

    def _new_recording_path(self) -> tuple[str, Path]:
        now = datetime.now()
        folder = RECORDINGS_DIR / now.strftime("%Y-%m-%d") / now.strftime("%H")
        folder.mkdir(parents=True, exist_ok=True)
        name = f"cam{self.camera_id}_{now.strftime('%Y%m%d_%H%M%S')}.mp4"
        path = folder / name
        relative = path.relative_to(RECORDINGS_DIR).as_posix()
        return relative, path

    def _maybe_cleanup_recordings(self) -> None:
        retention_days = int(getattr(settings, "recording_retention_days", 0))
        retention_max_bytes = int(getattr(settings, "recording_retention_max_bytes", 0))
        if retention_days <= 0 and retention_max_bytes <= 0:
            return
        now = time.monotonic()
        if now - self._recording_cleanup_last_monotonic < self._recording_cleanup_interval:
            return
        self._recording_cleanup_last_monotonic = now
        try:
            self._cleanup_recordings(retention_days=retention_days, max_bytes=retention_max_bytes)
        except Exception:
            logger.exception("Camera %s: recording cleanup failed", self.camera_id)

    def _cleanup_recordings(self, *, retention_days: int, max_bytes: int) -> None:
        root = RECORDINGS_DIR.resolve()
        if not root.exists():
            return
        now_wall = time.time()
        cutoff = now_wall - (retention_days * 86400) if retention_days > 0 else None
        files: list[tuple[Path, float, int]] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".avi", ".mkv", ".mp4"}:
                continue
            try:
                resolved = path.resolve()
                if root not in resolved.parents:
                    continue
                stat = resolved.stat()
            except OSError:
                continue
            if cutoff is not None and stat.st_mtime < cutoff:
                self._delete_recording_file(resolved)
                continue
            files.append((resolved, stat.st_mtime, int(stat.st_size)))

        if max_bytes <= 0:
            return
        total_bytes = sum(size for _path, _mtime, size in files)
        if total_bytes <= max_bytes:
            return
        for path, _mtime, size in sorted(files, key=lambda item: item[1]):
            if total_bytes <= max_bytes:
                break
            if self._delete_recording_file(path):
                total_bytes -= size

    def _delete_recording_file(self, path: Path) -> bool:
        try:
            path.unlink(missing_ok=True)
            logger.info("Deleted local recording by retention policy path=%s", path)
            return True
        except OSError:
            logger.exception("Failed to delete local recording by retention policy path=%s", path)
            return False

    def _rotate_recording_if_needed(self, width: int, height: int) -> None:
        if self._writer is None:
            return
        if self._writer_frame_size != (width, height):
            self._ensure_writer(width, height)
            return
        if (time.monotonic() - self._writer_started_monotonic) >= settings.recording_segment_seconds:
            self._ensure_writer(width, height)

    def _finalize_recording(self) -> None:
        if self._writer is None or self._writer_path is None or self._writer_relative_path is None:
            self._writer = None
            self._writer_path = None
            self._writer_relative_path = None
            self._writer_frame_size = None
            self._writer_started_dt = None
            self._writer_started_monotonic = 0.0
            return

        writer = self._writer
        path = self._writer_path
        relative_path = self._writer_relative_path
        started_dt = self._writer_started_dt or datetime.now()

        self._writer = None
        self._writer_path = None
        self._writer_relative_path = None
        self._writer_frame_size = None
        self._writer_started_dt = None
        self._writer_started_monotonic = 0.0

        writer.release()
        if not path.exists():
            return

        size = path.stat().st_size
        if size <= 0:
            return

        ended_dt = datetime.now()
        duration = max((ended_dt - started_dt).total_seconds(), 0.0)
        payload = {
            "camera_id": self.camera_id,
            "file_path": f"processor://{self.processor_id}/{relative_path}",
            "file_kind": "video",
            "started_at": started_dt.isoformat(),
            "ended_at": ended_dt.isoformat(),
            "duration_seconds": round(duration, 3),
            "file_size_bytes": size,
        }
        self._push_recording(payload, local_path=path)
        logger.info("Recording saved camera=%s path=%s size=%s", self.camera_id, relative_path, size)
        self._maybe_cleanup_recordings()

    def _dispatch_future(self, future: asyncio.Future, action: str, on_success=None) -> None:
        def _done(done_future):
            try:
                result = done_future.result()
                if on_success is not None:
                    on_success(result)
            except Exception:
                logger.exception("Failed to %s for camera %s", action, self.camera_id)

        future.add_done_callback(_done)

    def _start_event_thread(self) -> None:
        if self._event_thread and self._event_thread.is_alive():
            return
        self._event_stop.clear()
        drain(self._event_queue)
        self._event_thread = threading.Thread(
            target=self._event_loop_worker,
            name=f"camera-{self.camera_id}-events",
            daemon=True,
        )
        self._event_thread.start()

    def _stop_event_thread(self) -> None:
        self._event_stop.set()
        put_latest(self._event_queue, None)
        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=3)
            if self._event_thread.is_alive():
                logger.warning(
                    "Camera %s: event thread did not stop in time",
                    self.camera_id,
                )
        self._event_thread = None

    def _queue_event(
        self,
        event: dict,
        *,
        frame: np.ndarray | None = None,
        box: tuple[int, int, int, int] | None = None,
    ) -> None:
        frame_copy = frame.copy() if frame is not None and box is not None else None
        put_latest(self._event_queue, (event, frame_copy, box))

    def _event_loop_worker(self) -> None:
        while not self._event_stop.is_set():
            try:
                payload = self._event_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if payload is None:
                    break
                event, frame, box = payload
                snapshot = None
                if frame is not None and box is not None:
                    with self._metrics.measure("event_snapshot"):
                        snapshot = self._snapshot_bytes_from_box(frame, box)
                    if snapshot:
                        event = {
                            **event,
                            "snapshot_b64": base64.b64encode(snapshot).decode("ascii"),
                        }
                with self._metrics.measure("event_schedule"):
                    self._dispatch_event(event, local_snapshot=snapshot)
            except Exception:
                logger.exception(
                    "Failed to prepare event for camera %s",
                    self.camera_id,
                )
            finally:
                self._event_queue.task_done()

    def _dispatch_event(self, event: dict, local_snapshot: bytes | None = None) -> None:
        if self._event_loop is None or self.processor_id is None:
            return
        future = asyncio.run_coroutine_threadsafe(
            self.client.push_event(self.processor_id, event),
            self._event_loop,
        )
        self._dispatch_future(
            future,
            "push event",
            on_success=(
                (lambda result: self._store_event_snapshot(int(result.get("event_id")), local_snapshot))
                if local_snapshot
                else None
            ),
        )

    async def _send_recording(self, recording: dict, local_path: Path | None = None) -> dict:
        if self.processor_id is None:
            raise RuntimeError("processor_id is not initialized")
        if local_path is not None and local_path.exists():
            try:
                return await self.client.upload_recording(self.processor_id, recording, local_path)
            except Exception:
                logger.exception(
                    "Failed to upload recording for camera %s; falling back to metadata registration",
                    self.camera_id,
                )
        return await self.client.push_recording(self.processor_id, recording)

    def _schedule_recording_uploads_locked(self) -> None:
        if self._event_loop is None or self.processor_id is None:
            return
        while self._recording_upload_inflight < self._recording_upload_concurrency:
            try:
                recording, local_path = self._recording_upload_pending.get_nowait()
            except queue.Empty:
                return
            self._recording_upload_inflight += 1
            future = asyncio.run_coroutine_threadsafe(
                self._send_recording(recording, local_path),
                self._event_loop,
            )
            future.add_done_callback(self._recording_upload_done)

    def _recording_upload_done(self, done_future) -> None:
        try:
            done_future.result()
        except Exception:
            logger.exception("Failed to push recording for camera %s", self.camera_id)
        finally:
            with self._recording_upload_lock:
                self._recording_upload_inflight = max(0, self._recording_upload_inflight - 1)
                try:
                    self._recording_upload_pending.task_done()
                except ValueError:
                    pass
                self._schedule_recording_uploads_locked()

    def _push_recording(self, recording: dict, local_path: Path | None = None) -> dict | None:
        if self._event_loop is None or self.processor_id is None:
            return None

        with self._recording_upload_lock:
            if self._recording_upload_pending.full():
                try:
                    dropped, _dropped_path = self._recording_upload_pending.get_nowait()
                    self._recording_upload_pending.task_done()
                    logger.warning(
                        "Camera %s: recording upload queue is full; dropped oldest metadata path=%s",
                        self.camera_id,
                        dropped.get("file_path"),
                    )
                except queue.Empty:
                    pass
            try:
                self._recording_upload_pending.put_nowait((recording, local_path))
            except queue.Full:
                logger.error(
                    "Camera %s: recording upload queue is still full; skipped metadata path=%s",
                    self.camera_id,
                    recording.get("file_path"),
                )
                return None
            self._schedule_recording_uploads_locked()
        return None
