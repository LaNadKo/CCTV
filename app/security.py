from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from typing import Any, Dict, Optional

import pyotp
import jwt
from passlib.context import CryptContext
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
api_key_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
_FERNET_PREFIX = "fernet:"
_API_KEY_SHA256_PREFIX = "sha256:"


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


def create_media_token(user_id: int, token_version: int = 0) -> str:
    return create_access_token(
        {"sub": str(user_id), "token_use": "media", "token_version": int(token_version or 0)},
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
        raise RuntimeError("TOTP_ENCRYPTION_KEY is required to store application secrets")
    return _FERNET_PREFIX + f.encrypt(secret.encode()).decode()


def decrypt_secret(secret: str) -> str:
    if not secret:
        return secret
    f = _get_fernet()
    if not f:
        if secret.startswith(_FERNET_PREFIX):
            raise RuntimeError("TOTP_ENCRYPTION_KEY is required to decrypt application secrets")
        return secret
    token = secret[len(_FERNET_PREFIX):] if secret.startswith(_FERNET_PREFIX) else secret
    try:
        return f.decrypt(token.encode()).decode()
    except InvalidToken:
        return secret


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(code: str, secret: str) -> bool:
    return verify_totp_counter(code, secret) is not None


def verify_totp_counter(code: str, secret: str) -> int | None:
    normalized = str(code or "").replace(" ", "").strip()
    if not normalized:
        return None
    totp = pyotp.TOTP(secret)
    interval = max(1, int(getattr(totp, "interval", 30) or 30))
    now = datetime.now(timezone.utc)
    for offset in (-1, 0, 1):
        candidate_time = now + timedelta(seconds=offset * interval)
        expected = totp.at(candidate_time)
        if hmac.compare_digest(expected, normalized):
            return int(candidate_time.timestamp() // interval)
    return None


def hash_api_key(raw_key: str) -> str:
    return _API_KEY_SHA256_PREFIX + hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def verify_api_key(raw_key: str, hashed_key: str) -> bool:
    if hashed_key.startswith(_API_KEY_SHA256_PREFIX):
        return hmac.compare_digest(hash_api_key(raw_key), hashed_key)
    return api_key_context.verify(raw_key, hashed_key)
