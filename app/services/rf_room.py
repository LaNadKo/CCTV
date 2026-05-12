"""RF room layout loading and ESP32 node polling."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.schemas.rf import RfNodeConfig, RfNodeRuntime, RfRoomLayout, RfRoomSnapshot


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _layout_path() -> Path:
    raw = Path(settings.rf_room_layout_path)
    if raw.is_absolute():
        return raw
    return _repo_root() / raw


def load_rf_room_layout() -> RfRoomLayout:
    path = _layout_path()
    return RfRoomLayout.model_validate_json(path.read_text(encoding="utf-8"))


def save_rf_room_layout(layout: RfRoomLayout) -> RfRoomLayout:
    path = _layout_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(layout.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(f"{raw}\n", encoding="utf-8")
    tmp_path.replace(path)
    return load_rf_room_layout()


def get_rf_room_layout_path() -> str:
    return str(_layout_path())


async def _get_json(client: httpx.AsyncClient, url: str) -> tuple[dict[str, Any] | None, str | None, float | None]:
    started = time.perf_counter()
    try:
        response = await client.get(url)
        response.raise_for_status()
        latency_ms = (time.perf_counter() - started) * 1000
        payload = response.json()
        if not isinstance(payload, dict):
            return None, "node returned non-object JSON", latency_ms
        return payload, None, latency_ms
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return None, str(exc), latency_ms


async def _poll_node(
    client: httpx.AsyncClient,
    node: RfNodeConfig,
    include_scan: bool,
) -> RfNodeRuntime:
    health, health_error, health_latency = await _get_json(client, f"http://{node.ip}/health")
    if health is None:
        ota_status, ota_error, ota_latency = await _get_json(client, f"http://{node.ip}:8032/ota/status")
        if ota_status is not None:
            health = {
                "node_id": node.node_id,
                "role": "ruview-csi",
                "ip": node.ip,
                "wifi_status": "connected",
                "ota_status": ota_status,
            }
            health_error = None
            health_latency = ota_latency
        else:
            health_error = health_error or ota_error

    scan: dict[str, Any] | None = None
    scan_error: str | None = None

    if include_scan and health is not None and health.get("role") != "ruview-csi":
        scan, scan_error, _ = await _get_json(client, f"http://{node.ip}/scan")

    error = health_error or scan_error
    return RfNodeRuntime(
        config=node,
        online=health is not None,
        latency_ms=round(health_latency, 1) if health_latency is not None else None,
        health=health,
        scan=scan,
        error=error,
    )


async def collect_rf_room_snapshot(include_scan: bool = False) -> RfRoomSnapshot:
    layout = load_rf_room_layout()
    timeout = httpx.Timeout(25.0 if include_scan else 5.0, connect=1.5)
    limits = httpx.Limits(max_connections=max(len(layout.nodes), 6), max_keepalive_connections=0)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        nodes = await asyncio.gather(*(_poll_node(client, node, include_scan) for node in layout.nodes))

    return RfRoomSnapshot(
        generated_at=datetime.now(timezone.utc),
        layout=layout,
        nodes=list(nodes),
        include_scan=include_scan,
        online_count=sum(1 for node in nodes if node.online),
    )
