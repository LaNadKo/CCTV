"""S3-compatible storage backend (AWS S3, MinIO, Yandex Object Storage)."""
from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from app.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class S3StorageBackend(StorageBackend):
    def __init__(self, config: dict):
        self.endpoint_url = config.get("endpoint_url")
        self.bucket = config["bucket"]
        self.access_key = config.get("access_key_id", "")
        self.secret_key = config.get("secret_access_key", "")
        self.region = config.get("region", "us-east-1")
        self.prefix = config.get("prefix", "").strip("/")
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3
            kwargs = {
                "aws_access_key_id": self.access_key,
                "aws_secret_access_key": self.secret_key,
                "region_name": self.region,
            }
            if self.endpoint_url:
                kwargs["endpoint_url"] = self.endpoint_url
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def _key(self, remote_path: str) -> str:
        return f"{self.prefix}/{remote_path}" if self.prefix else remote_path

    async def upload(self, remote_path: str, data: bytes) -> None:
        client = self._get_client()
        await asyncio.to_thread(client.put_object, Bucket=self.bucket, Key=self._key(remote_path), Body=data)

    async def upload_file(self, remote_path: str, local_path: Path) -> None:
        client = self._get_client()
        await asyncio.to_thread(client.upload_file, str(local_path), self.bucket, self._key(remote_path))

    async def download(self, remote_path: str) -> bytes:
        client = self._get_client()
        resp = await asyncio.to_thread(client.get_object, Bucket=self.bucket, Key=self._key(remote_path))
        return resp["Body"].read()

    async def exists(self, remote_path: str) -> bool:
        client = self._get_client()
        try:
            await asyncio.to_thread(client.head_object, Bucket=self.bucket, Key=self._key(remote_path))
            return True
        except Exception:
            return False

    async def delete(self, remote_path: str) -> None:
        client = self._get_client()
        await asyncio.to_thread(client.delete_object, Bucket=self.bucket, Key=self._key(remote_path))

    async def list_files(self, prefix: str = "") -> list[str]:
        client = self._get_client()
        full_prefix = self._key(prefix) if prefix else (self.prefix or "")
        resp = await asyncio.to_thread(client.list_objects_v2, Bucket=self.bucket, Prefix=full_prefix, MaxKeys=1000)
        files = []
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if self.prefix and key.startswith(self.prefix + "/"):
                key = key[len(self.prefix) + 1:]
            files.append(key)
        return files

    async def health_check(self) -> dict:
        try:
            client = self._get_client()
            await asyncio.to_thread(client.head_bucket, Bucket=self.bucket)
            test_key = self._key(".health_check")
            await asyncio.to_thread(client.put_object, Bucket=self.bucket, Key=test_key, Body=b"ok")
            await asyncio.to_thread(client.delete_object, Bucket=self.bucket, Key=test_key)
            return {"ok": True, "exists": True, "writable": True}
        except Exception as e:
            return {"ok": False, "exists": False, "writable": False, "error": str(e)}

    async def get_url(self, remote_path: str) -> str | None:
        client = self._get_client()
        try:
            url = await asyncio.to_thread(
                client.generate_presigned_url, "get_object",
                Params={"Bucket": self.bucket, "Key": self._key(remote_path)}, ExpiresIn=3600,
            )
            return url
        except Exception:
            return None
