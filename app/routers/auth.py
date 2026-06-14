from datetime import datetime

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status, Form
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.config import settings
from app.db import get_session
from app.dependencies import get_current_user
from app.rate_limit import check_rate_limit, client_ip
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MediaTokenResponse,
    ProfileUpdateRequest,
    TokenResponse,
    TotpCodeRequest,
    TotpDisableRequest,
    TotpSetupRequest,
    TotpSetupResponse,
    TotpStatusResponse,
    UserOut,
)
from app.security import (
    create_access_token,
    create_media_token,
    decrypt_secret,
    encrypt_secret,
    generate_totp_secret,
    hash_password,
    verify_password,
    verify_totp_counter,
)

router = APIRouter(prefix="/auth", tags=["auth"])


async def _log_auth_event(
    session: AsyncSession,
    user_id: int | None,
    method: str,
    success: bool,
    reason: str | None = None,
    request: Request | None = None,
) -> None:
    event = models.AuthEvent(
        user_id=user_id,
        method=method,
        success=success,
        reason=reason,
        source_ip=client_ip(request) if request else None,
        user_agent=request.headers.get("user-agent", "")[:255] if request else None,
    )
    session.add(event)
    await session.commit()


async def _get_totp_method(
    session: AsyncSession,
    user_id: int,
    *,
    lock: bool = False,
) -> models.UserMfaMethod | None:
    stmt = (
        select(models.UserMfaMethod)
        .where(
            models.UserMfaMethod.user_id == user_id,
            models.UserMfaMethod.mfa_type == "totp",
            models.UserMfaMethod.is_enabled.is_(True),
        )
    )
    if lock:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def _verify_totp_once(code: str, method: models.UserMfaMethod) -> bool:
    if method.secret is None:
        return False
    counter = verify_totp_counter(code, decrypt_secret(method.secret))
    if counter is None:
        return False
    previous = method.last_totp_counter
    if previous is not None and counter <= previous:
        return False
    method.last_totp_counter = counter
    method.last_used_at = datetime.utcnow()
    return True


def _user_out(user: models.User, *, totp_enabled: bool) -> UserOut:
    return UserOut(
        user_id=user.user_id,
        login=user.login,
        role_id=user.role_id,
        first_name=user.first_name,
        last_name=user.last_name,
        middle_name=user.middle_name,
        must_change_password=user.must_change_password,
        totp_enabled=totp_enabled,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    check_rate_limit(
        request,
        f"auth-login:{payload.login.strip().lower()}",
        attempts=settings.auth_rate_limit_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
        detail="Too many login attempts",
    )
    result = await session.execute(select(models.User).where(models.User.login == payload.login))
    user = result.scalar_one_or_none()
    if user is None:
        await _log_auth_event(session, None, method="password", success=False, reason="user_not_found", request=request)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not verify_password(payload.password, user.password_hash):
        await _log_auth_event(session, user.user_id, method="password", success=False, reason="invalid_password", request=request)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    totp_method = await _get_totp_method(session, user.user_id, lock=True)
    method_used = "password"
    if totp_method and totp_method.secret:
        method_used = "password+totp"
        if not payload.totp_code:
            await _log_auth_event(session, user.user_id, method=method_used, success=False, reason="totp_required", request=request)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP code required")
        if not _verify_totp_once(payload.totp_code, totp_method):
            await _log_auth_event(session, user.user_id, method=method_used, success=False, reason="invalid_totp", request=request)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code")

    token = create_access_token({"sub": str(user.user_id), "token_version": user.token_version})
    await _log_auth_event(session, user.user_id, method=method_used, success=True, request=request)
    return TokenResponse(
        access_token=token,
        media_access_token=(
            None
            if user.must_change_password
            else create_media_token(user.user_id, user.token_version)
        ),
        media_token_expires_seconds=settings.media_token_expires_seconds,
        must_change_password=user.must_change_password,
    )


@router.post("/login-form", response_model=TokenResponse, summary="OAuth2 password-form login for Swagger UI")
async def login_form(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    totp_code: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    payload = LoginRequest(login=form_data.username, password=form_data.password, totp_code=totp_code)
    return await login(payload=payload, request=request, session=session)


@router.post("/change-password", response_model=TokenResponse)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    check_rate_limit(
        request,
        f"change-password:{current_user.user_id}",
        attempts=settings.auth_rate_limit_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
        detail="Too many password change attempts",
    )
    if not verify_password(payload.current_password, current_user.password_hash):
        await _log_auth_event(
            session,
            current_user.user_id,
            method="password",
            success=False,
            reason="change_password_invalid_current_password",
            request=request,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid current password")
    current_user.password_hash = hash_password(payload.new_password)
    current_user.must_change_password = False
    current_user.token_version = int(current_user.token_version or 0) + 1
    await _log_auth_event(
        session,
        current_user.user_id,
        method="password",
        success=True,
        reason="password_changed",
        request=request,
    )
    await session.commit()
    token = create_access_token(
        {
            "sub": str(current_user.user_id),
            "token_version": current_user.token_version,
        }
    )
    return TokenResponse(
        access_token=token,
        media_access_token=create_media_token(
            current_user.user_id,
            current_user.token_version,
        ),
        media_token_expires_seconds=settings.media_token_expires_seconds,
        must_change_password=False,
    )


@router.get("/me", response_model=UserOut)
async def me(
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    totp_enabled = await _get_totp_method(session, current_user.user_id) is not None
    return _user_out(current_user, totp_enabled=totp_enabled)


@router.post("/media-token", response_model=MediaTokenResponse)
async def refresh_media_token(
    current_user: models.User = Depends(get_current_user),
) -> MediaTokenResponse:
    return MediaTokenResponse(
        media_access_token=create_media_token(current_user.user_id, current_user.token_version),
        media_token_expires_seconds=settings.media_token_expires_seconds,
    )


@router.patch("/profile", response_model=UserOut)
async def update_profile(
    payload: ProfileUpdateRequest,
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    current_user.first_name = payload.first_name.strip() if payload.first_name else None
    current_user.last_name = payload.last_name.strip() if payload.last_name else None
    current_user.middle_name = payload.middle_name.strip() if payload.middle_name else None
    await session.commit()
    await session.refresh(current_user)
    totp_enabled = await _get_totp_method(session, current_user.user_id) is not None
    return _user_out(current_user, totp_enabled=totp_enabled)


@router.get("/totp/status", response_model=TotpStatusResponse)
async def totp_status(
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TotpStatusResponse:
    method = await _get_totp_method(session, current_user.user_id)
    return TotpStatusResponse(enabled=bool(method and method.is_enabled))


@router.post("/totp/setup", response_model=TotpSetupResponse)
async def totp_setup(
    payload: TotpSetupRequest,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TotpSetupResponse:
    check_rate_limit(
        request,
        f"totp-setup:{current_user.user_id}",
        attempts=settings.auth_rate_limit_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
        detail="Too many TOTP setup attempts",
    )
    if not verify_password(payload.current_password, current_user.password_hash):
        await _log_auth_event(
            session,
            current_user.user_id,
            method="password",
            success=False,
            reason="totp_setup_invalid_password",
            request=request,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid current password")
    secret = generate_totp_secret()
    provisioning_uri = pyotp.TOTP(secret).provisioning_uri(name=current_user.login, issuer_name=settings.app_name)

    result = await session.execute(
        select(models.UserMfaMethod).where(
            models.UserMfaMethod.user_id == current_user.user_id,
            models.UserMfaMethod.mfa_type == "totp",
        ).with_for_update()
    )
    method = result.scalar_one_or_none()
    if method and method.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Disable the current TOTP method before creating a new one",
        )
    if method:
        method.secret = encrypt_secret(secret)
        method.is_enabled = False
        method.destination = None
        method.last_totp_counter = None
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
    request: Request,
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TotpStatusResponse:
    check_rate_limit(
        request,
        f"totp-activate:{current_user.user_id}",
        attempts=settings.auth_rate_limit_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
        detail="Too many TOTP attempts",
    )
    result = await session.execute(
        select(models.UserMfaMethod).where(
            models.UserMfaMethod.user_id == current_user.user_id,
            models.UserMfaMethod.mfa_type == "totp",
        ).with_for_update()
    )
    method = result.scalar_one_or_none()
    if method is None or method.secret is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP not initialized")

    if not verify_password(payload.current_password, current_user.password_hash):
        await _log_auth_event(
            session,
            current_user.user_id,
            method="password+totp",
            success=False,
            reason="totp_activate_invalid_password",
            request=request,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid current password")

    if not _verify_totp_once(payload.code, method):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

    method.is_enabled = True
    await session.commit()
    return TotpStatusResponse(enabled=True)


@router.post("/totp/disable", response_model=TotpStatusResponse)
async def totp_disable(
    payload: TotpDisableRequest,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TotpStatusResponse:
    check_rate_limit(
        request,
        f"totp-disable:{current_user.user_id}",
        attempts=settings.auth_rate_limit_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
        detail="Too many TOTP attempts",
    )
    result = await session.execute(
        select(models.UserMfaMethod).where(
            models.UserMfaMethod.user_id == current_user.user_id,
            models.UserMfaMethod.mfa_type == "totp",
        ).with_for_update()
    )
    method = result.scalar_one_or_none()
    if method is None or not method.is_enabled:
        return TotpStatusResponse(enabled=False)

    if not verify_password(payload.current_password, current_user.password_hash):
        await _log_auth_event(
            session,
            current_user.user_id,
            method="password+totp",
            success=False,
            reason="totp_disable_invalid_password",
            request=request,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid current password")

    if not _verify_totp_once(payload.code, method):
        await _log_auth_event(
            session,
            current_user.user_id,
            method="password+totp",
            success=False,
            reason="totp_disable_invalid_totp",
            request=request,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")

    method.is_enabled = False
    method.secret = None
    await _log_auth_event(
        session,
        current_user.user_id,
        method="password+totp",
        success=True,
        reason="totp_disabled",
        request=request,
    )
    await session.commit()
    return TotpStatusResponse(enabled=False)
