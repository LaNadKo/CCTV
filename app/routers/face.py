from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.permissions import check_permission, is_admin, user_camera_permission
from app.recording_storage import recording_local_path
from app.vision import extract_best_face_embedding as _extract_best_face_embedding

router = APIRouter(prefix="/persons/face", tags=["persons-face"])
_MAX_FACE_IMAGE_UPLOAD_BYTES = 8 * 1024 * 1024
_MAX_FACE_IMAGE_PIXELS = 16_000_000


def _ensure_face_enrollment_admin(user: models.User) -> None:
    if not is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can create persons",
        )


def _decoded_image_pixel_count(image: np.ndarray) -> int:
    if image.ndim < 2:
        return 0
    return int(image.shape[0]) * int(image.shape[1])


def _decode_face_image(data: bytes) -> np.ndarray:
    image = np.frombuffer(data, np.uint8)
    decoded = cv2.imdecode(image, cv2.IMREAD_COLOR)
    if decoded is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image")
    if _decoded_image_pixel_count(decoded) > _MAX_FACE_IMAGE_PIXELS:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Image dimensions are too large")
    return decoded


def _read_image_file(path: Path) -> np.ndarray | None:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    if not data:
        return None
    return _decode_face_image(data)


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
    _ensure_face_enrollment_admin(current_user)
    data = await file.read(_MAX_FACE_IMAGE_UPLOAD_BYTES + 1)
    if len(data) > _MAX_FACE_IMAGE_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Image is too large")
    image = _decode_face_image(data)
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
    _ensure_face_enrollment_admin(current_user)
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

    local_path = recording_local_path(recording.file_path)
    if local_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording is not available in backend storage",
        )
    cap = cv2.VideoCapture(str(local_path))
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
    _ensure_face_enrollment_admin(current_user)
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


