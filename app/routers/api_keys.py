from datetime import datetime
import secrets
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.permissions import is_admin
from app.schemas.api_keys import ApiKeyCreate, ApiKeyOut, ApiKeyPlain, ApiKeyUpdate
from app.security import hash_api_key, verify_api_key

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


async def _ensure_admin(user: models.User, session: AsyncSession) -> None:
    if is_admin(user):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


def _normalize_scopes(scopes: List[str]) -> List[str]:
    return sorted(set(s.strip() for s in scopes if s.strip()))


def _serialize_key(obj: models.ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        api_key_id=obj.api_key_id,
        description=obj.description,
        scopes=obj.scopes.split(",") if obj.scopes else [],
        is_active=obj.is_active,
        expires_at=obj.expires_at.isoformat() if obj.expires_at else None,
        created_at=obj.created_at.isoformat() if obj.created_at else None,
    )


@router.post("", response_model=ApiKeyPlain, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> ApiKeyPlain:
    await _ensure_admin(current_user, session)
    raw_key = secrets.token_urlsafe(32)
    key_hash = hash_api_key(raw_key)
    scopes = ",".join(_normalize_scopes(payload.scopes))
    expires_at = datetime.fromisoformat(payload.expires_at) if payload.expires_at else None
    obj = models.ApiKey(
        key_hash=key_hash,
        description=payload.description,
        scopes=scopes,
        expires_at=expires_at,
    )
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    return ApiKeyPlain(api_key=raw_key, api_key_id=obj.api_key_id)


@router.get("", response_model=List[ApiKeyOut])
async def list_api_keys(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> List[ApiKeyOut]:
    await _ensure_admin(current_user, session)
    res = await session.execute(select(models.ApiKey))
    keys = res.scalars().all()
    return [_serialize_key(k) for k in keys]


@router.patch("/{api_key_id}", response_model=ApiKeyOut)
async def update_api_key(
    api_key_id: int,
    payload: ApiKeyUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> ApiKeyOut:
    await _ensure_admin(current_user, session)
    obj = await session.get(models.ApiKey, api_key_id)
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    if payload.description is not None:
        obj.description = payload.description
    if payload.scopes is not None:
        obj.scopes = ",".join(_normalize_scopes(payload.scopes))
    if payload.is_active is not None:
        obj.is_active = payload.is_active
    if payload.expires_at is not None:
        obj.expires_at = datetime.fromisoformat(payload.expires_at) if payload.expires_at else None
    await session.commit()
    await session.refresh(obj)
    return _serialize_key(obj)


@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    api_key_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    obj = await session.get(models.ApiKey, api_key_id)
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    await session.delete(obj)
    await session.commit()
    return None
