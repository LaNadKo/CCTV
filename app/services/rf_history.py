"""Small JSONL storage for RF baseline snapshots."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.schemas.rf import (
    RfBaselineNodeStats,
    RfBaselineSummary,
    RfHistoryOut,
    RfNodeRuntime,
    RfNodeSample,
    RfRoomSnapshot,
    RfSnapshotSample,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rf_history_path() -> Path:
    raw = Path(settings.rf_history_path)
    if raw.is_absolute():
        return raw
    return _repo_root() / raw


def _strongest_networks(node: RfNodeRuntime, limit: int = 3) -> list[dict[str, Any]]:
    networks = node.scan.get("networks", []) if node.scan else []
    if not isinstance(networks, list):
        return []
    valid = [network for network in networks if isinstance(network, dict) and isinstance(network.get("rssi"), int)]
    valid.sort(key=lambda network: network.get("rssi", -999), reverse=True)
    return [
        {
            "ssid": network.get("ssid"),
            "bssid": network.get("bssid"),
            "rssi": network.get("rssi"),
            "channel": network.get("channel"),
        }
        for network in valid[:limit]
    ]


def compact_sample(snapshot: RfRoomSnapshot) -> RfSnapshotSample:
    nodes: list[RfNodeSample] = []
    for node in snapshot.nodes:
        health = node.health or {}
        scan_networks = node.scan.get("networks", []) if node.scan else None
        nodes.append(
            RfNodeSample(
                node_id=node.config.node_id,
                physical_label=node.config.physical_label,
                position_label=node.config.position_label,
                ip=node.config.ip,
                mac=node.config.mac,
                x_cm=node.config.x_cm,
                y_cm=node.config.y_cm,
                z_cm=node.config.z_cm,
                online=node.online,
                latency_ms=node.latency_ms,
                rssi=health.get("rssi") if isinstance(health.get("rssi"), int) else None,
                ssid=health.get("ssid") if isinstance(health.get("ssid"), str) else None,
                bssid=health.get("bssid") if isinstance(health.get("bssid"), str) else None,
                uptime_ms=health.get("uptime_ms") if isinstance(health.get("uptime_ms"), int) else None,
                scan_network_count=len(scan_networks) if isinstance(scan_networks, list) else None,
                strongest_networks=_strongest_networks(node),
                error=node.error,
            )
        )
    return RfSnapshotSample(
        generated_at=snapshot.generated_at,
        include_scan=snapshot.include_scan,
        online_count=snapshot.online_count,
        node_count=len(nodes),
        nodes=nodes,
    )


def append_rf_sample(snapshot: RfRoomSnapshot) -> RfSnapshotSample:
    sample = compact_sample(snapshot)
    path = rf_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(sample.model_dump_json() + "\n")
    return sample


def read_rf_samples(limit: int = 100) -> RfHistoryOut:
    path = rf_history_path()
    if not path.exists():
        return RfHistoryOut(storage_path=str(path), total_samples=0, returned_samples=0, samples=[])

    raw_lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    limited = raw_lines[-max(1, min(limit, 1000)) :]
    samples: list[RfSnapshotSample] = []
    for line in limited:
        try:
            samples.append(RfSnapshotSample.model_validate_json(line))
        except Exception:
            continue
    return RfHistoryOut(
        storage_path=str(path),
        total_samples=len(raw_lines),
        returned_samples=len(samples),
        samples=samples,
    )


def summarize_rf_baseline(limit: int = 100) -> RfBaselineSummary:
    history = read_rf_samples(limit=limit)
    grouped: dict[str, list[tuple[RfSnapshotSample, RfNodeSample]]] = defaultdict(list)
    for sample in history.samples:
        for node in sample.nodes:
            grouped[node.node_id].append((sample, node))

    node_stats: list[RfBaselineNodeStats] = []
    for node_id, pairs in sorted(grouped.items(), key=lambda item: item[1][-1][1].physical_label):
        latest = pairs[-1][1]
        online_pairs = [(sample, node) for sample, node in pairs if node.online]
        rssi_values = [node.rssi for _, node in online_pairs if node.rssi is not None]
        last_rssi = rssi_values[-1] if rssi_values else None
        last_seen = next((sample.generated_at for sample, node in reversed(pairs) if node.online), None)
        node_stats.append(
            RfBaselineNodeStats(
                node_id=node_id,
                physical_label=latest.physical_label,
                position_label=latest.position_label,
                ip=latest.ip,
                x_cm=latest.x_cm,
                y_cm=latest.y_cm,
                z_cm=latest.z_cm,
                samples=len(pairs),
                online_samples=len(online_pairs),
                avg_rssi=round(sum(rssi_values) / len(rssi_values), 1) if rssi_values else None,
                min_rssi=min(rssi_values) if rssi_values else None,
                max_rssi=max(rssi_values) if rssi_values else None,
                last_rssi=last_rssi,
                last_seen_at=last_seen,
            )
        )

    return RfBaselineSummary(
        generated_at=datetime.now(timezone.utc),
        storage_path=history.storage_path,
        sample_count=history.total_samples,
        node_count=len(node_stats),
        nodes=node_stats,
    )
