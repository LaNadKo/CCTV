"""RuView CSI bridge schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RuViewCsiNodeState(BaseModel):
    node_id: int = Field(ge=0, le=255)
    physical_label: str | None = None
    layout_node_id: str | None = None
    raw_node_id: int | None = Field(default=None, ge=0, le=255)
    source_ip: str
    source_port: int
    packet_count: int = Field(ge=0)
    bytes_total: int = Field(ge=0)
    last_seen_at: datetime | None = None
    stale: bool = False
    last_sequence: int | None = None
    frequency_mhz: int | None = None
    antennas: int | None = None
    subcarriers: int | None = None
    rssi: int | None = None
    noise_floor: int | None = None
    last_payload_bytes: int | None = None
    window_packet_count: int = Field(default=0, ge=0)
    packet_rate_hz: float | None = None
    mean_rssi: float | None = None
    mean_power: float | None = None
    power_std: float | None = None
    last_mean_power: float | None = None


class RuViewCsiLinkState(BaseModel):
    rx_node_id: int = Field(ge=0, le=255)
    tx_node_id: int = Field(ge=0, le=255)
    rx_physical_label: str | None = None
    tx_physical_label: str | None = None
    rx_layout_node_id: str | None = None
    tx_layout_node_id: str | None = None
    tx_mac: str | None = None
    source_ip: str
    source_port: int
    packet_count: int = Field(ge=0)
    bytes_total: int = Field(ge=0)
    last_seen_at: datetime | None = None
    stale: bool = False
    last_sequence: int | None = None
    channel: int | None = None
    rssi: int | None = None
    noise_floor: int | None = None
    flags: int = Field(default=0, ge=0, le=255)
    pairwise: bool = False
    inferred: bool = False
    unknown_peer: bool = False
    link_age_ms: int | None = None
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    last_payload_bytes: int | None = None
    window_packet_count: int = Field(default=0, ge=0)
    packet_rate_hz: float | None = None
    mean_rssi: float | None = None
    mean_power: float | None = None
    power_std: float | None = None
    last_mean_power: float | None = None


class RuViewRfNodeHealthState(BaseModel):
    node_id: int = Field(ge=0, le=255)
    physical_label: str | None = None
    layout_node_id: str | None = None
    source_ip: str
    source_port: int
    packet_count: int = Field(ge=0)
    last_seen_at: datetime | None = None
    stale: bool = False
    last_sequence: int | None = None
    uptime_ms: int | None = None
    rssi: int | None = None
    channel: int | None = None
    tdm_slot: int | None = None
    tdm_total: int | None = None
    peer_count: int | None = None
    dropped_csi_samples: int | None = None


class RuViewVitalsNodeState(BaseModel):
    node_id: int = Field(ge=0, le=255)
    physical_label: str | None = None
    layout_node_id: str | None = None
    raw_node_id: int | None = Field(default=None, ge=0, le=255)
    source_ip: str
    source_port: int
    packet_count: int = Field(ge=0)
    last_seen_at: datetime | None = None
    stale: bool = False
    presence: bool = False
    fall: bool = False
    motion: bool = False
    breathing_bpm: float | None = None
    heart_bpm: float | None = None
    rssi: int | None = None
    detected_persons: int | None = None
    motion_energy: float | None = None
    presence_score: float | None = None
    device_uptime_ms: int | None = None


class RuViewTrackedPerson(BaseModel):
    person_id: str
    status: str
    confidence: float = Field(ge=0.0, le=1.0)
    x_cm: float | None = None
    y_cm: float | None = None
    z_cm: float | None = None
    source: str
    note: str | None = None


class RuViewBridgeStatus(BaseModel):
    enabled: bool
    listening: bool
    bind: str
    port: int
    stimulator_enabled: bool = True
    stimulator_running: bool = False
    stimulator_interval_seconds: float | None = None
    stimulus_count: int = Field(default=0, ge=0)
    last_stimulus_at: datetime | None = None
    last_stimulus_error: str | None = None
    upstream_forward_enabled: bool = False
    upstream_forward_host: str | None = None
    upstream_forward_port: int | None = None
    upstream_forward_count: int = Field(default=0, ge=0)
    last_upstream_forward_at: datetime | None = None
    last_upstream_forward_error: str | None = None
    started_at: datetime | None = None
    last_packet_at: datetime | None = None
    packet_count: int = Field(ge=0)
    csi_packet_count: int = Field(ge=0)
    vitals_packet_count: int = Field(ge=0)
    unknown_packet_count: int = Field(ge=0)
    last_error: str | None = None
    nodes: list[RuViewCsiNodeState] = Field(default_factory=list)
    links: list[RuViewCsiLinkState] = Field(default_factory=list)
    rf_health: list[RuViewRfNodeHealthState] = Field(default_factory=list)
    vitals: list[RuViewVitalsNodeState] = Field(default_factory=list)
    tracked_persons: list[RuViewTrackedPerson] = Field(default_factory=list)


class RuViewCalibrationNodeSample(BaseModel):
    node_id: int = Field(ge=0, le=255)
    physical_label: str | None = None
    layout_node_id: str | None = None
    source_ip: str
    packet_count: int = Field(ge=0)
    rssi: int | None = None
    mean_rssi: float | None = None
    mean_power: float | None = None
    power_std: float | None = None
    packet_rate_hz: float | None = None
    subcarriers: int | None = None


class RuViewCalibrationLinkSample(BaseModel):
    rx_node_id: int = Field(ge=0, le=255)
    tx_node_id: int = Field(ge=0, le=255)
    rx_physical_label: str | None = None
    tx_physical_label: str | None = None
    packet_count: int = Field(ge=0)
    rssi: int | None = None
    mean_rssi: float | None = None
    mean_power: float | None = None
    power_std: float | None = None
    packet_rate_hz: float | None = None
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    inferred: bool = False
    channel: int | None = None


class RuViewCalibrationSampleIn(BaseModel):
    kind: Literal["empty_room", "person_at_point", "walk_path", "live_reference"] = "live_reference"
    label: str
    duration_seconds: float = Field(default=8.0, ge=2.0, le=60.0)
    person_count: int = Field(default=0, ge=0, le=8)
    x_cm: float | None = None
    y_cm: float | None = None
    z_cm: float | None = None
    related_nodes: list[int] = Field(default_factory=list)
    note: str | None = None
    stimulate: bool = True


class RuViewCalibrationSample(BaseModel):
    sample_id: str
    created_at: datetime
    kind: str
    label: str
    duration_seconds: float
    person_count: int = Field(ge=0)
    x_cm: float | None = None
    y_cm: float | None = None
    z_cm: float | None = None
    related_nodes: list[int] = Field(default_factory=list)
    note: str | None = None
    packet_count: int = Field(ge=0)
    csi_packet_count: int = Field(ge=0)
    nodes: list[RuViewCalibrationNodeSample] = Field(default_factory=list)
    links: list[RuViewCalibrationLinkSample] = Field(default_factory=list)


class RuViewCalibrationHistory(BaseModel):
    storage_path: str
    total_samples: int = Field(ge=0)
    returned_samples: int = Field(ge=0)
    samples: list[RuViewCalibrationSample]


class RuViewZoneEstimate(BaseModel):
    generated_at: datetime
    baseline_samples: int = Field(ge=0)
    ready: bool
    person_count_hint: int | None = None
    estimated_x_cm: float | None = None
    estimated_y_cm: float | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    active_nodes: list[int] = Field(default_factory=list)
    message: str | None = None


class RuViewUpstreamStatus(BaseModel):
    enabled: bool
    reachable: bool
    base_url: str | None = None
    health: dict[str, Any] | None = None
    stream_status: dict[str, Any] | None = None
    pose_current: dict[str, Any] | None = None
    pose_stats: dict[str, Any] | None = None
    error: str | None = None


class RuViewPoseBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class RuViewPoseKeypoint(BaseModel):
    name: str | None = None
    x: float
    y: float
    z: float | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class RuViewPosePerson(BaseModel):
    stable_id: str
    ruview_id: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    bbox: RuViewPoseBox | None = None
    keypoints: list[RuViewPoseKeypoint] = Field(default_factory=list)
    zone: str | None = None
    last_seen_at: datetime


class RuViewPoseSnapshot(BaseModel):
    generated_at: datetime
    reachable: bool
    source: str | None = None
    total_persons: int = Field(default=0, ge=0)
    persons: list[RuViewPosePerson] = Field(default_factory=list)
    error: str | None = None
