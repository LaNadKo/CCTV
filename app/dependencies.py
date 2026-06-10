import hashlib
import time

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.config import settings
from app.db import get_session
from app.security import decode_token, verify_api_key

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login-form")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login-form", auto_error=False)
_service_scope_cache: dict[str, tuple[float, int, list[str]]] = {}
_SERVICE_SCOPE_CACHE_TTL = 300.0


def clear_service_scope_cache() -> None:
    _service_scope_cache.clear()


def _service_scope_cache_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


async def _user_from_token(
    token: str,
    session: AsyncSession = Depends(get_session),
    *,
    require_media_token: bool = False,
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        if not require_media_token and payload.get("token_use") == "media":
            raise credentials_exception
        if require_media_token and payload.get("token_use") != "media" and not settings.allow_legacy_query_tokens:
            raise credentials_exception
        sub: str | None = payload.get("sub")
        if sub is None:
            raise credentials_exception
        user_id = int(sub)
    except (InvalidTokenError, ValueError):
        raise credentials_exception

    result = await session.execute(select(models.User).where(models.User.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> models.User:
    return await _user_from_token(token, session)


async def get_current_user_optional(
    token: str | None = Depends(oauth2_scheme_optional),
    session: AsyncSession = Depends(get_session),
) -> models.User | None:
    if not token:
        return None
    return await _user_from_token(token, session)


async def get_current_user_allow_query(
    request: Request,
    token: str | None = Depends(oauth2_scheme_optional),
    session: AsyncSession = Depends(get_session),
) -> models.User:
    """
    Auth dependency that also accepts token/access_token in query params.
    Useful for <img>/<video> streaming requests where setting headers is hard.
    """
    raw_token = token or request.query_params.get("token") or request.query_params.get("access_token")
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _user_from_token(raw_token, session, require_media_token=token is None)


async def get_service_identity(
    api_key: str,
    session: AsyncSession = Depends(get_session),
) -> tuple[int, list[str]]:
    now = time.monotonic()
    cache_key = _service_scope_cache_key(api_key)
    cached = _service_scope_cache.get(cache_key)
    if cached and cached[0] > now:
        return cached[1], cached[2]

    result = await session.execute(
        select(models.ApiKey.api_key_id, models.ApiKey.key_hash, models.ApiKey.scopes, models.ApiKey.expires_at)
        .where(models.ApiKey.is_active.is_(True))
    )
    keys = result.all()
    for k in keys:
        api_key_id, key_hash, scopes_raw, expires_at = k
        if expires_at and expires_at < __import__("datetime").datetime.utcnow():
            continue
        if verify_api_key(api_key, key_hash):
            scopes = scopes_raw.split(",") if scopes_raw else []
            _service_scope_cache[cache_key] = (now + _SERVICE_SCOPE_CACHE_TTL, api_key_id, scopes)
            if len(_service_scope_cache) > 256:
                expired = [raw for raw, (deadline, _, _) in _service_scope_cache.items() if deadline <= now]
                for raw in expired:
                    _service_scope_cache.pop(raw, None)
            return api_key_id, scopes
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )


async def get_service_scopes(
    api_key: str,
    session: AsyncSession = Depends(get_session),
) -> list[str]:
    _api_key_id, scopes = await get_service_identity(api_key, session)
    return scopes
