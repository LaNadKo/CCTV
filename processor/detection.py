"""Camera worker: frame reading, motion detection, face scanning, media serving and recording."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from processor.config import settings
from processor.paths import RECORDINGS_DIR, SNAPSHOTS_DIR, ensure_media_dirs

logger = logging.getLogger(__name__)
_PROCESSING_BASE_FPS = 24.0
_MAX_FRAME_INTERVAL_SECONDS = 5.0
_FRAME_DIVISOR_CHOICES = (1, 2, 4, 8, 16, 32, 64, 120)

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
                raw_scan_divisor = 8
        self._face_scan_divisor = self._sanitize_frame_divisor(raw_scan_divisor, fallback=8)
        self._overlay_frame_divisor = self._sanitize_frame_divisor(
            getattr(settings, "overlay_frame_divisor", 1),
            fallback=1,
        )
        self._target_scan_interval = self._frame_divisor_to_interval(self._face_scan_divisor)
        self._last_event: dict[int | None, float] = {}
        self._event_dedup_seconds = 10.0
        self._overlay_ttl = max(self._target_scan_interval + 1.0, 3.0)
        self._record_event_tail_seconds = 10.0
        self._live_publish_interval = self._frame_divisor_to_interval(self._overlay_frame_divisor)
        self._last_publish_ts = 0.0
        self._publish_frame_counter = 0
        self._last_overlay_refresh_mark = 0

        self._last_faces_info: list[tuple[tuple[int, int, int, int], str, bool]] = []
        self._last_faces_ts = 0.0
        self._last_body_info: list[dict[str, object]] = []
        self._last_body_ts = 0.0
        self._last_activity_ts = 0.0
        self._last_motion_ts = 0.0
        self._liveness_state: dict[str, dict[str, object]] = {}
        self._identity_state: dict[str, dict[str, object]] = {}
        self._body_tracks: dict[int, dict[str, object]] = {}
        self._next_body_track_id = 1
        self._body_support_cache: list[dict] | None = None
        self._body_support_ts = 0.0
        self._body_support_interval = max(0.08, min(0.6, self._target_scan_interval * 0.8))
        self._body_max_side = 800

        self._capture_lock = threading.Lock()
        self._capture_ready = threading.Event()
        self._capture_frame: np.ndarray | None = None
        self._capture_seq = 0
        self._capture_thread: threading.Thread | None = None
        self._scan_lock = threading.Lock()
        self._scan_inflight = False
        self._scan_max_side = 960

        self._frame_lock = threading.Lock()
        self._latest_raw_jpeg: bytes | None = None
        self._latest_overlay_jpeg: bytes | None = None

        self._writer: cv2.VideoWriter | None = None
        self._writer_path: Path | None = None
        self._writer_relative_path: str | None = None
        self._writer_started_monotonic = 0.0
        self._writer_started_dt: datetime | None = None
        self._writer_frame_size: tuple[int, int] | None = None

        ensure_media_dirs()

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

    def _frame_divisor_to_interval(self, divisor: int) -> float:
        return min(_MAX_FRAME_INTERVAL_SECONDS, divisor / _PROCESSING_BASE_FPS)

    async def set_gallery(self, gallery: list[dict]):
        self._gallery = gallery

    async def start(self, processor_id: int):
        self.processor_id = processor_id
        self._running = True
        self._event_loop = asyncio.get_event_loop()
        await asyncio.to_thread(self._run_loop)

    def stop(self):
        self._running = False

    def get_stream_frame(self, overlay: bool = True) -> bytes | None:
        with self._frame_lock:
            if overlay and self._latest_overlay_jpeg:
                return self._latest_overlay_jpeg
            return self._latest_raw_jpeg

    def _run_loop(self):
        cap = self._open_capture()
        if not cap.isOpened():
            logger.error("Cannot open camera %s source=%s", self.camera_id, self.source)
            return
        last_face_scan = 0.0
        last_processed_seq = 0
        self._capture_ready.clear()
        self._capture_thread = threading.Thread(target=self._capture_loop, args=(cap,), daemon=True)
        self._capture_thread.start()
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
                    if self._try_start_scan():
                        last_face_scan = now
                        scan_frame = frame.copy()
                        threading.Thread(
                            target=self._scan_faces_guarded,
                            args=(scan_frame,),
                            daemon=True,
                        ).start()

                if should_publish:
                    self._publish_live_frames(frame, publish_mark=publish_mark)
                    self._last_publish_ts = now
                self._record_frame(frame, motion)
                self._rotate_recording_if_needed(frame.shape[1], frame.shape[0])
        finally:
            self._running = False
            if self._capture_thread and self._capture_thread.is_alive():
                self._capture_thread.join(timeout=2)
            self._capture_thread = None
            self._capture_ready.clear()
            with self._capture_lock:
                self._capture_frame = None
                self._capture_seq = 0
            self._finalize_recording()
            cap.release()

    def _capture_loop(self, cap: cv2.VideoCapture) -> None:
        while self._running:
            ok = cap.grab()
            if not ok:
                time.sleep(0.05)
                continue
            ok, frame = cap.retrieve()
            if not ok or frame is None:
                time.sleep(0.01)
                continue
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

    def _open_capture(self) -> cv2.VideoCapture:
        source = self.source
        if isinstance(source, str) and source.lower().startswith("rtsp://"):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0|buffer_size;102400"
            )
            cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        else:
            cap = cv2.VideoCapture(source)

        for prop, value in (
            (getattr(cv2, "CAP_PROP_BUFFERSIZE", None), 1),
            (getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None), 5000),
            (getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None), 5000),
        ):
            if prop is None:
                continue
            try:
                cap.set(prop, value)
            except Exception:
                pass
        return cap

    def _detect_motion(self, frame: np.ndarray) -> bool:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        motion = False
        if self._prev_gray is not None:
            delta = cv2.absdiff(self._prev_gray, gray)
            thresh = cv2.threshold(delta, settings.motion_threshold, 255, cv2.THRESH_BINARY)[1]
            thresh = cv2.dilate(thresh, None, iterations=2)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                if cv2.contourArea(contour) >= settings.motion_min_area:
                    motion = True
                    break
        self._prev_gray = gray
        return motion

    def _scan_faces(self, frame: np.ndarray):
        try:
            from processor.vision import detect_faces, match_embedding

            scan_frame, scale_x, scale_y = self._prepare_scan_frame(frame)
            rgb = cv2.cvtColor(scan_frame, cv2.COLOR_BGR2RGB)
            faces = detect_faces(rgb)
            now = time.time()
            overlay_items: list[tuple[tuple[int, int, int, int], str, bool]] = []
            want_body_support = bool(faces) or (now - self._last_faces_ts) <= self._overlay_ttl or (now - self._last_motion_ts) <= 1.2
            bodies = self._get_body_support(frame, now) if want_body_support else []
            body_tracks = self._update_body_tracks(bodies, now)

            for face in faces:
                box = self._rescale_box(face["box"], frame.shape[1], frame.shape[0], scale_x, scale_y)
                track_id = self._find_body_track_for_face(box, body_tracks)
                person_id, sim = match_embedding(face["embedding"], self._gallery)
                if person_id is None:
                    if track_id is not None:
                        person_id = self._recover_track_identity(track_id, sim, now)
                if person_id is None:
                    person_id = self._recover_recent_identity(box, sim, now)
                recognized = person_id is not None
                label = self._label_for_person(person_id) if recognized else "Неизвестно"
                if not self._is_live_face(frame, box, bodies, now, strict_unknown=not recognized):
                    logger.debug("Camera %s: suppressed non-live/spoof-like face %s", self.camera_id, box)
                    continue
                if recognized:
                    self._remember_identity(box, person_id, sim, now)
                    if track_id is not None:
                        self._remember_track_identity(track_id, person_id, label, now)
                if not recognized:
                    recent_motion = (time.time() - self._last_motion_ts) <= settings.unknown_face_requires_motion_seconds
                    if not recent_motion and track_id is not None:
                        track_state = self._body_tracks.get(track_id)
                        recent_motion = bool(
                            track_state
                            and int(track_state.get("hits", 0)) >= 2
                            and self._track_has_pose_support(track_state, strict=True)
                        )
                    if not recent_motion and bodies and self._face_supported_by_pose(box, bodies, strict=True):
                        recent_motion = True
                    if not recent_motion:
                        logger.debug(
                            "Camera %s: suppressed unknown face without recent scene motion box=%s",
                            self.camera_id,
                            box,
                        )
                        continue
                overlay_items.append((box, label, recognized))
                event_type = "face_recognized" if recognized else "face_unknown"

                dedup_key = person_id
                last_ts = self._last_event.get(dedup_key, 0)
                if now - last_ts < self._event_dedup_seconds:
                    continue
                self._last_event[dedup_key] = now
                self._last_activity_ts = now

                logger.info(
                    "Camera %s: %s person=%s sim=%.3f",
                    self.camera_id, event_type, person_id, sim,
                )

                snapshot_b64 = None
                if not recognized:
                    snapshot = self._snapshot_bytes_from_box(frame, box)
                    if snapshot:
                        snapshot_b64 = base64.b64encode(snapshot).decode("ascii")

                payload = {
                    "event_type": event_type,
                    "camera_id": self.camera_id,
                    "person_id": person_id,
                    "confidence": self._similarity_to_confidence(sim, recognized),
                    "snapshot_b64": snapshot_b64,
                    "event_ts": datetime.now().isoformat(),
                }
                self._dispatch_event(payload, local_snapshot=snapshot if snapshot_b64 else None)

            body_overlay_items = self._build_body_overlay_items(body_tracks, now)
            if overlay_items:
                self._last_faces_info = overlay_items
                self._last_faces_ts = now
            elif now - self._last_faces_ts > self._overlay_ttl:
                self._last_faces_info = []
            if body_overlay_items:
                self._last_body_info = body_overlay_items
                self._last_body_ts = now
            elif now - self._last_body_ts > max(self._overlay_ttl, 4.0):
                self._last_body_info = []
        except Exception:
            logger.exception("Face scan error on camera %s", self.camera_id)

    def _try_start_scan(self) -> bool:
        with self._scan_lock:
            if self._scan_inflight:
                return False
            self._scan_inflight = True
            return True

    def _scan_faces_guarded(self, frame: np.ndarray) -> None:
        try:
            self._scan_faces(frame)
        finally:
            with self._scan_lock:
                self._scan_inflight = False

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
        if self._body_support_cache is not None and (now - self._body_support_ts) < self._body_support_interval:
            return self._body_support_cache

        try:
            from processor.body_detector import detect_bodies

            body_frame, scale_x, scale_y = self._prepare_body_frame(frame)
            detected = detect_bodies(body_frame, conf=0.28)
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
                    payload["keypoints"] = [
                        [float(point[0]) * scale_x, float(point[1]) * scale_y]
                        for point in keypoints
                        if isinstance(point, list) or isinstance(point, tuple)
                    ]
                keypoint_conf = body.get("keypoint_conf")
                if isinstance(keypoint_conf, list):
                    payload["keypoint_conf"] = [float(value) for value in keypoint_conf]
                self._apply_body_pose_metadata(payload, frame.shape[1], frame.shape[0])
                bodies.append(payload)
        except Exception:
            logger.exception("Body support scan failed on camera %s", self.camera_id)
            bodies = []

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

    def _body_track_match_score(self, body: dict[str, object], state: dict[str, object]) -> float:
        body_box = body.get("tracking_box")
        if not isinstance(body_box, tuple):
            body_box = body.get("box")
        state_box = state.get("tracking_box")
        if not isinstance(state_box, tuple):
            state_box = state.get("box")
        if not isinstance(body_box, tuple) or not isinstance(state_box, tuple):
            return 0.0

        iou_score = self._box_iou(body_box, state_box)
        anchor_score = 0.0
        body_anchor = self._body_anchor(body)
        state_anchor = self._body_anchor(state)
        if body_anchor and state_anchor:
            dist = abs(body_anchor[0] - state_anchor[0]) + abs(body_anchor[1] - state_anchor[1])
            max_side = max(body_box[2] - body_box[0], body_box[3] - body_box[1], state_box[2] - state_box[0], state_box[3] - state_box[1], 1)
            max_dist = max(32.0, max_side * 0.9)
            anchor_score = 1.0 - min(1.0, dist / max_dist)
        if iou_score >= 0.18:
            return max(iou_score, (iou_score * 0.72) + (anchor_score * 0.28))
        return max(iou_score, anchor_score * 0.88)

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

    def _update_body_tracks(self, bodies: list[dict], now: float) -> list[dict]:
        stale_track_ids = [
            track_id
            for track_id, state in self._body_tracks.items()
            if now - float(state.get("last_seen", 0.0)) > 3.5
        ]
        for track_id in stale_track_ids:
            self._body_tracks.pop(track_id, None)

        unmatched_track_ids = set(self._body_tracks.keys())
        for body in bodies:
            box = tuple(int(round(v)) for v in body["box"])
            tracking_box = body.get("tracking_box")
            if not isinstance(tracking_box, tuple):
                tracking_box = box
            best_track_id: int | None = None
            best_score = 0.0
            for track_id in list(unmatched_track_ids):
                state = self._body_tracks.get(track_id)
                if not state:
                    continue
                score = self._body_track_match_score(body, state)
                if score > best_score:
                    best_score = score
                    best_track_id = track_id
            if best_track_id is not None and best_score >= 0.16:
                state = self._body_tracks[best_track_id]
                state["box"] = box
                state["tracking_box"] = tracking_box
                state["keypoints"] = body.get("keypoints")
                state["keypoint_conf"] = body.get("keypoint_conf")
                state["head_points"] = body.get("head_points")
                state["head_box"] = body.get("head_box")
                state["head_only"] = bool(body.get("head_only"))
                state["last_seen"] = now
                state["hits"] = int(state.get("hits", 0)) + 1
                unmatched_track_ids.discard(best_track_id)
                continue

            track_id = self._next_body_track_id
            self._next_body_track_id += 1
            self._body_tracks[track_id] = {
                "track_id": track_id,
                "box": box,
                "tracking_box": tracking_box,
                "last_seen": now,
                "hits": 1,
                "keypoints": body.get("keypoints"),
                "keypoint_conf": body.get("keypoint_conf"),
                "head_points": body.get("head_points"),
                "head_box": body.get("head_box"),
                "head_only": bool(body.get("head_only")),
                "person_id": None,
                "label": None,
                "recognized": False,
            }

        self._dedupe_body_tracks()
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
        return best_track_id

    def _remember_track_identity(self, track_id: int, person_id: int | None, label: str, now: float) -> None:
        if person_id is None:
            return
        state = self._body_tracks.get(track_id)
        if not state:
            return
        state["person_id"] = person_id
        state["label"] = label
        state["recognized"] = True
        state["last_identity_seen"] = now

    def _recover_track_identity(self, track_id: int, sim: float | None, now: float) -> int | None:
        state = self._body_tracks.get(track_id)
        if not state or not state.get("recognized"):
            return None
        if sim is not None and sim < max(settings.face_match_threshold - 0.08, 0.5):
            return None
        person_id = state.get("person_id")
        return int(person_id) if person_id is not None else None

    def _build_body_overlay_items(
        self,
        body_tracks: list[dict],
        now: float,
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for state in body_tracks:
            if not state.get("recognized"):
                continue
            box = state.get("tracking_box")
            if not isinstance(box, tuple):
                box = state.get("box")
            label = state.get("label")
            if not isinstance(box, tuple) or not label:
                continue
            items.append(
                {
                    "box": box,
                    "label": str(label),
                    "recognized": True,
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

    def _is_live_face(
        self,
        frame: np.ndarray,
        box: tuple[int, int, int, int],
        bodies: list[dict] | None,
        now: float,
        strict_unknown: bool = False,
    ) -> bool:
        from processor.antispoof import lbp_texture_score, micro_movement_check

        self._prune_liveness_state(now)
        self._prune_identity_state(now)
        crop = self._crop_face(frame, box)
        if crop is None:
            return False

        x1, y1, x2, y2 = box
        frame_area = max(frame.shape[0] * frame.shape[1], 1)
        face_area_ratio = ((x2 - x1) * (y2 - y1)) / frame_area
        large_face = face_area_ratio >= settings.antispoof_small_face_ratio
        texture_score = lbp_texture_score(crop) if min(crop.shape[:2]) >= 32 else 0.0
        if bodies is None:
            body_supported = face_area_ratio >= max(settings.antispoof_small_face_ratio * 0.6, 0.03)
            strict_body_supported = face_area_ratio >= max(settings.antispoof_small_face_ratio * 1.05, 0.055)
        else:
            pose_supported = self._face_supported_by_pose(box, bodies, strict=False)
            strict_pose_supported = self._face_supported_by_pose(box, bodies, strict=True)
            body_supported = pose_supported or self._face_supported_by_body(box, bodies) or face_area_ratio >= 0.2
            strict_body_supported = strict_pose_supported or self._face_strictly_supported_by_body(box, bodies) or face_area_ratio >= 0.22
        if not body_supported:
            return False

        gray = cv2.cvtColor(cv2.resize(crop, (96, 96)), cv2.COLOR_BGR2GRAY)
        context = self._crop_context(frame, box)
        context_gray = None
        if context is not None:
            context_gray = cv2.cvtColor(cv2.resize(context, (128, 128)), cv2.COLOR_BGR2GRAY)
        key = self._face_key(box)
        prev = self._liveness_state.get(key)

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
                shift_motion_ok = shift >= max(8.0, max(x2 - x1, y2 - y1) * 0.07)

        self._liveness_state[key] = {
            "gray": gray,
            "context_gray": context_gray,
            "box": box,
            "stable_hits": stable_hits,
            "last_seen": now,
        }

        movement_ok = face_motion_ok or context_motion_ok or shift_motion_ok

        if strict_unknown:
            if not strict_body_supported:
                return False
            if texture_score < settings.antispoof_min_texture_score * 1.15:
                return False
            if bodies is not None and self._face_supported_by_pose(box, bodies, strict=True):
                if face_area_ratio >= 0.045 and stable_hits >= 2:
                    return True
            if face_area_ratio < max(settings.antispoof_small_face_ratio * 1.15, 0.05):
                return stable_hits >= 2 and (face_motion_ok or shift_motion_ok)
            return stable_hits >= 2 and (face_motion_ok or shift_motion_ok or (context_motion_ok and face_area_ratio >= 0.075))

        if not large_face:
            if texture_score < settings.antispoof_min_texture_score:
                return False
            return movement_ok and stable_hits >= 2
        if texture_score < settings.antispoof_min_texture_score * 0.75:
            return False
        return movement_ok

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

    def _draw_overlay(self, frame: np.ndarray, publish_mark: int | None = None) -> np.ndarray:
        now = time.time()
        face_overlay_active = bool(self._last_faces_info) and (now - self._last_faces_ts) <= self._overlay_ttl
        body_overlay_active = bool(self._last_body_info) and (now - self._last_body_ts) <= max(self._overlay_ttl, 4.0)
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
                x1, y1, x2, y2 = box
                active_body_boxes.append(box)
                rgb_color = (0, 180, 255) if recognized else (255, 160, 64)
                if isinstance(keypoints, list) and len(keypoints) >= 17:
                    confs = keypoint_conf if isinstance(keypoint_conf, list) else None
                    for a_idx, b_idx in _POSE_SKELETON_EDGES:
                        if a_idx >= len(keypoints) or b_idx >= len(keypoints):
                            continue
                        if confs is not None:
                            if a_idx >= len(confs) or b_idx >= len(confs):
                                continue
                            if float(confs[a_idx]) < 0.35 or float(confs[b_idx]) < 0.35:
                                continue
                        ax, ay = keypoints[a_idx]
                        bx, by = keypoints[b_idx]
                        draw.line((ax, ay, bx, by), fill=rgb_color, width=3)
                    for kp_idx, point in enumerate(keypoints):
                        if not isinstance(point, list) and not isinstance(point, tuple):
                            continue
                        if confs is not None and kp_idx < len(confs) and float(confs[kp_idx]) < 0.35:
                            continue
                        px, py = point
                        draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=rgb_color)
                else:
                    draw.rectangle((x1, y1, x2, y2), outline=rgb_color, width=2)
                body_label = label
                text_pos = self._body_label_position(box, keypoints, keypoint_conf)
                try:
                    bbox = draw.textbbox(text_pos, body_label, font=font)
                    draw.rectangle((bbox[0] - 4, bbox[1] - 2, bbox[2] + 4, bbox[3] + 2), fill=(0, 0, 0))
                except Exception:
                    pass
                draw.text(text_pos, body_label, font=font, fill=rgb_color)
        for (x1, y1, x2, y2), label, recognized in self._last_faces_info:
            color = (0, 200, 0) if recognized else (0, 0, 200)
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
            age_ms = int(max(0.0, now - self._last_faces_ts) * 1000)
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
        encode_opts = [int(cv2.IMWRITE_JPEG_QUALITY), 82]
        raw_ok, raw_buf = cv2.imencode(".jpg", frame, encode_opts)
        raw_bytes = raw_buf.tobytes() if raw_ok else None

        overlay_bytes = raw_bytes
        overlay_active = (
            (bool(self._last_faces_info) and (time.time() - self._last_faces_ts) <= self._overlay_ttl)
            or (bool(self._last_body_info) and (time.time() - self._last_body_ts) <= max(self._overlay_ttl, 4.0))
        )
        if overlay_active:
            overlay_frame = self._draw_overlay(frame, publish_mark=publish_mark)
            overlay_ok, overlay_buf = cv2.imencode(".jpg", overlay_frame, encode_opts)
            if overlay_ok:
                overlay_bytes = overlay_buf.tobytes()
        with self._frame_lock:
            if raw_bytes is not None:
                self._latest_raw_jpeg = raw_bytes
            if overlay_bytes is not None:
                self._latest_overlay_jpeg = overlay_bytes

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
            self._finalize_recording()
            return
        self._ensure_writer(frame.shape[1], frame.shape[0])
        if self._writer is not None:
            self._writer.write(frame)

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
            rel_path, abs_path = self._new_recording_path()
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(abs_path), fourcc, 15.0, frame_size)
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
        self._push_recording(
            {
                "camera_id": self.camera_id,
                "file_path": f"processor://{self.processor_id}/{relative_path}",
                "file_kind": "video",
                "started_at": started_dt.isoformat(),
                "ended_at": ended_dt.isoformat(),
                "duration_seconds": round(duration, 3),
                "file_size_bytes": size,
            }
        )
        logger.info("Recording saved camera=%s path=%s size=%s", self.camera_id, relative_path, size)

    def _dispatch_future(self, future: asyncio.Future, action: str, on_success=None) -> None:
        def _done(done_future):
            try:
                result = done_future.result()
                if on_success is not None:
                    on_success(result)
            except Exception:
                logger.exception("Failed to %s for camera %s", action, self.camera_id)

        future.add_done_callback(_done)

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

    def _push_recording(self, recording: dict) -> dict | None:
        if self._event_loop is None or self.processor_id is None:
            return None
        future = asyncio.run_coroutine_threadsafe(
            self.client.push_recording(self.processor_id, recording),
            self._event_loop,
        )
        self._dispatch_future(future, "push recording")
        return None
