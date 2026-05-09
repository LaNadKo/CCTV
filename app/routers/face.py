from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.permissions import check_permission, is_at_least_user, user_camera_permission
from app.vision import extract_best_face_embedding as _extract_best_face_embedding

router = APIRouter(prefix="/persons/face", tags=["persons-face"])


def _read_image_file(path: Path) -> np.ndarray | None:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    arr = np.frombuffer(data, np.uint8)
    if arr.size == 0:
        return None
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


async def _create_person_with_embedding(
    session: AsyncSession,
    emb: np.ndarray,
    first_name: str | None,
    last_name: str | None,
    middle_name: str | None,
) -> models.Person:
    person = models.Person(
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
    )
    session.add(person)
    await session.flush()
    session.add(
        models.PersonEmbedding(
            person_id=person.person_id,
            embedding=emb.astype(np.float32).tobytes(),
            source="face_enroll",
        )
    )
    return person


@router.post("/enroll-person-photo")
async def enroll_person_photo(
    file: UploadFile = File(...),
    first_name: str | None = Form(default=None),
    last_name: str | None = Form(default=None),
    middle_name: str | None = Form(default=None),
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not is_at_least_user(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission")
    data = await file.read()
    image = np.frombuffer(data, np.uint8)
    image = cv2.imdecode(image, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image")
    emb = _extract_best_face_embedding(image)
    if emb is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No face found")
    person = await _create_person_with_embedding(
        session,
        emb,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
    )
    await session.commit()
    await session.refresh(person)
    return {"person_id": person.person_id, "embedding_len": len(emb)}


@router.post("/enroll-from-recording")
async def enroll_person_from_recording(
    recording_id: int = Form(...),
    ts: float | None = Form(default=None, description="Timestamp in seconds"),
    first_name: str | None = Form(default=None),
    last_name: str | None = Form(default=None),
    middle_name: str | None = Form(default=None),
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(
        select(models.RecordingFile, models.VideoStream.camera_id)
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .where(models.RecordingFile.recording_file_id == recording_id)
    )
    row = res.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    recording, cam_id = row
    perm = await user_camera_permission(session, current_user.user_id, cam_id)
    if not check_permission(perm, "control") and current_user.role_id != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    cap = cv2.VideoCapture(recording.file_path)
    if not cap.isOpened():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Cannot open video")
    try:
        if ts is not None:
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
        else:
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            if frames and frames > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frames / 2)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Cannot read frame")
    finally:
        cap.release()

    emb = _extract_best_face_embedding(frame)
    if emb is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No face found in frame")

    person = await _create_person_with_embedding(
        session,
        emb,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
    )
    await session.commit()
    await session.refresh(person)
    return {"person_id": person.person_id, "from_recording": recording_id, "embedding_len": len(emb)}


@router.post("/enroll-from-snapshot")
async def enroll_person_from_snapshot(
    event_id: int = Form(...),
    first_name: str | None = Form(default=None),
    last_name: str | None = Form(default=None),
    middle_name: str | None = Form(default=None),
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    event = await session.get(models.Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    perm = await user_camera_permission(session, current_user.user_id, event.camera_id)
    if not check_permission(perm, "control") and current_user.role_id != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    snapshot_path = Path("snapshots").resolve() / f"event_{event_id}.jpg"
    if not snapshot_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    image = _read_image_file(snapshot_path)
    if image is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot read snapshot")

    emb = _extract_best_face_embedding(image)
    if emb is None:
        from app.routers.persons import _extract_best_face_embedding_via_processor

        emb = await _extract_best_face_embedding_via_processor(session, image, event.camera_id)
    if emb is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No face found in snapshot")

    person = await _create_person_with_embedding(
        session,
        emb,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
    )
    await session.commit()
    await session.refresh(person)
    return {"person_id": person.person_id, "from_event": event_id, "embedding_len": len(emb)}


