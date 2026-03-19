"""Camera worker: frame reading, motion detection, face scanning, event reporting."""
from __future__ import annotations
import asyncio
import cv2
import logging
import time
import numpy as np
from processor.config import settings

logger = logging.getLogger(__name__)


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
        # dedup: track last event per person to avoid spam
        self._last_event: dict[int | None, float] = {}
        self._event_dedup_seconds = 10.0

    async def set_gallery(self, gallery: list[dict]):
        self._gallery = gallery

    async def start(self, processor_id: int):
        self.processor_id = processor_id
        self._running = True
        self._event_loop = asyncio.get_event_loop()
        await asyncio.to_thread(self._run_loop)

    def stop(self):
        self._running = False

    def _run_loop(self):
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            logger.error("Cannot open camera %s source=%s", self.camera_id, self.source)
            return
        frame_count = 0
        last_face_scan = 0
        try:
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(1)
                    continue
                frame_count += 1
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (21, 21), 0)
                motion = False
                if self._prev_gray is not None:
                    delta = cv2.absdiff(self._prev_gray, gray)
                    thresh = cv2.threshold(delta, settings.motion_threshold, 255, cv2.THRESH_BINARY)[1]
                    thresh = cv2.dilate(thresh, None, iterations=2)
                    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for c in contours:
                        if cv2.contourArea(c) >= settings.motion_min_area:
                            motion = True
                            break
                self._prev_gray = gray
                now = time.monotonic()
                if motion and (now - last_face_scan) >= settings.face_scan_interval:
                    last_face_scan = now
                    self._scan_faces(frame)
        finally:
            cap.release()

    def _scan_faces(self, frame: np.ndarray):
        try:
            from processor.vision import detect_faces, match_embedding
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            faces = detect_faces(rgb)
            now = time.time()
            for face in faces:
                person_id, sim = match_embedding(face["embedding"], self._gallery)
                recognized = person_id is not None
                event_type = "face_recognized" if recognized else "face_unknown"

                # dedup: skip if same person reported recently
                dedup_key = person_id
                last_ts = self._last_event.get(dedup_key, 0)
                if now - last_ts < self._event_dedup_seconds:
                    continue
                self._last_event[dedup_key] = now

                logger.info(
                    "Camera %s: %s person=%s sim=%.3f",
                    self.camera_id, event_type, person_id, sim,
                )

                # Report event to backend
                self._push_event({
                    "event_type": event_type,
                    "camera_id": self.camera_id,
                    "person_id": person_id,
                    "confidence": round(sim, 4) if sim else None,
                })
        except Exception:
            logger.exception("Face scan error on camera %s", self.camera_id)

    def _push_event(self, event: dict):
        """Push event to backend from sync thread."""
        if self._event_loop is None or self.processor_id is None:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.client.push_event(self.processor_id, event),
                self._event_loop,
            )
            future.result(timeout=5)
        except Exception:
            logger.exception("Failed to push event for camera %s", self.camera_id)
