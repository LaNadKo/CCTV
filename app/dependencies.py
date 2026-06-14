import hashlib
import time
from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.config import settings
from app.db import get_session
from app.security import decode_token, hash_api_key, verify_api_key

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login-form")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login-form", auto_error=False)
_service_scope_cache: dict[str, tuple[float, int, list[str]]] = {}
_SERVICE_SCOPE_CACHE_TTL = 30.0
_PASSWORD_ROTATION_ALLOWED_PATHS = frozenset(
    {
        "/auth/me",
        "/auth/change-password",
    }
)


def clear_service_scope_cache() -> None:
    _service_scope_cache.clear()


def _service_scope_cache_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _enforce_password_rotation(user: models.User, request: Request) -> None:
    if bool(getattr(user, "must_change_password", False)) and request.url.path not in _PASSWORD_ROTATION_ALLOWED_PATHS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required",
        )


async def _user_from_token(
    token: str,
    session: AsyncSession = Depends(get_session),
    *,
    require_media_token: bool = False,
    allow_media_token: bool = False,
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        token_use = payload.get("token_use")
        if token_use == "media" and not (require_media_token or allow_media_token):
            raise credentials_exception
        if require_media_token and token_use != "media" and not settings.allow_legacy_query_tokens:
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
    expected_token_version = int(getattr(user, "token_version", 0) or 0)
    token_version = payload.get("token_version")
    if token_version is None:
        if expected_token_version != 0:
            raise credentials_exception
    else:
        try:
            parsed_token_version = int(token_version)
        except (TypeError, ValueError):
            raise credentials_exception
        if parsed_token_version != expected_token_version:
            raise credentials_exception
    return user


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> models.User:
    user = await _user_from_token(token, session)
    _enforce_password_rotation(user, request)
    return user


async def get_current_user_optional(
    request: Request,
    token: str | None = Depends(oauth2_scheme_optional),
    session: AsyncSession = Depends(get_session),
) -> models.User | None:
    if not token:
        return None
    user = await _user_from_token(token, session)
    _enforce_password_rotation(user, request)
    return user


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
    user = await _user_from_token(
        raw_token,
        session,
        require_media_token=token is None,
        allow_media_token=token is not None,
    )
    _enforce_password_rotation(user, request)
    return user


async def get_service_identity(
    api_key: str,
    session: AsyncSession = Depends(get_session),
) -> tuple[int, list[str]]:
    now = time.monotonic()
    cache_key = _service_scope_cache_key(api_key)
    cached = _service_scope_cache.get(cache_key)
    if cached and cached[0] > now:
        return cached[1], cached[2]

    deterministic_hash = hash_api_key(api_key)
    direct_result = await session.execute(
        select(models.ApiKey.api_key_id, models.ApiKey.scopes, models.ApiKey.expires_at)
        .where(
            models.ApiKey.is_active.is_(True),
            models.ApiKey.key_hash == deterministic_hash,
        )
        .limit(1)
    )
    direct = direct_result.first()
    if direct is not None:
        api_key_id, scopes_raw, expires_at = direct
        utc_now = datetime.utcnow()
        if not expires_at or expires_at >= utc_now:
            scopes = scopes_raw.split(",") if scopes_raw else []
            cache_deadline = now + _SERVICE_SCOPE_CACHE_TTL
            if expires_at:
                cache_deadline = min(
                    cache_deadline,
                    now + max((expires_at - utc_now).total_seconds(), 0.0),
                )
            _service_scope_cache[cache_key] = (cache_deadline, api_key_id, scopes)
            return api_key_id, scopes

    result = await session.execute(
        select(models.ApiKey.api_key_id, models.ApiKey.key_hash, models.ApiKey.scopes, models.ApiKey.expires_at)
        .where(
            models.ApiKey.is_active.is_(True),
            ~models.ApiKey.key_hash.startswith("sha256:"),
        )
    )
    keys = result.all()
    for k in keys:
        api_key_id, key_hash, scopes_raw, expires_at = k
        utc_now = datetime.utcnow()
        if expires_at and expires_at < utc_now:
            continue
        if verify_api_key(api_key, key_hash):
            scopes = scopes_raw.split(",") if scopes_raw else []
            key_row = await session.get(models.ApiKey, api_key_id)
            if key_row is not None:
                key_row.key_hash = deterministic_hash
                await session.commit()
            cache_deadline = now + _SERVICE_SCOPE_CACHE_TTL
            if expires_at:
                cache_deadline = min(cache_deadline, now + max((expires_at - utc_now).total_seconds(), 0.0))
            _service_scope_cache[cache_key] = (cache_deadline, api_key_id, scopes)
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
