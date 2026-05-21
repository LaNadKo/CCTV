from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pyotp
import jwt
from passlib.context import CryptContext
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
api_key_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
_FERNET_PREFIX = "fernet:"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    data: Dict[str, Any],
    expires_minutes: Optional[int] = None,
    expires_seconds: Optional[int] = None,
) -> str:
    to_encode = data.copy()
    if expires_seconds is not None:
        expire = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=expires_minutes if expires_minutes is not None else settings.jwt_expires_minutes
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return encoded_jwt


def create_media_token(user_id: int) -> str:
    return create_access_token(
        {"sub": str(user_id), "token_use": "media"},
        expires_seconds=settings.media_token_expires_seconds,
    )


def decode_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def _get_fernet() -> Fernet | None:
    key = settings.totp_encryption_key
    if key:
        try:
            return Fernet(key.encode())
        except Exception:
            return None
    return None


def encrypt_secret(secret: str) -> str:
    if not secret:
        return secret
    if secret.startswith(_FERNET_PREFIX):
        return secret
    f = _get_fernet()
    if not f:
        return secret
    return _FERNET_PREFIX + f.encrypt(secret.encode()).decode()


def decrypt_secret(secret: str) -> str:
    if not secret:
        return secret
    f = _get_fernet()
    if not f:
        return secret
    token = secret[len(_FERNET_PREFIX):] if secret.startswith(_FERNET_PREFIX) else secret
    try:
        return f.decrypt(token.encode()).decode()
    except InvalidToken:
        return secret


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(code: str, secret: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def hash_api_key(raw_key: str) -> str:
    return api_key_context.hash(raw_key)


def verify_api_key(raw_key: str, hashed_key: str) -> bool:
    return api_key_context.verify(raw_key, hashed_key)
