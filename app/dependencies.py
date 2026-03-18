from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.security import decode_token, verify_api_key

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login-form")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login-form", auto_error=False)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        sub: str | None = payload.get("sub")
        if sub is None:
            raise credentials_exception
        user_id = int(sub)
    except (JWTError, ValueError):
        raise credentials_exception

    result = await session.execute(select(models.User).where(models.User.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
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
    return await get_current_user(token=raw_token, session=session)


async def get_service_scopes(
    api_key: str,
    session: AsyncSession = Depends(get_session),
) -> list[str]:
    result = await session.execute(select(models.ApiKey).where(models.ApiKey.is_active.is_(True)))
    keys = result.scalars().all()
    for k in keys:
        if k.expires_at and k.expires_at < __import__("datetime").datetime.utcnow():
            continue
        if verify_api_key(api_key, k.key_hash):
            return k.scopes.split(",") if k.scopes else []
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )
