from typing import List, Optional
import asyncio
import time
from pathlib import Path
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user, get_current_user_allow_query
from app.permissions import check_permission, user_camera_permission
from app.schemas.cameras import CameraOut, CameraPermissionOut

# Lazy imports for heavy deps (cv2, torch) — only needed for streaming endpoint
cv2 = None
vision = None
resolve_source = None

def _ensure_vision_deps():
    global cv2, vision, resolve_source
    if cv2 is None:
        import cv2 as _cv2
        cv2 = _cv2
    if vision is None:
        from app import vision as _vision
        vision = _vision
    if resolve_source is None:
        from app.camera_utils import resolve_source as _rs
        resolve_source = _rs

router = APIRouter(prefix="/cameras", tags=["cameras"])
log = logging.getLogger("app.activity")

_unknown_cache_live = {}  # camera_id -> list of (embedding, ts)


def _should_skip_unknown(camera_id: int, emb, ttl: float = 10.0, sim_thr: float = 0.6) -> bool:
    import numpy as np
    cache = _unknown_cache_live.setdefault(camera_id, [])
    now = time.time()
    cache[:] = [(e, ts) for e, ts in cache if now - ts < ttl]
    for e, ts in cache:
        sim = float(np.dot(emb, e) / (np.linalg.norm(emb) * np.linalg.norm(e) + 1e-6))
        if sim >= sim_thr:
            return True
    cache.append((emb, now))
    return False


async def _create_face_event(
    session: AsyncSession,
    camera_id: int,
    recognized: bool,
    person_id: int | None,
    confidence: float | None,
    frame_with_boxes=None,
    box=None,
):
    try:
        et_name = "face_recognized" if recognized else "face_unknown"
        res = await session.execute(select(models.EventType).where(models.EventType.name == et_name))
        et = res.scalar_one_or_none()
        if et is None:
            log.warning("Missing event type '%s' in DB — skipping event creation", et_name)
            return None
        evt = models.Event(
            camera_id=camera_id,
            event_type_id=et.event_type_id,
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
            if frame_with_boxes is not None:
                try:
                    snapshots_dir = Path("snapshots")
                    snapshots_dir.mkdir(exist_ok=True)
                    path = snapshots_dir / f"event_{evt.event_id}.jpg"
                    import cv2

                    if box is not None:
                        x1, y1, x2, y2 = [int(b) for b in box]
                        pad = int(0.2 * max(x2 - x1, y2 - y1))
                        h, w = frame_with_boxes.shape[:2]
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
        return evt.event_id
    except Exception as exc:
        log.error("Failed to create face event: %s", exc)
        try:
            await session.rollback()
        except Exception:
            pass
        return None


@router.get("", response_model=List[CameraOut])
async def list_cameras(
    home_id: Optional[int] = Query(None, description="Filter cameras by home"),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> List[CameraOut]:
    if home_id is not None:
        # Filter cameras assigned to rooms in this home
        result = await session.execute(
            select(models.Camera)
            .join(models.RoomCamera, models.RoomCamera.camera_id == models.Camera.camera_id)
            .join(models.Room, models.Room.room_id == models.RoomCamera.room_id)
            .where(models.Room.home_id == home_id)
        )
    else:
        result = await session.execute(select(models.Camera))
    cams = result.scalars().all()
    out: List[CameraOut] = []
    for cam in cams:
        # system_admin (role_id=1) sees all cameras
        if current_user.role_id == 1:
            perm = "admin"
        else:
            perm = await user_camera_permission(session, current_user.user_id, cam.camera_id)
        if perm:
            out.append(
                CameraOut(
                    camera_id=cam.camera_id,
                    name=cam.name,
                    location=cam.location,
                    ip_address=cam.ip_address,
                    stream_url=cam.stream_url,
                    permission=perm,
                    detection_enabled=cam.detection_enabled,
                    recording_mode=cam.recording_mode,
                    tracking_enabled=cam.tracking_enabled,
                    tracking_mode=cam.tracking_mode,
                    tracking_target_person_id=cam.tracking_target_person_id,
                )
            )
    return out


@router.get("/{camera_id}/permission", response_model=CameraPermissionOut)
async def get_camera_permission(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> CameraPermissionOut:
    result = await session.execute(select(models.Camera).where(models.Camera.camera_id == camera_id))
    cam = result.scalar_one_or_none()
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    perm = await user_camera_permission(session, current_user.user_id, camera_id)
    return CameraPermissionOut(camera_id=camera_id, permission=perm, allowed=perm is not None)


async def require_camera_permission(
    required: str,
    camera_id: int,
    session: AsyncSession,
    user_id: int,
) -> None:
    perm = await user_camera_permission(session, user_id, camera_id)
    if not check_permission(perm, required):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden for this camera")


@router.get("/{camera_id}/stream")
async def stream_camera(
    camera_id: int,
    annotate: bool = True,
    annotate_interval: int = 30,
    face_threshold: float = 0.25,
    overlay_ttl: float = 2.0,
    # lazy-load heavy dependencies on first stream request
    _init=Depends(lambda: _ensure_vision_deps()),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user_allow_query),
):
    cam = await session.get(models.Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    perm = await user_camera_permission(session, current_user.user_id, camera_id)
    if not check_permission(perm, "view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this camera")

    source = resolve_source(cam)
    tried_backends = []
    cap = None
    # On Windows laptop webcams often need CAP_DSHOW/CAP_MSMF to open.
    backend_candidates = [None]
    if isinstance(source, int):
        backend_candidates = [cv2.CAP_DSHOW, cv2.CAP_MSMF, None]
    for backend in backend_candidates:
        cap = cv2.VideoCapture(source, backend) if backend is not None else cv2.VideoCapture(source)
        tried_backends.append(backend)
        if cap.isOpened():
            break
        cap.release()
        cap = None
    if cap is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Cannot open camera source (source={source}, tried backends={tried_backends}). "
            "If this is a laptop webcam, set stream_url=local:0. If already set, close other apps that hold the camera.",
        )

    gallery = await vision.load_gallery(session)
    gallery_loaded_at = time.time()
    frame_idx = 0
    last_face_event_ts = 0.0
    event_gap = 5.0  # seconds
    last_faces_info = []
    last_faces_ts = 0.0

    async def frame_generator():
        nonlocal frame_idx
        nonlocal last_face_event_ts
        nonlocal last_faces_info, last_faces_ts, gallery, gallery_loaded_at
        try:
            while True:
                ok, frame = await asyncio.to_thread(cap.read)
                if not ok or frame is None:
                    break
                raw_frame = frame.copy()
                now = time.time()
                if now - gallery_loaded_at > 10:
                    gallery = await vision.load_gallery(session)
                    gallery_loaded_at = now
                # draw previous boxes to reduce flicker
                if last_faces_info and (now - last_faces_ts) < overlay_ttl:
                    label_items = []
                    for (x1, y1, x2, y2), label, rec in last_faces_info:
                        color_rgb = (0, 200, 0) if rec else (200, 0, 0)
                        cv2.rectangle(frame, (x1, y1), (x2, y2),
                                      (color_rgb[2], color_rgb[1], color_rgb[0]), 2)
                        label_items.append((x1, y1, label, color_rgb))
                    frame = vision.draw_labels(frame, label_items)
                if annotate and cam.detection_enabled and annotate_interval > 0 and (frame_idx % annotate_interval == 0):
                    faces_info, annotated = await vision.annotate_and_match(raw_frame, gallery, face_threshold)
                    if faces_info:
                        if (now - last_face_event_ts) >= event_gap:
                            last_face_event_ts = now
                            for box, label, rec, person_id, sim, emb in faces_info:
                                if not rec and _should_skip_unknown(cam.camera_id, emb):
                                    continue
                                # СЃРѕС…СЂР°РЅСЏРµРј СЃРЅР°РїС€РѕС‚ СЃ РѕСЂРёРіРёРЅР°Р»СЊРЅРѕРіРѕ РєР°РґСЂР° Р±РµР· РѕРІРµСЂР»РµСЏ
                                await _create_face_event(
                                    session,
                                    cam.camera_id,
                                    rec,
                                    person_id,
                                    sim,
                                    raw_frame.copy() if not rec else None,
                                    box if not rec else None,
                                )
                        last_faces_info = [(box, label, rec) for box, label, rec, _, _, _ in faces_info]
                        last_faces_ts = now
                        # РґР»СЏ РѕС‚РѕР±СЂР°Р¶РµРЅРёСЏ РѕСЃС‚Р°РІР»СЏРµРј РѕРІРµСЂР»РµР№
                        frame = annotated
                frame_idx += 1
                ok, buffer = cv2.imencode(".jpg", frame)
                if not ok:
                    continue
                chunk = buffer.tobytes()
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + chunk + b"\r\n"
        finally:
            cap.release()

    return StreamingResponse(frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")
