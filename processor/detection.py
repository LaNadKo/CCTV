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

        self._last_event: dict[int | None, float] = {}
        self._event_dedup_seconds = 10.0
        self._overlay_ttl = max(float(settings.face_scan_interval) + 1.0, 3.0)
        self._record_event_tail_seconds = 10.0
        self._live_publish_interval = 1.0 / 15.0
        self._last_publish_ts = 0.0

        self._last_faces_info: list[tuple[tuple[int, int, int, int], str, bool]] = []
        self._last_faces_ts = 0.0
        self._last_activity_ts = 0.0
        self._last_motion_ts = 0.0
        self._liveness_state: dict[str, dict[str, object]] = {}

        self._capture_lock = threading.Lock()
        self._capture_ready = threading.Event()
        self._capture_frame: np.ndarray | None = None
        self._capture_seq = 0
        self._capture_thread: threading.Thread | None = None

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

                if self.assignment.get("detection_enabled", True) and (now - last_face_scan) >= max(settings.face_scan_interval, 0.5):
                    last_face_scan = now
                    self._scan_faces(frame)

                self._record_frame(frame, motion)
                if (now - self._last_publish_ts) >= self._live_publish_interval:
                    self._publish_live_frames(frame)
                    self._last_publish_ts = now
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

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            faces = detect_faces(rgb)
            now = time.time()
            overlay_items: list[tuple[tuple[int, int, int, int], str, bool]] = []
            bodies: list[dict] | None = []
            frame_area = max(frame.shape[0] * frame.shape[1], 1)

            if faces and any(
                ((face["box"][2] - face["box"][0]) * (face["box"][3] - face["box"][1])) / frame_area
                < max(settings.antispoof_small_face_ratio * 2.0, 0.2)
                for face in faces
            ):
                try:
                    from processor.body_detector import detect_bodies

                    bodies = detect_bodies(frame, conf=0.45)
                except Exception:
                    logger.exception("Body support detection failed on camera %s", self.camera_id)
                    bodies = None

            for face in faces:
                box = tuple(int(v) for v in face["box"])
                if not self._is_live_face(frame, box, bodies, now):
                    logger.debug("Camera %s: suppressed non-live/spoof-like face %s", self.camera_id, box)
                    continue
                person_id, sim = match_embedding(face["embedding"], self._gallery)
                recognized = person_id is not None
                if not recognized:
                    recent_motion = (time.time() - self._last_motion_ts) <= settings.unknown_face_requires_motion_seconds
                    if not recent_motion:
                        logger.debug(
                            "Camera %s: suppressed unknown face without recent scene motion box=%s",
                            self.camera_id,
                            box,
                        )
                        continue
                event_type = "face_recognized" if recognized else "face_unknown"
                label = self._label_for_person(person_id) if recognized else "Unknown"
                overlay_items.append((box, label, recognized))

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

            if overlay_items:
                self._last_faces_info = overlay_items
                self._last_faces_ts = now
        except Exception:
            logger.exception("Face scan error on camera %s", self.camera_id)

    def _label_for_person(self, person_id: int | None) -> str:
        if person_id is None:
            return "Unknown"
        for entry in self._gallery:
            if entry.get("person_id") == person_id:
                return str(entry.get("label") or f"ID {person_id}")
        return f"ID {person_id}"

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
            bx1, by1, bx2, by2 = [float(v) for v in body["box"]]
            body_width = max(bx2 - bx1, 1.0)
            body_height = max(by2 - by1, 1.0)
            face_inside = bx1 <= face_cx <= bx2 and by1 <= face_cy <= by1 + body_height * 0.55
            scale_ok = face_width <= body_width * 0.85 and face_height <= body_height * 0.55
            if face_inside and scale_ok:
                return True
        return False

    def _prune_liveness_state(self, now: float) -> None:
        stale_keys = [
            key
            for key, state in self._liveness_state.items()
            if now - float(state.get("last_seen", 0.0)) > 12.0
        ]
        for key in stale_keys:
            self._liveness_state.pop(key, None)

    def _is_live_face(
        self,
        frame: np.ndarray,
        box: tuple[int, int, int, int],
        bodies: list[dict] | None,
        now: float,
    ) -> bool:
        from processor.antispoof import lbp_texture_score, micro_movement_check

        self._prune_liveness_state(now)
        crop = self._crop_face(frame, box)
        if crop is None:
            return False

        x1, y1, x2, y2 = box
        frame_area = max(frame.shape[0] * frame.shape[1], 1)
        face_area_ratio = ((x2 - x1) * (y2 - y1)) / frame_area
        large_face = face_area_ratio >= settings.antispoof_small_face_ratio
        texture_score = lbp_texture_score(crop) if min(crop.shape[:2]) >= 32 else 0.0
        if bodies is None:
            body_supported = face_area_ratio >= 0.2
        else:
            body_supported = self._face_supported_by_body(box, bodies) or face_area_ratio >= 0.2
        if not body_supported:
            return False

        gray = cv2.cvtColor(cv2.resize(crop, (96, 96)), cv2.COLOR_BGR2GRAY)
        context = self._crop_context(frame, box)
        context_gray = None
        if context is not None:
            context_gray = cv2.cvtColor(cv2.resize(context, (128, 128)), cv2.COLOR_BGR2GRAY)
        key = self._face_key(box)
        prev = self._liveness_state.get(key)

        movement_ok = False
        stable_hits = 1
        if prev:
            prev_gray = prev.get("gray")
            prev_context_gray = prev.get("context_gray")
            prev_box = prev.get("box")
            stable_hits = int(prev.get("stable_hits", 0)) + 1
            if isinstance(prev_gray, np.ndarray):
                movement_ok = micro_movement_check(
                    prev_gray,
                    gray,
                    threshold=settings.antispoof_face_motion_threshold,
                    pixel_threshold=20.0,
                    min_active_ratio=settings.antispoof_active_ratio,
                )
            if isinstance(prev_context_gray, np.ndarray) and isinstance(context_gray, np.ndarray):
                movement_ok = movement_ok or micro_movement_check(
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
                movement_ok = movement_ok or shift >= max(8.0, max(x2 - x1, y2 - y1) * 0.07)

        self._liveness_state[key] = {
            "gray": gray,
            "context_gray": context_gray,
            "box": box,
            "stable_hits": stable_hits,
            "last_seen": now,
        }

        if not large_face:
            if texture_score < settings.antispoof_min_texture_score:
                return False
            return movement_ok and stable_hits >= 2
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

    def _draw_overlay(self, frame: np.ndarray) -> np.ndarray:
        now = time.time()
        if not self._last_faces_info or now - self._last_faces_ts > self._overlay_ttl:
            return frame
        annotated = frame.copy()
        pil_image = Image.fromarray(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_image)
        font = _load_overlay_font(max(18, frame.shape[1] // 55))
        for (x1, y1, x2, y2), label, recognized in self._last_faces_info:
            color = (0, 200, 0) if recognized else (0, 0, 200)
            rgb_color = (color[2], color[1], color[0])
            draw.rectangle((x1, y1, x2, y2), outline=rgb_color, width=2)
            text_pos = (x1, max(y1 - 28, 6))
            try:
                bbox = draw.textbbox(text_pos, label, font=font)
                draw.rectangle(
                    (bbox[0] - 4, bbox[1] - 2, bbox[2] + 4, bbox[3] + 2),
                    fill=(0, 0, 0),
                )
            except Exception:
                pass
            draw.text(text_pos, label, font=font, fill=rgb_color)
        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

    def _publish_live_frames(self, frame: np.ndarray) -> None:
        encode_opts = [int(cv2.IMWRITE_JPEG_QUALITY), 82]
        raw_ok, raw_buf = cv2.imencode(".jpg", frame, encode_opts)
        overlay_frame = self._draw_overlay(frame)
        overlay_ok, overlay_buf = cv2.imencode(".jpg", overlay_frame, encode_opts)
        with self._frame_lock:
            if raw_ok:
                self._latest_raw_jpeg = raw_buf.tobytes()
            if overlay_ok:
                self._latest_overlay_jpeg = overlay_buf.tobytes()

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
