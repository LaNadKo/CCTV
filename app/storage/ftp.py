"""FTP storage backend."""
from __future__ import annotations
import asyncio
# FTPS is default; plain FTP requires explicit operator opt-in.
import ftplib  # nosec B402
import io
import logging
import ssl
from pathlib import Path, PurePosixPath
from app.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class FTPStorageBackend(StorageBackend):
    def __init__(self, config: dict):
        self.host = config["host"]
        self.port = int(config.get("port", 21))
        self.username = config.get("username", "anonymous")
        self.password = config.get("password", "")
        self.base_path = config.get("base_path", "/").rstrip("/")
        self.use_tls = bool(config.get("use_tls", True))
        self.allow_insecure_ftp = bool(config.get("allow_insecure_ftp", False))

    def _connect(self) -> ftplib.FTP:
        if self.use_tls:
            ftp = ftplib.FTP_TLS(context=ssl.create_default_context())
            ftp.connect(self.host, self.port, timeout=10)
            ftp.login(self.username, self.password)
            ftp.prot_p()
            return ftp
        if not self.allow_insecure_ftp:
            raise ValueError("Plain FTP is disabled. Use FTPS or set allow_insecure_ftp=true for a trusted legacy server.")
        # Only used after explicit allow_insecure_ftp=true.
        ftp = ftplib.FTP()  # nosec B321
        ftp.connect(self.host, self.port, timeout=10)
        ftp.login(self.username, self.password)
        return ftp

    def _remote(self, path: str) -> str:
        raw = str(path or "").replace("\\", "/")
        parts = [
            part
            for part in PurePosixPath(raw).parts
            if part not in {"", ".", "..", "/"}
        ]
        if not parts:
            raise ValueError("Remote path is empty")
        clean = "/".join(parts)
        return f"{self.base_path}/{clean}" if self.base_path else clean

    def _ensure_dirs(self, ftp: ftplib.FTP, remote: str):
        parts = PurePosixPath(remote).parent.parts
        current = ""
        for part in parts:
            current = f"{current}/{part}" if current else part
            try:
                ftp.mkd(current)
            except ftplib.error_perm:
                pass

    async def upload(self, remote_path: str, data: bytes) -> None:
        def _do():
            ftp = self._connect()
            try:
                r = self._remote(remote_path)
                self._ensure_dirs(ftp, r)
                ftp.storbinary(f"STOR {r}", io.BytesIO(data))
            finally:
                ftp.quit()
        await asyncio.to_thread(_do)

    async def upload_file(self, remote_path: str, local_path: Path) -> None:
        data = local_path.read_bytes()
        await self.upload(remote_path, data)

    async def download(self, remote_path: str) -> bytes:
        def _do():
            ftp = self._connect()
            try:
                buf = io.BytesIO()
                ftp.retrbinary(f"RETR {self._remote(remote_path)}", buf.write)
                return buf.getvalue()
            finally:
                ftp.quit()
        return await asyncio.to_thread(_do)

    async def exists(self, remote_path: str) -> bool:
        def _do():
            ftp = self._connect()
            try:
                ftp.size(self._remote(remote_path))
                return True
            except ftplib.error_perm:
                return False
            finally:
                ftp.quit()
        return await asyncio.to_thread(_do)

    async def delete(self, remote_path: str) -> None:
        def _do():
            ftp = self._connect()
            try:
                ftp.delete(self._remote(remote_path))
            finally:
                ftp.quit()
        await asyncio.to_thread(_do)

    async def list_files(self, prefix: str = "") -> list[str]:
        def _do():
            ftp = self._connect()
            try:
                remote = self._remote(prefix) if prefix else self.base_path or "/"
                return ftp.nlst(remote)
            except ftplib.error_perm:
                return []
            finally:
                ftp.quit()
        return await asyncio.to_thread(_do)

    async def health_check(self) -> dict:
        def _do():
            try:
                ftp = self._connect()
                test_path = self._remote(".health_check")
                ftp.storbinary(f"STOR {test_path}", io.BytesIO(b"ok"))
                ftp.delete(test_path)
                ftp.quit()
                return {"ok": True, "exists": True, "writable": True}
            except Exception as e:
                return {"ok": False, "exists": False, "writable": False, "error": str(e)}
        return await asyncio.to_thread(_do)

    async def get_url(self, remote_path: str) -> str | None:
        scheme = "ftps" if self.use_tls else "ftp"
        return f"{scheme}://{self.host}:{self.port}{self._remote(remote_path)}"
