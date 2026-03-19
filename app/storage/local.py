"""Local filesystem storage backend."""
from __future__ import annotations
import asyncio
import shutil
from pathlib import Path
from app.storage.base import StorageBackend


class LocalStorageBackend(StorageBackend):
    def __init__(self, root_path: str):
        self.root = Path(root_path).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _full_path(self, remote_path: str) -> Path:
        return self.root / remote_path

    async def upload(self, remote_path: str, data: bytes) -> None:
        p = self._full_path(remote_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(p.write_bytes, data)

    async def upload_file(self, remote_path: str, local_path: Path) -> None:
        p = self._full_path(remote_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, local_path, p)

    async def download(self, remote_path: str) -> bytes:
        return await asyncio.to_thread(self._full_path(remote_path).read_bytes)

    async def exists(self, remote_path: str) -> bool:
        return await asyncio.to_thread(self._full_path(remote_path).exists)

    async def delete(self, remote_path: str) -> None:
        p = self._full_path(remote_path)
        if await asyncio.to_thread(p.exists):
            await asyncio.to_thread(p.unlink)

    async def list_files(self, prefix: str = "") -> list[str]:
        base = self._full_path(prefix) if prefix else self.root
        if not await asyncio.to_thread(base.exists):
            return []
        files = []
        for p in base.rglob("*"):
            if p.is_file():
                files.append(str(p.relative_to(self.root)))
        return files

    async def health_check(self) -> dict:
        exists = await asyncio.to_thread(self.root.exists)
        writable = False
        free_gb = None
        total_gb = None
        if exists:
            test_file = self.root / ".health_check"
            try:
                await asyncio.to_thread(test_file.write_text, "ok")
                await asyncio.to_thread(test_file.unlink)
                writable = True
            except Exception:
                pass
            try:
                usage = shutil.disk_usage(self.root)
                total_gb = round(usage.total / (1024**3), 2)
                free_gb = round(usage.free / (1024**3), 2)
            except Exception:
                pass
        return {"ok": exists and writable, "exists": exists, "writable": writable, "total_gb": total_gb, "free_gb": free_gb}

    async def get_url(self, remote_path: str) -> str | None:
        return None
