"""Abstract storage backend."""
from __future__ import annotations
import abc
from pathlib import Path


class StorageBackend(abc.ABC):
    @abc.abstractmethod
    async def upload(self, remote_path: str, data: bytes) -> None: ...

    @abc.abstractmethod
    async def upload_file(self, remote_path: str, local_path: Path) -> None: ...

    @abc.abstractmethod
    async def download(self, remote_path: str) -> bytes: ...

    @abc.abstractmethod
    async def exists(self, remote_path: str) -> bool: ...

    @abc.abstractmethod
    async def delete(self, remote_path: str) -> None: ...

    @abc.abstractmethod
    async def list_files(self, prefix: str = "") -> list[str]: ...

    @abc.abstractmethod
    async def health_check(self) -> dict: ...

    @abc.abstractmethod
    async def get_url(self, remote_path: str) -> str | None: ...
