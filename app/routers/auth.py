from datetime import datetime

import pyotp
from fastapi import APIRouter, Depends, HTTPException, status, Form
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.config import settings
from app.db import get_session
from app.dependencies import get_current_user
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    TokenResponse,
    TotpCodeRequest,
    TotpSetupResponse,
    TotpStatusResponse,
    UserOut,
)
from app.security import (
    create_access_token,
    decrypt_secret,
    encrypt_secret,
    generate_totp_secret,
    hash_password,
    verify_password,
    verify_totp,
)

router = APIRouter(prefix="/auth", tags=["auth"])


async def _log_auth_event(
    session: AsyncSession,
    user_id: int | None,
    method: str,
    success: bool,
    reason: str | None = None,
) -> None:
    event = models.AuthEvent(
        user_id=user_id,
        method=method,
        success=success,
        reason=reason,
    )
    session.add(event)
    await session.commit()


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    result = await session.execute(select(models.User).where(models.User.login == payload.login))
    user = result.scalar_one_or_none()
    if user is None:
        await _log_auth_event(session, None, method="password", success=False, reason="user_not_found")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not verify_password(payload.password, user.password_hash):
        await _log_auth_event(session, user.user_id, method="password", success=False, reason="invalid_password")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Check TOTP requirement
    result_totp = await session.execute(
        select(models.UserMfaMethod).where(
            models.UserMfaMethod.user_id == user.user_id,
            models.UserMfaMethod.mfa_type == "totp",
            models.UserMfaMethod.is_enabled.is_(True),
        )
    )
    totp_method = result_totp.scalar_one_or_none()
    method_used = "password"
    if totp_method and totp_method.secret:
        method_used = "password+totp"
        if not payload.totp_code:
            await _log_auth_event(session, user.user_id, method=method_used, success=False, reason="totp_required")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP code required")
        if not verify_totp(payload.totp_code, decrypt_secret(totp_method.secret)):
            await _log_auth_event(session, user.user_id, method=method_used, success=False, reason="invalid_totp")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code")

    token = create_access_token({"sub": str(user.user_id)})
    await _log_auth_event(session, user.user_id, method=method_used, success=True)
    return TokenResponse(access_token=token, must_change_password=user.must_change_password)


@router.post("/login-form", response_model=TokenResponse, summary="OAuth2 password-form login for Swagger UI")
async def login_form(
    form_data: OAuth2PasswordRequestForm = Depends(),
    totp_code: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Same as /auth/login but accepts form-data (username/password), used by Swagger UI."""
    payload = LoginRequest(login=form_data.username, password=form_data.password, totp_code=totp_code)
    return await login(payload=payload, session=session)


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid current password")
    current_user.password_hash = hash_password(payload.new_password)
    current_user.must_change_password = False
    await session.commit()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(current_user: models.User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


@router.post("/totp/setup", response_model=TotpSetupResponse)
async def totp_setup(
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TotpSetupResponse:
    secret = generate_totp_secret()
    provisioning_uri = pyotp.TOTP(secret).provisioning_uri(name=current_user.login, issuer_name=settings.app_name)

    result = await session.execute(
        select(models.UserMfaMethod).where(
            models.UserMfaMethod.user_id == current_user.user_id,
            models.UserMfaMethod.mfa_type == "totp",
        )
    )
    method = result.scalar_one_or_none()
    if method:
        method.secret = encrypt_secret(secret)
        method.is_enabled = False
        method.destination = None
    else:
        method = models.UserMfaMethod(
            user_id=current_user.user_id,
            mfa_type="totp",
            secret=encrypt_secret(secret),
            is_enabled=False,
        )
        session.add(method)
    await session.commit()
    return TotpSetupResponse(secret=secret, provisioning_uri=provisioning_uri)


@router.post("/totp/activate", response_model=TotpStatusResponse)
async def totp_activate(
    payload: TotpCodeRequest,
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TotpStatusResponse:
    result = await session.execute(
        select(models.UserMfaMethod).where(
            models.UserMfaMethod.user_id == current_user.user_id,
            models.UserMfaMethod.mfa_type == "totp",
        )
    )
    method = result.scalar_one_or_none()
    if method is None or method.secret is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP not initialized")

    if not verify_totp(payload.code, decrypt_secret(method.secret)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

    method.is_enabled = True
    method.last_used_at = datetime.utcnow()
    await session.commit()
    return TotpStatusResponse(enabled=True)


@router.post("/totp/disable", response_model=TotpStatusResponse)
async def totp_disable(
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TotpStatusResponse:
    result = await session.execute(
        select(models.UserMfaMethod).where(
            models.UserMfaMethod.user_id == current_user.user_id,
            models.UserMfaMethod.mfa_type == "totp",
        )
    )
    method = result.scalar_one_or_none()
    if method is None:
        return TotpStatusResponse(enabled=False)
    method.is_enabled = False
    method.secret = None
    await session.commit()
    return TotpStatusResponse(enabled=False)
