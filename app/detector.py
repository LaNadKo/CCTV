import asyncio
import contextlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, List, Tuple

import cv2
import numpy as np
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, vision
from app.db import SessionLocal
from app.camera_utils import resolve_source


@dataclass
class CameraConfig:
    camera_id: int
    stream_url: Optional[str]
    ip_address: Optional[str]
    detection_enabled: bool
    recording_mode: str  # continuous | event | off


class DetectionManager:
    """
    Background manager:
    - Polls DB for cameras.
    - For each camera starts a worker reading frames.
      * detection_enabled -> motion + face recognition (insightface)
      * recording_mode: continuous -> writes continuous segments
                        event -> records short clip on motion
    - Registers recording_files in DB.
    """

    def __init__(
        self,
        poll_interval: int = 10,
        motion_threshold: int = 25,
        min_event_gap: int = 10,
        face_threshold: float = 0.25,
        face_scan_interval: float = 1.0,
    ):
        self.log = logging.getLogger("app.activity")
        if not self.log.handlers:
            handler = logging.StreamHandler()
            fmt = logging.Formatter("%(asctime)s [ACTIVITY] %(message)s")
            handler.setFormatter(fmt)
            self.log.addHandler(handler)
        self.log.setLevel(logging.INFO)
        self.poll_interval = poll_interval
        self.motion_threshold = motion_threshold
        self.min_event_gap = min_event_gap
        self.face_threshold = face_threshold
        self.face_scan_interval = face_scan_interval
        self._scan_task: Optional[asyncio.Task] = None
        self._workers: Dict[int, asyncio.Task] = {}
        self._worker_cfg: Dict[int, CameraConfig] = {}
        self._running = False
        self.recordings_dir = Path("recordings").resolve()
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self._gallery: List[Tuple[int, np.ndarray, str]] = []  # (person_id, embedding, label)
        self._unknown_cache: Dict[int, List[Tuple[np.ndarray, float]]] = {}  # camera_id -> list of (emb, ts)
        self.snapshots_dir = Path("snapshots")
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    async def start(self):
        self._running = True
        self.log.info("detector.start poll=%ss", self.poll_interval)
        self._scan_task = asyncio.create_task(self._scanner())

    async def stop(self):
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scan_task
        for t in list(self._workers.values()):
            t.cancel()
        self._workers.clear()
        self._worker_cfg.clear()
        self.log.info("detector.stop")

    async def _scanner(self):
        while self._running:
            try:
                await self._sync_workers()
            except Exception:  # pragma: no cover - best effort
                import traceback

                traceback.print_exc()
            await asyncio.sleep(self.poll_interval)

    async def _sync_workers(self):
        async with SessionLocal() as session:
            self._gallery = await vision.load_gallery(session)
            res = await session.execute(
                select(models.Camera)
            )
            cams = res.scalars().all()
        desired: Dict[int, CameraConfig] = {}
        for cam in cams:
            cfg = CameraConfig(
                camera_id=cam.camera_id,
                stream_url=cam.stream_url,
                ip_address=cam.ip_address,
                detection_enabled=cam.detection_enabled,
                recording_mode=cam.recording_mode or "continuous",
            )
            # Start worker if we need detection or any recording
            if cfg.detection_enabled or cfg.recording_mode in ("continuous", "event"):
                desired[cfg.camera_id] = cfg

        # stop removed/changed
        for cam_id, task in list(self._workers.items()):
            if cam_id not in desired:
                self.log.info("camera.%s.stop removed", cam_id)
                task.cancel()
                self._workers.pop(cam_id, None)
                self._worker_cfg.pop(cam_id, None)
                continue
            if self._worker_cfg.get(cam_id) != desired[cam_id]:
                self.log.info("camera.%s.restart config_changed", cam_id)
                task.cancel()
                self._workers.pop(cam_id, None)
                self._worker_cfg.pop(cam_id, None)

        # start new
        for cam_id, cfg in desired.items():
            if cam_id not in self._workers:
                t = asyncio.create_task(self._run_camera(cfg))
                self._workers[cam_id] = t
                self._worker_cfg[cam_id] = cfg
                self.log.info("camera.%s.start detection=%s rec_mode=%s", cam_id, cfg.detection_enabled, cfg.recording_mode)

    async def _run_camera(self, cfg: CameraConfig):
        last_motion_ts = 0.0
        last_face_ts = 0.0
        while self._running:
            source = resolve_source(
                models.Camera(
                    camera_id=cfg.camera_id,
                    name="",
                    stream_url=cfg.stream_url,
                    ip_address=cfg.ip_address,
                    status_id=None,
                    location=None,
                    detection_enabled=cfg.detection_enabled,
                    recording_mode=cfg.recording_mode,
                )
            )
            cap = cv2.VideoCapture(source, cv2.CAP_DSHOW) if isinstance(source, int) else cv2.VideoCapture(source)
            if not cap.isOpened():
                cap.release()
                self.log.warning("camera.%s.open_fail source=%s", cfg.camera_id, source)
                await asyncio.sleep(5)
                continue
            self.log.info("camera.%s.opened source=%s", cfg.camera_id, source)

            prev_gray = None
            writer = None
            writer_path: Optional[Path] = None
            writer_started: Optional[float] = None
            last_faces_info: List[Tuple[Tuple[int, int, int, int], str, bool]] = []
            record_until = 0.0
            fail_count = 0
            try:
                while self._running:
                    ok, frame = await asyncio.to_thread(cap.read)
                    if not ok or frame is None:
                        fail_count += 1
                        if fail_count >= 5:
                            self.log.warning("camera.%s.read_fail reopen after %s fails", cfg.camera_id, fail_count)
                            break  # reopen camera
                        await asyncio.sleep(0.1)
                        continue
                    fail_count = 0
                    raw_frame = frame.copy()
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    motion = False
                    if prev_gray is not None:
                        diff = cv2.absdiff(prev_gray, gray)
                        thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1]
                        nonzero = cv2.countNonZero(thresh)
                        motion = nonzero > self.motion_threshold * 100
                    prev_gray = gray

                    now = time.time()

                    if cfg.detection_enabled and last_faces_info:
                        for (x1, y1, x2, y2), label, recognized in last_faces_info:
                            color = (0, 200, 0) if recognized else (0, 0, 200)
                            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                            cv2.putText(frame, label, (x1, max(y1 - 5, 0)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)

                    # recording
                    if cfg.recording_mode == "continuous":
                        writer, writer_path, writer_started = self._ensure_writer(writer, writer_path, writer_started, cfg.camera_id, frame, mode="cont")
                        if writer:
                            writer.write(frame)
                            # rotate every 60s
                            if writer_started and (now - writer_started) >= 60:
                                writer.release()
                                await self._register_file(cfg.camera_id, writer_path, writer_started, time.time(), mode="cont")
                                writer = None
                                writer_path = None
                                writer_started = None
                    elif cfg.recording_mode == "event":
                        if motion:
                            record_until = max(record_until, now + 5)
                        if record_until > now:
                            writer, writer_path, writer_started = self._ensure_writer(writer, writer_path, writer_started, cfg.camera_id, frame, mode="event")
                            if writer:
                                writer.write(frame)
                        elif writer:
                            writer.release()
                            await self._register_file(cfg.camera_id, writer_path, writer_started, time.time(), mode="event")
                            writer = None
                            writer_path = None
                            writer_started = None

                    # detection -> create event
                    if cfg.detection_enabled:
                        if motion and (now - last_motion_ts) > self.min_event_gap:
                            last_motion_ts = now
                            await self._create_detection(cfg.camera_id, "motion_detected", confidence=0.5)
                        if (now - last_face_ts) > self.face_scan_interval:
                            last_face_ts = now
                            faces_info, annotated = await vision.annotate_and_match(raw_frame, self._gallery, self.face_threshold)
                            if faces_info:
                                last_faces_info = [(box, label, rec) for box, label, rec, *_ in faces_info]
                                # create events
                                for info in faces_info:
                                    box, label, rec, person_id, sim, emb = info[:6]
                                    if rec:
                                        await self._create_face_event(cfg.camera_id, person_id, sim, True, raw_frame.copy(), box)
                                    else:
                                        if self._should_skip_unknown(cfg.camera_id, emb):
                                            continue
                                        await self._create_face_event(cfg.camera_id, None, sim, False, raw_frame.copy(), box)
                # loop end
            except Exception:
                import traceback
                traceback.print_exc()
            finally:
                if writer:
                    writer.release()
                    await self._register_file(cfg.camera_id, writer_path, writer_started, time.time(), mode=cfg.recording_mode)
                cap.release()
            self.log.info("camera.%s.reopen", cfg.camera_id)
            await asyncio.sleep(1)

    def _ensure_writer(self, writer, writer_path: Optional[Path], writer_started: Optional[float], camera_id: int, frame, mode: str):
        if writer is not None:
            return writer, writer_path, writer_started
        h, w = frame.shape[:2]
        # Пишем в H.264 (H264 fourcc) в контейнер AVI; если не открылся — MJPG -> mp4v
        fourcc = cv2.VideoWriter_fourcc(*"H264")
        ts = int(time.time())
        dt = __import__("datetime").datetime.fromtimestamp(ts)
        folder = self.recordings_dir / dt.strftime("%Y-%m-%d") / dt.strftime("%H")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"cam{camera_id}_{mode}_{dt.strftime('%Y%m%d_%H%M%S')}.avi"
        writer = cv2.VideoWriter(str(path), fourcc, 10.0, (w, h))
        if not writer.isOpened():
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            writer = cv2.VideoWriter(str(path), fourcc, 10.0, (w, h))
        if not writer.isOpened():
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(path), fourcc, 10.0, (w, h))
        codec_name = "h264" if fourcc == cv2.VideoWriter_fourcc(*"H264") else ("mjpg" if fourcc == cv2.VideoWriter_fourcc(*"MJPG") else "mp4v")
        if not writer.isOpened():
            self.log.error("camera.%s.writer.fail codec=%s path=%s", camera_id, codec_name, path)
            return None, None, None
        self.log.info("camera.%s.writer.start mode=%s path=%s codec=%s", camera_id, mode, path, codec_name)
        return writer, path, time.time()

    async def _create_detection(self, camera_id: int, event_type: str, confidence: Optional[float] = None):
        async with SessionLocal() as session:
            et_id = await self._event_type_id(session, event_type)
            evt = models.Event(
                camera_id=camera_id,
                event_type_id=et_id,
                person_id=None,
                recording_file_id=None,
                confidence=confidence,
                created_by_user_id=None,
            )
            session.add(evt)
            await session.commit()
        self.log.info("event.motion camera=%s event_id=%s conf=%.2f", camera_id, evt.event_id, confidence or 0.0)

    async def _event_type_id(self, session: AsyncSession, name: str) -> int:
        res = await session.execute(select(models.EventType).where(models.EventType.name == name))
        et = res.scalar_one_or_none()
        if et is None:
            raise RuntimeError(f"Event type {name} not found")
        return et.event_type_id

    async def _ensure_storage_target(self, session: AsyncSession) -> int:
        res = await session.execute(select(models.StorageTarget).where(models.StorageTarget.name == "local_files"))
        st = res.scalar_one_or_none()
        if st:
            return st.storage_target_id
        st = models.StorageTarget(
            name="local_files",
            root_path=str(self.recordings_dir.resolve()),
            device_kind="other",
            purpose="recording",
            is_primary_recording=False,
            is_active=True,
        )
        session.add(st)
        await session.flush()
        self.log.info("storage_target.create id=%s path=%s", st.storage_target_id, st.root_path)
        return st.storage_target_id

    async def _ensure_video_stream(self, session: AsyncSession, camera_id: int) -> int:
        res = await session.execute(
            select(models.VideoStream).where(
                models.VideoStream.camera_id == camera_id,
                models.VideoStream.stream_url.is_(None),
            )
        )
        vs = res.scalar_one_or_none()
        if vs:
            return vs.video_stream_id
        vs = models.VideoStream(
            camera_id=camera_id,
            resolution=None,
            fps=10,
            enabled=True,
            stream_url=None,
        )
        session.add(vs)
        await session.flush()
        return vs.video_stream_id

    async def _register_file(self, camera_id: int, path: Optional[Path], started_ts: Optional[float], ended_ts: float, mode: str):
        if not path or not started_ts:
            return
        size = path.stat().st_size if path.exists() else None
        duration = ended_ts - started_ts
        if duration < 2.0:
            # too short, likely reconnect artifact
            if path.exists():
                with contextlib.suppress(Exception):
                    path.unlink()
            self.log.info("recording.skip_short camera=%s path=%s dur=%.2fs", camera_id, path, duration)
            return
        async with SessionLocal() as session:
            storage_target_id = await self._ensure_storage_target(session)
            video_stream_id = await self._ensure_video_stream(session, camera_id)
            rf = models.RecordingFile(
                video_stream_id=video_stream_id,
                storage_target_id=storage_target_id,
                file_kind="video",
                file_path=str(path),
                started_at=__import__("datetime").datetime.fromtimestamp(started_ts),
                ended_at=__import__("datetime").datetime.fromtimestamp(ended_ts),
                duration_seconds=duration,
                file_size_bytes=size,
                checksum=None,
            )
            session.add(rf)
            await session.commit()
        self.log.info("recording.save camera=%s mode=%s path=%s dur=%.2fs size=%s", camera_id, mode, path.name, duration, size)

    async def _refresh_gallery(self, session: AsyncSession) -> None:
        res = await session.execute(
            select(models.PersonEmbedding.person_id, models.PersonEmbedding.embedding)
            .join(models.Person, models.Person.person_id == models.PersonEmbedding.person_id)
            .where(models.Person.deleted_at.is_(None))
        )
        gallery: List[Tuple[int, np.ndarray]] = []
        for person_id, raw_embedding in res.all():
            try:
                emb = np.frombuffer(raw_embedding, dtype=np.float32)
                gallery.append((person_id, emb))
            except Exception:
                continue
        self._gallery = gallery

    async def _get_face_app(self):
        if self._face_app is not None:
            return self._face_app
        import torch
        from facenet_pytorch import MTCNN, InceptionResnetV1

        device = "cuda" if torch.cuda.is_available() else "cpu"
        mtcnn = MTCNN(keep_all=True, device=device)
        embedder = InceptionResnetV1(pretrained="vggface2").eval().to(device)
        self._face_app = (mtcnn, embedder, device)
        return self._face_app

    def _draw_faces(self, frame, faces_info: List[Tuple[Tuple[int, int, int, int], str, bool]]):
        for (x1, y1, x2, y2), label, recognized in faces_info:
            color = (0, 200, 0) if recognized else (0, 0, 200)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, max(y1 - 5, 0)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)

    async def _process_faces(self, camera_id: int, frame, face_app):
        mtcnn, embedder, device = face_app
        # convert BGR to RGB
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        import torch

        # detect
        boxes, probs = await asyncio.to_thread(mtcnn.detect, img_rgb)
        if boxes is None or len(boxes) == 0:
            return
        # extract aligned faces
        faces = []
        for box in boxes:
            x1, y1, x2, y2 = [int(b) for b in box]
            crop = img_rgb[max(y1,0):max(y2,0), max(x1,0):max(x2,0)]
            if crop.size == 0:
                continue
            faces.append(cv2.resize(crop, (160, 160)))
        if not faces:
            return
        batch = np.stack(faces).astype(np.float32) / 255.0
        batch = torch.from_numpy(batch).permute(0,3,1,2).to(device)
        with torch.no_grad():
            embs = embedder(batch).cpu().numpy()

        gallery = list(self._gallery)
        faces_info: List[Tuple[Tuple[int, int, int, int], str, bool]] = []
        annotated = frame.copy()
        for emb, box in zip(embs, boxes):
            best_id = None
            best_sim = -1.0
            for pid, g_emb in gallery:
                if emb.shape != g_emb.shape:
                    continue
                sim = float(np.dot(emb, g_emb) / (np.linalg.norm(emb) * np.linalg.norm(g_emb) + 1e-6))
                if sim > best_sim:
                    best_sim = sim
                    best_id = pid
            x1, y1, x2, y2 = [int(b) for b in box]
            if best_id is not None and best_sim >= self.face_threshold:
                await self._create_face_event(camera_id, best_id, best_sim, recognized=True, frame_with_boxes=None)
                faces_info.append(((x1, y1, x2, y2), f"id {best_id} ({best_sim:.2f})", True))
            else:
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(annotated, "Unknown", (x1, max(y1 - 5, 0)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2, cv2.LINE_AA)
                await self._create_face_event(camera_id, None, best_sim if best_sim > 0 else None, recognized=False, frame_with_boxes=annotated)
                faces_info.append(((x1, y1, x2, y2), "Unknown", False))
        return faces_info

    def _should_skip_unknown(self, camera_id: int, emb: np.ndarray, ttl: float = 10.0, sim_thr: float = 0.6) -> bool:
        cache = self._unknown_cache.setdefault(camera_id, [])
        now = time.time()
        # drop expired
        cache[:] = [(e, ts) for e, ts in cache if now - ts < ttl]
        for e, ts in cache:
            sim = float(np.dot(emb, e) / (np.linalg.norm(emb) * np.linalg.norm(e) + 1e-6))
            if sim >= sim_thr:
                return True
        cache.append((emb, now))
        return False

    async def _create_face_event(self, camera_id: int, person_id: Optional[int], confidence: Optional[float], recognized: bool, frame_with_boxes=None, box=None):
        async with SessionLocal() as session:
            if recognized:
                et_id = await self._event_type_id(session, "face_recognized")
            else:
                et_id = await self._event_type_id(session, "face_unknown")
            evt = models.Event(
                camera_id=camera_id,
                event_type_id=et_id,
                person_id=person_id,
                recording_file_id=None,
                confidence=confidence,
                created_by_user_id=None,
            )
            session.add(evt)
            await session.flush()
            if not recognized:
                review = models.EventReview(event_id=evt.event_id, status="pending")
                session.add(review)
                # save snapshot if provided
                if frame_with_boxes is not None:
                    try:
                        path = self.snapshots_dir / f"event_{evt.event_id}.jpg"
                        if box is not None:
                            x1, y1, x2, y2 = [int(b) for b in box]
                            h, w = frame_with_boxes.shape[:2]
                            pad = int(0.2 * max(x2 - x1, y2 - y1))
                            xs1, ys1 = max(0, x1 - pad), max(0, y1 - pad)
                            xs2, ys2 = min(w, x2 + pad), min(h, y2 + pad)
                            if xs2 - xs1 > 20 and ys2 - ys1 > 20:
                                crop = frame_with_boxes[ys1:ys2, xs1:xs2]
                                cv2.imwrite(str(path), crop)
                            else:
                                cv2.imwrite(str(path), frame_with_boxes)
                        else:
                            cv2.imwrite(str(path), frame_with_boxes)
                    except Exception:
                        pass
            await session.commit()
        self.log.info(
            "event.face camera=%s event_id=%s recognized=%s person=%s conf=%.2f snapshot=%s",
            camera_id,
            evt.event_id,
            recognized,
            person_id,
            confidence or 0.0,
            path if (not recognized and frame_with_boxes is not None) else None,
        )
