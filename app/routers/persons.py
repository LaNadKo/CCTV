import base64
from typing import List

import cv2
import httpx
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.permissions import is_admin
from app.processor_media import get_processor_media_base_url, get_processor_media_headers
from app.schemas.persons import PersonCreate, PersonOut, PersonUpdate
from app.routers.face import _extract_best_face_embedding

router = APIRouter(prefix="/persons", tags=["persons"])


async def _ensure_admin(user: models.User, session: AsyncSession) -> None:
    if is_admin(user):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


_EMB_ACCEPT_MIN = 0.6
_EMB_DUPLICATE_MAX = 0.9


def _cos_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-6))


async def _existing_embeddings(session: AsyncSession, person_id: int) -> list[np.ndarray]:
    res = await session.execute(
        select(models.PersonEmbedding.embedding)
        .where(models.PersonEmbedding.person_id == person_id)
    )
    rows = res.scalars().all()
    embeddings: list[np.ndarray] = []
    for raw in rows:
        arr = np.frombuffer(raw, dtype=np.float32)
        if arr.size:
            embeddings.append(arr)
    return embeddings


def _should_add_embedding(emb: np.ndarray, existing: list[np.ndarray]) -> tuple[bool, str, float | None]:
    if not existing:
        return True, "added", None
    sims = [_cos_sim(emb, e) for e in existing]
    max_sim = max(sims) if sims else None
    if max_sim is not None and max_sim >= _EMB_DUPLICATE_MAX:
        return False, "duplicate", max_sim
    if max_sim is not None and max_sim < _EMB_ACCEPT_MIN:
        return False, "mismatch", max_sim
    return True, "added", max_sim


async def _embedding_count(session: AsyncSession, person_id: int) -> int:
    res = await session.execute(
        select(func.count(models.PersonEmbedding.person_embedding_id))
        .where(models.PersonEmbedding.person_id == person_id)
    )
    return int(res.scalar_one() or 0)


async def _pick_processor_for_embedding(
    session: AsyncSession,
    camera_id: int | None,
) -> models.Processor | None:
    if camera_id is not None:
        res = await session.execute(
            select(models.Processor)
            .join(
                models.ProcessorCameraAssignment,
                models.ProcessorCameraAssignment.processor_id == models.Processor.processor_id,
            )
            .where(
                models.ProcessorCameraAssignment.camera_id == camera_id,
                models.Processor.status == "online",
            )
            .order_by(
                models.ProcessorCameraAssignment.priority.desc(),
                models.Processor.last_heartbeat.desc(),
                models.Processor.processor_id.desc(),
            )
            .limit(1)
        )
        assigned = res.scalar_one_or_none()
        if assigned is not None:
            return assigned

    res = await session.execute(
        select(models.Processor)
        .where(models.Processor.status == "online")
        .order_by(models.Processor.last_heartbeat.desc(), models.Processor.processor_id.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def _extract_best_face_embedding_via_processor(
    session: AsyncSession,
    image: np.ndarray,
    camera_id: int | None,
) -> np.ndarray | None:
    proc = await _pick_processor_for_embedding(session, camera_id)
    if proc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Face recognition unavailable: no online processor available for embedding extraction",
        )

    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image")

    url = f"{get_processor_media_base_url(proc)}/embeddings/extract"
    headers = {
        **get_processor_media_headers(proc),
        "Content-Type": "image/jpeg",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(url, headers=headers, content=buf.tobytes())
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Face recognition unavailable: processor media endpoint is unreachable ({exc})",
        ) from exc

    payload = {}
    if res.content:
        try:
            payload = res.json()
        except ValueError:
            payload = {}

    if not res.is_success:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if res.status_code == status.HTTP_404_NOT_FOUND:
            detail = "Face recognition unavailable: installed processor is outdated, update Processor to the latest version"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(detail or "Processor failed to extract face embedding"),
        )

    emb_b64 = payload.get("embedding_b64") if isinstance(payload, dict) else None
    if not emb_b64:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processor returned empty face embedding",
        )
    emb = np.frombuffer(base64.b64decode(emb_b64), dtype=np.float32)
    if emb.size == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processor returned invalid face embedding",
        )
    return emb


@router.get("", response_model=List[PersonOut])
async def list_persons(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> List[PersonOut]:
    await _ensure_admin(current_user, session)
    counts = (
        select(
            models.PersonEmbedding.person_id,
            func.count(models.PersonEmbedding.person_embedding_id).label("cnt"),
        )
        .group_by(models.PersonEmbedding.person_id)
        .subquery()
    )
    res = await session.execute(
        select(models.Person, func.coalesce(counts.c.cnt, 0))
        .outerjoin(counts, counts.c.person_id == models.Person.person_id)
        .order_by(models.Person.person_id)
    )
    items: List[PersonOut] = []
    for person, count in res.all():
        items.append(
            PersonOut(
                person_id=person.person_id,
                first_name=person.first_name,
                last_name=person.last_name,
                middle_name=person.middle_name,
                embeddings_count=int(count or 0),
                created_at=person.created_at,
            )
        )
    return items


@router.post("", response_model=PersonOut, status_code=status.HTTP_201_CREATED)
async def create_person(
    payload: PersonCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> PersonOut:
    await _ensure_admin(current_user, session)
    person = models.Person(
        first_name=payload.first_name,
        last_name=payload.last_name,
        middle_name=payload.middle_name,
    )
    session.add(person)
    await session.commit()
    await session.refresh(person)
    return PersonOut(
        person_id=person.person_id,
        first_name=person.first_name,
        last_name=person.last_name,
        middle_name=person.middle_name,
        embeddings_count=0,
        created_at=person.created_at,
    )


@router.patch("/{person_id}", response_model=PersonOut)
async def update_person(
    person_id: int,
    payload: PersonUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> PersonOut:
    await _ensure_admin(current_user, session)
    person = await session.get(models.Person, person_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    if payload.first_name is not None:
        person.first_name = payload.first_name
    if payload.last_name is not None:
        person.last_name = payload.last_name
    if payload.middle_name is not None:
        person.middle_name = payload.middle_name
    await session.commit()
    await session.refresh(person)
    count = await _embedding_count(session, person.person_id)
    return PersonOut(
        person_id=person.person_id,
        first_name=person.first_name,
        last_name=person.last_name,
        middle_name=person.middle_name,
        embeddings_count=count,
        created_at=person.created_at,
    )


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(
    person_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    person = await session.get(models.Person, person_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    await session.delete(person)
    await session.commit()
    return None


@router.post("/{person_id}/embeddings/photo")
async def add_embedding_from_photo(
    person_id: int,
    file: UploadFile = File(...),
    camera_id: int | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    person = await session.get(models.Person, person_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    data = await file.read()
    image = np.frombuffer(data, np.uint8)
    image = cv2.imdecode(image, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image")
    try:
        emb = _extract_best_face_embedding(image)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE and "torch" in str(exc.detail).lower():
            emb = await _extract_best_face_embedding_via_processor(session, image, camera_id)
        else:
            raise
    if emb is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No face found")
    existing = await _existing_embeddings(session, person.person_id)
    ok, status_name, max_sim = _should_add_embedding(emb, existing)
    if ok:
        session.add(
            models.PersonEmbedding(
                person_id=person.person_id,
                embedding=emb.astype(np.float32).tobytes(),
                source="photo",
            )
        )
        if not person.embeddings:
            person.embeddings = emb.astype(np.float32).tobytes()
        await session.commit()
    return {"person_id": person.person_id, "embedding_len": len(emb), "status": status_name, "max_similarity": max_sim}
