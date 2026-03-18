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
        self._live_publish_interval = 1.0 / 12.0
        self._last_publish_ts = 0.0

        self._last_faces_info: list[tuple[tuple[int, int, int, int], str, bool]] = []
        self._last_faces_ts = 0.0
        self._last_activity_ts = 0.0

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
        try:
            while self._running:
                ret, frame = cap.read()
                if not ret or frame is None:
                    time.sleep(1)
                    continue

                motion = self._detect_motion(frame)
                now = time.monotonic()
                if motion:
                    self._last_activity_ts = time.time()

                if self.assignment.get("detection_enabled", True) and (now - last_face_scan) >= max(settings.face_scan_interval, 1):
                    last_face_scan = now
                    self._scan_faces(frame)

                self._record_frame(frame, motion)
                if (now - self._last_publish_ts) >= self._live_publish_interval:
                    self._publish_live_frames(frame)
                    self._last_publish_ts = now
                self._rotate_recording_if_needed(frame.shape[1], frame.shape[0])
        finally:
            self._finalize_recording()
            cap.release()

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

            for face in faces:
                box = tuple(int(v) for v in face["box"])
                person_id, sim = match_embedding(face["embedding"], self._gallery)
                recognized = person_id is not None
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
                    "confidence": round(sim, 4) if sim else None,
                    "snapshot_b64": snapshot_b64,
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
            self._writer_started_dt = datetime.utcnow()

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
        started_dt = self._writer_started_dt or datetime.utcnow()

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

        duration = max((datetime.utcnow() - started_dt).total_seconds(), 0.0)
        ended_dt = datetime.utcnow()
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
