"""HTTP client for backend API."""
from __future__ import annotations
import logging
import httpx
from processor.config import settings

logger = logging.getLogger(__name__)


class BackendClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base = (base_url or settings.backend_url).rstrip("/")
        key = api_key or settings.api_key
        self.headers = {"X-Api-Key": key, "Content-Type": "application/json"}
        self._http = httpx.AsyncClient(timeout=30, headers=self.headers)

    async def register(self, name: str, capabilities: dict | None = None) -> dict:
        r = await self._http.post(f"{self.base}/processors/register", json={"name": name, "capabilities": capabilities or {}})
        r.raise_for_status()
        return r.json()

    async def heartbeat(
        self,
        processor_id: int,
        status: str = "online",
        stats: dict | None = None,
        metrics: dict | None = None,
        media_port: int | None = None,
        media_token: str | None = None,
    ) -> dict:
        payload = {"status": status, "stats": stats or {}}
        if metrics:
            payload["metrics"] = metrics
        if media_port is not None:
            payload["media_port"] = media_port
        if media_token:
            payload["media_token"] = media_token
        r = await self._http.post(f"{self.base}/processors/{processor_id}/heartbeat", json=payload)
        r.raise_for_status()
        return r.json()

    async def get_assignments(self, processor_id: int) -> list[dict]:
        r = await self._http.get(f"{self.base}/processors/{processor_id}/assignments")
        r.raise_for_status()
        return r.json()

    async def get_gallery(self, processor_id: int) -> list[dict]:
        r = await self._http.get(f"{self.base}/processors/{processor_id}/gallery")
        r.raise_for_status()
        return r.json()

    async def push_event(self, processor_id: int, event: dict) -> dict:
        r = await self._http.post(f"{self.base}/processors/{processor_id}/events", json=event)
        r.raise_for_status()
        return r.json()

    async def push_recording(self, processor_id: int, recording: dict) -> dict:
        r = await self._http.post(f"{self.base}/processors/{processor_id}/recordings", json=recording)
        r.raise_for_status()
        return r.json()

    async def get_storage_config(self, processor_id: int) -> dict:
        r = await self._http.get(f"{self.base}/processors/{processor_id}/storage-config")
        r.raise_for_status()
        return r.json()

    async def close(self):
        await self._http.aclose()
