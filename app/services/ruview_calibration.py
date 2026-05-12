"""RuView CSI calibration sample storage and rough zone estimation."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from uuid import uuid4

import httpx

from app.config import settings
from app.schemas.ruview import (
    RuViewCalibrationHistory,
    RuViewCalibrationLinkSample,
    RuViewCalibrationNodeSample,
    RuViewCalibrationSample,
    RuViewCalibrationSampleIn,
    RuViewZoneEstimate,
)
from app.services.rf_room import load_rf_room_layout
from app.services.ruview_bridge import get_ruview_bridge_status, start_ruview_bridge

_ESTIMATE_CACHE_TTL_SECONDS = 0.8
_estimate_cache_lock = threading.Lock()
_estimate_cache: tuple[float, int, RuViewZoneEstimate] | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _calibration_path() -> Path:
    raw = Path(settings.ruview_calibration_path)
    if raw.is_absolute():
        return raw
    return _repo_root() / raw


def calibration_storage_path() -> str:
    return str(_calibration_path())


async def collect_calibration_sample(payload: RuViewCalibrationSampleIn) -> RuViewCalibrationSample:
    start_ruview_bridge()
    started_packets = get_ruview_bridge_status().packet_count
    deadline = asyncio.get_running_loop().time() + payload.duration_seconds

    async with httpx.AsyncClient(timeout=httpx.Timeout(1.5, connect=0.5)) as client:
        while asyncio.get_running_loop().time() < deadline:
            if payload.stimulate:
                await _stimulate_nodes(client)
            await asyncio.sleep(0.2)

    status = get_ruview_bridge_status()
    sample = _build_calibration_sample(payload, status, started_packets)
    append_calibration_sample(sample)
    return sample


def collect_instant_calibration_sample(
    *,
    kind: str,
    label: str,
    person_count: int,
    x_cm: float | None = None,
    y_cm: float | None = None,
    z_cm: float | None = None,
    related_nodes: list[int] | None = None,
    note: str | None = None,
) -> RuViewCalibrationSample:
    start_ruview_bridge()
    status = get_ruview_bridge_status()
    sample = RuViewCalibrationSample(
        sample_id=str(uuid4()),
        created_at=datetime.now(timezone.utc),
        kind=kind,
        label=label,
        duration_seconds=0.0,
        person_count=person_count,
        x_cm=x_cm,
        y_cm=y_cm,
        z_cm=z_cm,
        related_nodes=related_nodes or [],
        note=note,
        packet_count=0,
        csi_packet_count=status.csi_packet_count,
        nodes=_node_samples_from_status(status),
        links=_link_samples_from_status(status),
    )
    append_calibration_sample(sample)
    return sample


def _build_calibration_sample(
    payload: RuViewCalibrationSampleIn,
    status,
    started_packets: int,
) -> RuViewCalibrationSample:
    return RuViewCalibrationSample(
        sample_id=str(uuid4()),
        created_at=datetime.now(timezone.utc),
        kind=payload.kind,
        label=payload.label,
        duration_seconds=payload.duration_seconds,
        person_count=payload.person_count,
        x_cm=payload.x_cm,
        y_cm=payload.y_cm,
        z_cm=payload.z_cm,
        related_nodes=payload.related_nodes,
        note=payload.note,
        packet_count=max(0, status.packet_count - started_packets),
        csi_packet_count=status.csi_packet_count,
        nodes=_node_samples_from_status(status),
        links=_link_samples_from_status(status),
    )


def _node_samples_from_status(status) -> list[RuViewCalibrationNodeSample]:
    return [
        RuViewCalibrationNodeSample(
            node_id=node.node_id,
            physical_label=node.physical_label,
            layout_node_id=node.layout_node_id,
            source_ip=node.source_ip,
            packet_count=node.window_packet_count,
            rssi=node.rssi,
            mean_rssi=node.mean_rssi,
            mean_power=node.mean_power,
            power_std=node.power_std,
            packet_rate_hz=node.packet_rate_hz,
            subcarriers=node.subcarriers,
        )
        for node in status.nodes
        if not node.stale
    ]


def _link_samples_from_status(status) -> list[RuViewCalibrationLinkSample]:
    return [
        RuViewCalibrationLinkSample(
            rx_node_id=link.rx_node_id,
            tx_node_id=link.tx_node_id,
            rx_physical_label=link.rx_physical_label,
            tx_physical_label=link.tx_physical_label,
            packet_count=link.window_packet_count,
            rssi=link.rssi,
            mean_rssi=link.mean_rssi,
            mean_power=link.mean_power,
            power_std=link.power_std,
            packet_rate_hz=link.packet_rate_hz,
            quality_score=link.quality_score,
            inferred=link.inferred,
            channel=link.channel,
        )
        for link in status.links
        if not link.stale and link.pairwise and (link.quality_score or 0.0) >= 0.12
    ]


async def _stimulate_nodes(client: httpx.AsyncClient) -> None:
    try:
        layout = load_rf_room_layout()
    except Exception:
        return
    tasks = [client.get(f"http://{node.ip}:8032/ota/status") for node in layout.nodes]
    await asyncio.gather(*tasks, return_exceptions=True)


def append_calibration_sample(sample: RuViewCalibrationSample) -> None:
    path = _calibration_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sample.model_dump(mode="json", exclude_none=True), ensure_ascii=False))
        handle.write("\n")


def read_calibration_samples(limit: int = 100) -> RuViewCalibrationHistory:
    path = _calibration_path()
    samples: list[RuViewCalibrationSample] = []
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                cleaned = line.lstrip("\ufeff").strip()
                if cleaned:
                    samples.append(RuViewCalibrationSample.model_validate_json(cleaned))
    returned = samples[-limit:]
    return RuViewCalibrationHistory(
        storage_path=str(path),
        total_samples=len(samples),
        returned_samples=len(returned),
        samples=returned,
    )


def estimate_current_zone(limit: int = 200) -> RuViewZoneEstimate:
    global _estimate_cache
    now = time.monotonic()
    with _estimate_cache_lock:
        if _estimate_cache is not None:
            cached_at, cached_limit, cached = _estimate_cache
            if cached_limit >= limit and now - cached_at <= _ESTIMATE_CACHE_TTL_SECONDS:
                return cached.model_copy(deep=True)

    estimate = _estimate_current_zone_uncached(limit=limit)
    with _estimate_cache_lock:
        _estimate_cache = (time.monotonic(), limit, estimate.model_copy(deep=True))
    return estimate


def _estimate_current_zone_uncached(limit: int = 200) -> RuViewZoneEstimate:
    # Keep the live window small for labeled samples, but never let a burst of
    # live_reference records hide older empty-room baselines.
    history = read_calibration_samples(limit=limit)
    baseline_samples = [sample for sample in history.samples if sample.kind == "empty_room"]
    if not baseline_samples:
        history = read_calibration_samples(limit=max(limit, 5000))
        baseline_samples = [sample for sample in history.samples if sample.kind == "empty_room"]
    if not baseline_samples:
        return RuViewZoneEstimate(
            generated_at=datetime.now(timezone.utc),
            baseline_samples=0,
            ready=False,
            message="No empty_room baseline yet. Record an empty-room sample before estimating coordinates.",
        )

    baseline_power = _baseline_power(baseline_samples)
    baseline_link_power = _baseline_link_power(baseline_samples)

    status = get_ruview_bridge_status()
    supervised_estimate = _supervised_fingerprint_estimate(
        status,
        history.samples,
        baseline_power,
        baseline_link_power,
    )
    if supervised_estimate is not None:
        estimated_x, estimated_y, confidence, active_nodes, sample_count = supervised_estimate
        return RuViewZoneEstimate(
            generated_at=datetime.now(timezone.utc),
            baseline_samples=len(baseline_samples),
            ready=True,
            person_count_hint=1,
            estimated_x_cm=estimated_x,
            estimated_y_cm=estimated_y,
            confidence=confidence,
            active_nodes=active_nodes,
            message=f"Camera-supervised RF fingerprint estimate from {sample_count} labeled CSI samples.",
        )

    current_vector = _status_deviation_vector(status.nodes, baseline_power)
    anchor_estimate = _weighted_anchor_estimate(status.nodes, baseline_power)
    link_estimate = _weighted_link_estimate(status.links, baseline_link_power)
    hybrid_estimate = _hybrid_anchor_link_estimate(anchor_estimate, link_estimate)
    if hybrid_estimate is not None:
        estimated_x, estimated_y, confidence, active_nodes = hybrid_estimate
        return RuViewZoneEstimate(
            generated_at=datetime.now(timezone.utc),
            baseline_samples=len(baseline_samples),
            ready=True,
            person_count_hint=1,
            estimated_x_cm=estimated_x,
            estimated_y_cm=estimated_y,
            confidence=confidence,
            active_nodes=active_nodes,
            message="Live hybrid RF estimate. Node deviations pull the marker toward nearby anchors; pairwise links stabilize it.",
        )

    if anchor_estimate is not None:
        estimated_x, estimated_y, confidence, active_nodes = anchor_estimate
        return RuViewZoneEstimate(
            generated_at=datetime.now(timezone.utc),
            baseline_samples=len(baseline_samples),
            ready=True,
            person_count_hint=1,
            estimated_x_cm=estimated_x,
            estimated_y_cm=estimated_y,
            confidence=confidence,
            active_nodes=active_nodes,
            message="Live weighted CSI anchor deviation estimate. Uses the strongest changed ESP32 anchors.",
        )

    if link_estimate is not None:
        estimated_x, estimated_y, confidence, active_nodes = link_estimate
        return RuViewZoneEstimate(
            generated_at=datetime.now(timezone.utc),
            baseline_samples=len(baseline_samples),
            ready=True,
            person_count_hint=1,
            estimated_x_cm=estimated_x,
            estimated_y_cm=estimated_y,
            confidence=confidence,
            active_nodes=active_nodes,
            message="Live weighted RF link deviation estimate. Uses pairwise ESP32 CSI links when available.",
        )

    labeled_samples = [
        sample
        for sample in history.samples
        if sample.kind == "person_at_point" and sample.x_cm is not None and sample.y_cm is not None
    ]
    nearest = _nearest_labeled_sample(current_vector, labeled_samples, baseline_power)
    if nearest is not None:
        sample, similarity = nearest
        return RuViewZoneEstimate(
            generated_at=datetime.now(timezone.utc),
            baseline_samples=len(baseline_samples),
            ready=True,
            person_count_hint=sample.person_count or 1,
            estimated_x_cm=sample.x_cm,
            estimated_y_cm=sample.y_cm,
            confidence=max(0.0, min(1.0, similarity)),
            active_nodes=sample.related_nodes,
            message=f"Fallback to nearest labeled CSI sample: {sample.label}. Live anchor deviation is currently weak.",
        )

    if not current_vector:
        return RuViewZoneEstimate(
            generated_at=datetime.now(timezone.utc),
            baseline_samples=len(baseline_samples),
            ready=True,
            confidence=0.0,
            message="CSI is close to empty baseline; no strong person zone detected.",
        )

    return RuViewZoneEstimate(
        generated_at=datetime.now(timezone.utc),
        baseline_samples=len(baseline_samples),
        ready=True,
        confidence=0.0,
        message="CSI changed, but no layout anchors matched the active node identities.",
    )


def _baseline_power(samples: list[RuViewCalibrationSample]) -> dict[int, float]:
    totals: dict[int, float] = {}
    counts: dict[int, int] = {}
    for sample in samples:
        for node in sample.nodes:
            if node.mean_power is None:
                continue
            totals[node.node_id] = totals.get(node.node_id, 0.0) + node.mean_power
            counts[node.node_id] = counts.get(node.node_id, 0) + 1
    return {node_id: totals[node_id] / counts[node_id] for node_id in totals if counts.get(node_id)}


def _link_key(rx_node_id: int, tx_node_id: int) -> tuple[int, int]:
    return rx_node_id, tx_node_id


def _baseline_link_power(samples: list[RuViewCalibrationSample]) -> dict[tuple[int, int], float]:
    totals: dict[tuple[int, int], float] = {}
    counts: dict[tuple[int, int], int] = {}
    for sample in samples:
        for link in sample.links:
            if link.mean_power is None or link.tx_node_id <= 0:
                continue
            if link.quality_score is not None and link.quality_score < 0.12:
                continue
            key = _link_key(link.rx_node_id, link.tx_node_id)
            totals[key] = totals.get(key, 0.0) + link.mean_power
            counts[key] = counts.get(key, 0) + 1
    return {key: totals[key] / counts[key] for key in totals if counts.get(key)}


def _sample_deviation_vector(sample: RuViewCalibrationSample, baseline_power: dict[int, float]) -> dict[int, float]:
    values: dict[int, float] = {}
    for node in sample.nodes:
        if node.mean_power is None or node.node_id not in baseline_power:
            continue
        baseline = max(baseline_power[node.node_id], 1.0)
        values[node.node_id] = (node.mean_power - baseline) / baseline
    return values


def _status_deviation_vector(nodes, baseline_power: dict[int, float]) -> dict[int, float]:
    values: dict[int, float] = {}
    for node in nodes:
        if node.stale or node.mean_power is None or node.node_id not in baseline_power:
            continue
        baseline = max(baseline_power[node.node_id], 1.0)
        values[node.node_id] = (node.mean_power - baseline) / baseline
    return values


def _supervised_fingerprint_estimate(
    status,
    samples: list[RuViewCalibrationSample],
    baseline_power: dict[int, float],
    baseline_link_power: dict[tuple[int, int], float],
) -> tuple[float, float, float, list[int], int] | None:
    camera_samples = [
        sample
        for sample in samples
        if sample.kind == "live_reference" and _is_usable_labeled_sample(sample)
    ]
    fallback_samples = [
        sample
        for sample in samples
        if sample.kind in {"person_at_point", "walk_path"}
        and _is_usable_labeled_sample(sample)
    ]
    labeled_samples = camera_samples if len(camera_samples) >= 3 else [*camera_samples, *fallback_samples]
    if len(labeled_samples) < 3:
        return None

    current_vector = _status_feature_vector(status, baseline_power, baseline_link_power)
    if len(current_vector) < 3:
        return None

    scored: list[tuple[float, RuViewCalibrationSample]] = []
    for sample in labeled_samples[-300:]:
        sample_vector = _sample_feature_vector(sample, baseline_power, baseline_link_power)
        similarity = _cosine_similarity_features(current_vector, sample_vector)
        if similarity is None or similarity < 0.45:
            continue
        scored.append((similarity, sample))

    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[: min(7, len(scored))]
    if top[0][0] < 0.55:
        return None

    weights = [(similarity - 0.40) ** 2 for similarity, _ in top]
    total_weight = sum(weights)
    if total_weight <= 0:
        return None

    estimated_x = sum(weight * float(sample.x_cm) for weight, (_, sample) in zip(weights, top)) / total_weight
    estimated_y = sum(weight * float(sample.y_cm) for weight, (_, sample) in zip(weights, top)) / total_weight
    active_nodes: list[int] = []
    for _, sample in top:
        for node_id in sample.related_nodes:
            if node_id not in active_nodes:
                active_nodes.append(node_id)
    confidence = max(0.0, min(1.0, top[0][0] * 0.82 + min(len(labeled_samples) / 80.0, 0.18)))
    return round(estimated_x, 1), round(estimated_y, 1), confidence, active_nodes[:6], len(labeled_samples)


def _is_usable_labeled_sample(sample: RuViewCalibrationSample) -> bool:
    if sample.x_cm is None or sample.y_cm is None:
        return False
    note = (sample.note or "").lower()
    # The temporary full-frame projection mapped camera detections to arbitrary
    # room coordinates. Keeping these samples in the fingerprint makes the RF
    # tracker stick to the lower wall near node 3.
    if "projection=auto_full_frame" in note:
        return False
    return True


def _status_feature_vector(
    status,
    baseline_power: dict[int, float],
    baseline_link_power: dict[tuple[int, int], float],
) -> dict[str, float]:
    features: dict[str, float] = {}
    for node_id, deviation in _status_deviation_vector(status.nodes, baseline_power).items():
        if abs(deviation) >= 0.015:
            features[f"n:{node_id}"] = deviation
    for link in status.links:
        if link.stale or not getattr(link, "pairwise", False) or link.mean_power is None or link.tx_node_id <= 0:
            continue
        if (getattr(link, "quality_score", None) or 0.0) < 0.12:
            continue
        key = _link_key(link.rx_node_id, link.tx_node_id)
        if key not in baseline_link_power:
            continue
        baseline = max(baseline_link_power[key], 1.0)
        deviation = (link.mean_power - baseline) / baseline
        if abs(deviation) >= 0.012:
            features[f"l:{link.rx_node_id}:{link.tx_node_id}"] = deviation
    return features


def _sample_feature_vector(
    sample: RuViewCalibrationSample,
    baseline_power: dict[int, float],
    baseline_link_power: dict[tuple[int, int], float],
) -> dict[str, float]:
    features: dict[str, float] = {}
    for node_id, deviation in _sample_deviation_vector(sample, baseline_power).items():
        if abs(deviation) >= 0.015:
            features[f"n:{node_id}"] = deviation
    for link in sample.links:
        if link.mean_power is None or link.tx_node_id <= 0:
            continue
        if link.quality_score is not None and link.quality_score < 0.12:
            continue
        key = _link_key(link.rx_node_id, link.tx_node_id)
        if key not in baseline_link_power:
            continue
        baseline = max(baseline_link_power[key], 1.0)
        deviation = (link.mean_power - baseline) / baseline
        if abs(deviation) >= 0.012:
            features[f"l:{link.rx_node_id}:{link.tx_node_id}"] = deviation
    return features


def _weighted_anchor_estimate(nodes, baseline_power: dict[int, float]) -> tuple[float, float, float, list[int]] | None:
    layout = load_rf_room_layout()
    layout_by_label = {int(node.physical_label): node for node in layout.nodes if node.physical_label.isdigit()}
    weighted: list[tuple[float, float, float, int]] = []
    for node in nodes:
        if node.stale or node.mean_power is None or node.node_id not in baseline_power:
            continue
        baseline = max(baseline_power[node.node_id], 1.0)
        deviation = abs(node.mean_power - baseline) / baseline
        if deviation <= 0.05:
            continue
        config = layout_by_label.get(node.node_id)
        if config is None:
            continue
        weight = (deviation - 0.05) ** 1.35
        weighted.append((weight, config.x_cm, config.y_cm, node.node_id))

    if not weighted:
        return None

    total = sum(item[0] for item in weighted)
    if total <= 0:
        return None
    estimated_x = sum(weight * x for weight, x, _, _ in weighted) / total
    estimated_y = sum(weight * y for weight, _, y, _ in weighted) / total
    strongest = max(item[0] for item in weighted)
    active_nodes = [node_id for _, _, _, node_id in sorted(weighted, reverse=True)]
    confidence = max(0.0, min(1.0, strongest * 3.0))
    return round(estimated_x, 1), round(estimated_y, 1), confidence, active_nodes


def _hybrid_anchor_link_estimate(
    anchor_estimate: tuple[float, float, float, list[int]] | None,
    link_estimate: tuple[float, float, float, list[int]] | None,
) -> tuple[float, float, float, list[int]] | None:
    if anchor_estimate is None or link_estimate is None:
        return None
    anchor_x, anchor_y, anchor_confidence, anchor_nodes = anchor_estimate
    link_x, link_y, link_confidence, link_nodes = link_estimate
    anchor_weight = 0.68 if anchor_confidence >= 0.25 else 0.55
    link_weight = 1.0 - anchor_weight
    active_nodes: list[int] = []
    for node_id in [*anchor_nodes[:4], *link_nodes[:4]]:
        if node_id not in active_nodes:
            active_nodes.append(node_id)
    return (
        round(anchor_x * anchor_weight + link_x * link_weight, 1),
        round(anchor_y * anchor_weight + link_y * link_weight, 1),
        max(0.0, min(1.0, max(anchor_confidence, link_confidence) * 0.92)),
        active_nodes,
    )


def _weighted_link_estimate(links, baseline_link_power: dict[tuple[int, int], float]) -> tuple[float, float, float, list[int]] | None:
    if not baseline_link_power:
        return None
    layout = load_rf_room_layout()
    layout_by_label = {int(node.physical_label): node for node in layout.nodes if node.physical_label.isdigit()}
    weighted: list[tuple[float, float, float, int, int]] = []

    for link in links:
        if link.stale or not getattr(link, "pairwise", False) or link.mean_power is None or link.tx_node_id <= 0:
            continue
        if (getattr(link, "quality_score", None) or 0.0) < 0.12:
            continue
        key = _link_key(link.rx_node_id, link.tx_node_id)
        if key not in baseline_link_power:
            continue
        rx_config = layout_by_label.get(link.rx_node_id)
        tx_config = layout_by_label.get(link.tx_node_id)
        if rx_config is None or tx_config is None:
            continue
        baseline = max(baseline_link_power[key], 1.0)
        deviation = abs(link.mean_power - baseline) / baseline
        if deviation <= 0.035:
            continue
        midpoint_x = (rx_config.x_cm + tx_config.x_cm) / 2.0
        midpoint_y = (rx_config.y_cm + tx_config.y_cm) / 2.0
        weight = (deviation - 0.035) ** 1.25
        weighted.append((weight, midpoint_x, midpoint_y, link.rx_node_id, link.tx_node_id))

    if not weighted:
        return None

    total = sum(item[0] for item in weighted)
    if total <= 0:
        return None

    estimated_x = sum(weight * x for weight, x, _, _, _ in weighted) / total
    estimated_y = sum(weight * y for weight, _, y, _, _ in weighted) / total
    strongest = max(item[0] for item in weighted)
    active_nodes: list[int] = []
    for _, _, _, rx_node_id, tx_node_id in sorted(weighted, reverse=True):
        for node_id in (rx_node_id, tx_node_id):
            if node_id not in active_nodes:
                active_nodes.append(node_id)
    confidence = max(0.0, min(1.0, strongest * 4.0))
    return round(estimated_x, 1), round(estimated_y, 1), confidence, active_nodes


def _nearest_labeled_sample(
    current_vector: dict[int, float],
    samples: list[RuViewCalibrationSample],
    baseline_power: dict[int, float],
) -> tuple[RuViewCalibrationSample, float] | None:
    if not current_vector or not samples:
        return None
    best: tuple[RuViewCalibrationSample, float] | None = None
    for sample in samples:
        sample_vector = _sample_deviation_vector(sample, baseline_power)
        similarity = _cosine_similarity(current_vector, sample_vector)
        if similarity is None:
            continue
        if best is None or similarity > best[1]:
            best = (sample, similarity)
    if best is None or best[1] < 0.55:
        return None
    return best


def _cosine_similarity(left: dict[int, float], right: dict[int, float]) -> float | None:
    keys = set(left) & set(right)
    if not keys:
        return None
    dot = sum(left[key] * right[key] for key in keys)
    left_norm = sqrt(sum(left[key] * left[key] for key in keys))
    right_norm = sqrt(sum(right[key] * right[key] for key in keys))
    if left_norm <= 0 or right_norm <= 0:
        return None
    return dot / (left_norm * right_norm)


def _cosine_similarity_features(left: dict[str, float], right: dict[str, float]) -> float | None:
    keys = set(left) & set(right)
    if len(keys) < 3:
        return None
    dot = sum(left[key] * right[key] for key in keys)
    left_norm = sqrt(sum(left[key] * left[key] for key in keys))
    right_norm = sqrt(sum(right[key] * right[key] for key in keys))
    if left_norm <= 0 or right_norm <= 0:
        return None
    return dot / (left_norm * right_norm)
