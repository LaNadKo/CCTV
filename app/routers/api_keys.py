from datetime import datetime
import secrets
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.permissions import is_home_admin
from app.schemas.api_keys import ApiKeyCreate, ApiKeyOut, ApiKeyPlain
from app.security import hash_api_key, verify_api_key

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


async def _ensure_admin(user: models.User, session: AsyncSession) -> None:
    if user.role_id == 1:
        return
    if await is_home_admin(session, user.user_id):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


def _normalize_scopes(scopes: List[str]) -> List[str]:
    return sorted(set(s.strip() for s in scopes if s.strip()))


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
    out: List[ApiKeyOut] = []
    for k in keys:
        out.append(
            ApiKeyOut(
                api_key_id=k.api_key_id,
                description=k.description,
                scopes=k.scopes.split(",") if k.scopes else [],
                is_active=k.is_active,
            )
        )
    return out
