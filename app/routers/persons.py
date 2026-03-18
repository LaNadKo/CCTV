from pathlib import Path
from typing import List

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.permissions import is_home_admin
from app.schemas.persons import PersonCreate, PersonOut, PersonUpdate
from app.routers.face import _extract_best_face_embedding

router = APIRouter(prefix="/persons", tags=["persons"])


async def _ensure_admin(user: models.User, session: AsyncSession) -> None:
    if user.role_id == 1:
        return
    if await is_home_admin(session, user.user_id):
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


@router.post("/{person_id}/embeddings/photo")
async def add_embedding_from_photo(
    person_id: int,
    file: UploadFile = File(...),
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
    emb = _extract_best_face_embedding(image)
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
