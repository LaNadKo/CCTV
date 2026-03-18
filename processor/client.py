"""HTTP client for backend API."""
from __future__ import annotations
import logging
import httpx
from processor.config import settings

logger = logging.getLogger(__name__)


class BackendClient:
    def __init__(self):
        self.base = settings.backend_url.rstrip("/")
        self.headers = {"X-Api-Key": settings.api_key, "Content-Type": "application/json"}
        self._http = httpx.AsyncClient(timeout=30, headers=self.headers)

    async def register(self, name: str, capabilities: dict | None = None) -> dict:
        r = await self._http.post(f"{self.base}/processors/register", json={"name": name, "capabilities": capabilities or {}})
        r.raise_for_status()
        return r.json()

    async def heartbeat(self, processor_id: int, status: str = "online", stats: dict | None = None) -> dict:
        r = await self._http.post(f"{self.base}/processors/{processor_id}/heartbeat", json={"status": status, "stats": stats or {}})
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
