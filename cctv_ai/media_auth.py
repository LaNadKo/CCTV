from __future__ import annotations

import base64
import hashlib
import hmac
import time


SCOPED_MEDIA_TOKEN_VERSION = "v1"
DEFAULT_SCOPED_MEDIA_TOKEN_TTL_SECONDS = 120
MAX_SCOPED_MEDIA_TOKEN_TTL_SECONDS = 600


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def issue_scoped_media_token(
    secret: str,
    path: str,
    *,
    ttl_seconds: int = DEFAULT_SCOPED_MEDIA_TOKEN_TTL_SECONDS,
    now: float | None = None,
) -> str:
    if not secret:
        raise ValueError("Media token secret is required")
    if not path.startswith("/"):
        raise ValueError("Media path must be absolute")
    ttl = min(MAX_SCOPED_MEDIA_TOKEN_TTL_SECONDS, max(1, int(ttl_seconds)))
    expires_at = int((time.time() if now is None else now) + ttl)
    encoded_path = _b64url_encode(path.encode("utf-8"))
    payload = f"{SCOPED_MEDIA_TOKEN_VERSION}.{expires_at}.{encoded_path}"
    signature = hmac.new(
        secret.encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{payload}.{_b64url_encode(signature)}"


def verify_scoped_media_token(
    secret: str,
    token: str,
    path: str,
    *,
    now: float | None = None,
) -> bool:
    if not secret or not token or not path.startswith("/"):
        return False
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != SCOPED_MEDIA_TOKEN_VERSION:
        return False
    version, expires_raw, encoded_path, encoded_signature = parts
    try:
        expires_at = int(expires_raw)
        token_path = _b64url_decode(encoded_path).decode("utf-8")
        supplied_signature = _b64url_decode(encoded_signature)
    except (ValueError, UnicodeDecodeError):
        return False
    current = int(time.time() if now is None else now)
    if expires_at < current or expires_at > current + MAX_SCOPED_MEDIA_TOKEN_TTL_SECONDS:
        return False
    if not hmac.compare_digest(token_path, path):
        return False
    payload = f"{version}.{expires_at}.{encoded_path}"
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return hmac.compare_digest(expected_signature, supplied_signature)
