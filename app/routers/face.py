from typing import List, Optional
from pathlib import Path

import numpy as np
import cv2
import torch
from facenet_pytorch import MTCNN, InceptionResnetV1
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user, get_current_user_allow_query
from app.schemas.face import FaceEmbedding, FaceEnrollResponse, FaceLoginRequest, FaceLoginResponse
from app.security import create_access_token, decrypt_secret, verify_totp
from app.permissions import user_camera_permission, check_permission

router = APIRouter(prefix="/auth/face", tags=["auth-face"])

_mtcnn: Optional[MTCNN] = None
_embedder: Optional[InceptionResnetV1] = None
_device: str = "cpu"


def _read_image_file(path: Path) -> np.ndarray | None:
    """
    Read image from disk using bytes+imdecode to avoid Unicode path issues on Windows.
    Returns BGR image or None if cannot read.
    """
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    arr = np.frombuffer(data, np.uint8)
    if arr.size == 0:
        return None
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _preprocess_frame(frame_bgr: np.ndarray) -> np.ndarray:
    # слегка поднять контраст/яркость в темноте (CLAHE по L-каналу)
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l2 = clahe.apply(l)
    lab = cv2.merge((l2, a, b))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _face_models():
    global _mtcnn, _embedder, _device
    if _mtcnn is not None and _embedder is not None:
        return _mtcnn, _embedder, _device
    _device = "cuda" if torch.cuda.is_available() else "cpu"
    _mtcnn = MTCNN(keep_all=True, device=_device, thresholds=[0.5, 0.6, 0.6])
    _embedder = InceptionResnetV1(pretrained="vggface2").eval().to(_device)
    return _mtcnn, _embedder, _device


def _extract_best_face_embedding(image_bgr: np.ndarray) -> np.ndarray | None:
    """Extract embedding from the largest face using MTCNN aligned extraction.

    Uses mtcnn.extract() for face alignment — same pipeline as vision.py
    detection, so that enrolled and detected embeddings are comparable.
    """
    image_bgr = _preprocess_frame(image_bgr)
    mtcnn, embedder, device = _face_models()
    img_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    boxes, probs = mtcnn.detect(img_rgb)
    if boxes is None or len(boxes) == 0:
        return None
    # take the largest box
    areas = [(box[2] - box[0]) * (box[3] - box[1]) for box in boxes]
    best_idx = int(np.argmax(areas))
    best_box = [boxes[best_idx]]
    # Use MTCNN aligned extraction (same as vision.py detection pipeline)
    face_tensors = mtcnn.extract(img_rgb, best_box, None)
    if face_tensors is None or len(face_tensors) == 0 or face_tensors[0] is None:
        return None
    face = face_tensors[0].permute(1, 2, 0).numpy()  # HWC RGB
    tensor = torch.from_numpy(face.astype(np.float32) / 255.0).permute(2, 0, 1).unsqueeze(0).to(device)
    with torch.no_grad():
        emb = embedder(tensor).cpu().numpy()[0]
    return _normalize(emb.astype(np.float32))


def _normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def _l2_distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


@router.post("/enroll", response_model=FaceEnrollResponse)
async def enroll_face(
    payload: FaceEmbedding,
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FaceEnrollResponse:
    vec = np.array(payload.embedding, dtype=np.float32)
    if payload.distance_metric == "cosine":
        vec = _normalize(vec)

    tpl = models.UserFaceTemplate(
        user_id=current_user.user_id,
        embedding=vec.tobytes(),
        model=payload.model,
        distance_metric=payload.distance_metric or "cosine",
        threshold=payload.threshold,
        quality_score=payload.quality_score,
    )
    session.add(tpl)
    current_user.face_login_enabled = True
    await session.commit()

    count_res = await session.execute(
        select(models.UserFaceTemplate).where(models.UserFaceTemplate.user_id == current_user.user_id)
    )
    templates_count = len(count_res.scalars().all())
    return FaceEnrollResponse(templates_count=templates_count, face_login_enabled=True)


@router.post("/enroll-person-photo")
async def enroll_person_photo(
    file: UploadFile = File(...),
    first_name: str | None = Form(default=None),
    last_name: str | None = Form(default=None),
    middle_name: str | None = Form(default=None),
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    data = await file.read()
    image = np.frombuffer(data, np.uint8)
    image = cv2.imdecode(image, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image")
    emb = _extract_best_face_embedding(image)
    if emb is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No face found")
    person = models.Person(
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        embeddings=emb.astype(np.float32).tobytes(),
    )
    session.add(person)
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
    # fetch recording and camera to check permissions
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
    if not check_permission(perm, "view") and current_user.role_id != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    path = recording.file_path
    cap = cv2.VideoCapture(path)
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

    person = models.Person(
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        embeddings=emb.astype(np.float32).tobytes(),
    )
    session.add(person)
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
    snapshot_path = Path("snapshots").resolve() / f"event_{event_id}.jpg"
    if not snapshot_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    image = _read_image_file(snapshot_path)
    if image is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot read snapshot")
    emb = _extract_best_face_embedding(image)
    if emb is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No face found in snapshot")
    person = models.Person(
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        embeddings=emb.astype(np.float32).tobytes(),
    )
    session.add(person)
    await session.commit()
    await session.refresh(person)
    return {"person_id": person.person_id, "from_event": event_id, "embedding_len": len(emb)}


@router.post("/login", response_model=FaceLoginResponse)
async def face_login(
    payload: FaceLoginRequest,
    session: AsyncSession = Depends(get_session),
) -> FaceLoginResponse:
    probe = np.array(payload.embedding, dtype=np.float32)
    probe = _normalize(probe)

    result = await session.execute(select(models.UserFaceTemplate))
    templates: List[models.UserFaceTemplate] = result.scalars().all()
    if not templates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No enrolled faces")

    best_score = None
    best_tpl: models.UserFaceTemplate | None = None
    for tpl in templates:
        stored = np.frombuffer(tpl.embedding, dtype=np.float32)
        if tpl.distance_metric == "cosine":
            stored = _normalize(stored)
            score = _cosine_similarity(probe, stored)
            thr = tpl.threshold if tpl.threshold is not None else 0.4
            ok = score >= thr
            cmp_score = score
        else:
            score = _l2_distance(probe, stored)
            thr = tpl.threshold if tpl.threshold is not None else 1.0
            ok = score <= thr
            cmp_score = -score  # lower is better
        if ok and (best_score is None or cmp_score > best_score):
            best_score = cmp_score
            best_tpl = tpl

    if best_tpl is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Face not recognized")

    # Check user exists and face login enabled
    user = await session.get(models.User, best_tpl.user_id)
    if user is None or not user.face_login_enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Face login disabled for user")

    # TOTP check if enabled
    totp_method = await session.execute(
        select(models.UserMfaMethod).where(
            models.UserMfaMethod.user_id == user.user_id,
            models.UserMfaMethod.mfa_type == "totp",
            models.UserMfaMethod.is_enabled.is_(True),
        )
    )
    totp = totp_method.scalar_one_or_none()
    if totp:
        if not payload.totp_code:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP code required")
        if not verify_totp(payload.totp_code, decrypt_secret(totp.secret)):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code")

    token = create_access_token({"sub": str(user.user_id)})
    return FaceLoginResponse(access_token=token, user_id=user.user_id)
