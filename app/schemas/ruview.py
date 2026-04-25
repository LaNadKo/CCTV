from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RuViewNodeStatus(BaseModel):
    node_id: int
    label: str
    source_ip: str | None = None
    source_port: int | None = None
    online: bool
    last_seen: datetime | None = None
    packet_count: int = 0
    packet_rate_hz: float = 0.0
    last_packet_type: str | None = None
    last_sequence: int | None = None
    last_rssi: int | None = None
    channel: int | None = None
    payload_bytes: int | None = None


class RuViewBridgeStatus(BaseModel):
    enabled: bool
    listening: bool
    bind: str
    port: int
    started_at: datetime | None = None
    last_packet_at: datetime | None = None
    last_csi_packet_at: datetime | None = None
    live_csi: bool = False
    packet_count: int = 0
    csi_packet_count: int = 0
    vitals_packet_count: int = 0
    health_packet_count: int = 0
    unknown_packet_count: int = 0
    dropped_csi_packet_count: int = 0
    upstream_forward_enabled: bool = False
    upstream_forward_host: str | None = None
    upstream_forward_port: int | None = None
    upstream_forward_count: int = 0
    last_upstream_forward_at: datetime | None = None
    last_upstream_error: str | None = None
    last_error: str | None = None
    nodes: list[RuViewNodeStatus] = Field(default_factory=list)


class RuViewEndpointStatus(BaseModel):
    url: str
    reachable: bool
    latency_ms: float | None = None
    health: dict | None = None
    stream_status: dict | None = None
    pose_stats: dict | None = None
    error: str | None = None


class RuViewUpstreamStatus(BaseModel):
    enabled: bool
    primary_url: str | None = None
    endpoints: list[RuViewEndpointStatus] = Field(default_factory=list)


class RuViewPoseBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class RuViewPoseKeypoint(BaseModel):
    name: str
    x: float
    y: float
    confidence: float | None = None
    visible: bool = True


class RuViewPosePerson(BaseModel):
    track_id: str
    source_id: str | None = None
    confidence: float | None = None
    bbox: RuViewPoseBox | None = None
    keypoints: list[RuViewPoseKeypoint] = Field(default_factory=list)
    age_ms: float | None = None


class RuViewPoseSnapshot(BaseModel):
    reachable: bool
    source_url: str | None = None
    source_kind: str | None = None
    captured_at: datetime | None = None
    latency_ms: float | None = None
    frame_width: float | None = None
    frame_height: float | None = None
    camera_aligned: bool = False
    overlay_allowed: bool = False
    persons: list[RuViewPosePerson] = Field(default_factory=list)
    error: str | None = None


class RuViewCalibrationStartIn(BaseModel):
    label: str = "baseline"
    scenario: str = "empty"
    duration_seconds: float | None = None
    notes: str | None = None


class RuViewCalibrationStatus(BaseModel):
    active: bool
    session_id: str | None = None
    label: str | None = None
    scenario: str | None = None
    notes: str | None = None
    directory: str | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    duration_seconds: float | None = None
    csi_samples: int = 0
    camera_samples: int = 0
    latest_tracks: int = 0
