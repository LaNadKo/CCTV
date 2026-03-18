"""Storage backend factory."""
from __future__ import annotations
import json
import logging
from app.storage.base import StorageBackend
from app.storage.local import LocalStorageBackend

logger = logging.getLogger(__name__)


def create_backend(storage_target) -> StorageBackend:
    storage_type = getattr(storage_target, "storage_type", "local") or "local"
    if storage_type == "local":
        return LocalStorageBackend(storage_target.root_path)
    config = {}
    raw = getattr(storage_target, "connection_config", None)
    if raw:
        try:
            config = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid connection_config for storage target %s", storage_target.name)
    if storage_type == "s3":
        from app.storage.s3 import S3StorageBackend
        return S3StorageBackend(config)
    elif storage_type == "ftp":
        from app.storage.ftp import FTPStorageBackend
        return FTPStorageBackend(config)
    else:
        logger.warning("Unknown storage type %s, falling back to local", storage_type)
        return LocalStorageBackend(storage_target.root_path)
