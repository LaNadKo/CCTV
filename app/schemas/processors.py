"""Processor-related Pydantic schemas."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class ProcessorRegister(BaseModel):
    name: str
    capabilities: dict | None = None


class ProcessorRegisterOut(BaseModel):
    processor_id: int
    name: str
    status: str


# ── Connection code flow ──

class GenerateCodeOut(BaseModel):
    code: str
    expires_at: datetime


class ProcessorConnect(BaseModel):
    code: str
    name: str
    hostname: str | None = None
    ip_address: str | None = None
    os_info: str | None = None
    version: str | None = None
    capabilities: dict | None = None


class ProcessorConnectOut(BaseModel):
    processor_id: int
    name: str
    api_key: str
    status: str


# ── Heartbeat ──

class SystemMetrics(BaseModel):
    cpu_percent: float | None = None
    ram_total_gb: float | None = None
    ram_used_gb: float | None = None
    ram_percent: float | None = None
    gpu_name: str | None = None
    gpu_util_percent: float | None = None
    gpu_mem_used_mb: float | None = None
    gpu_mem_total_mb: float | None = None
    gpu_temp_c: float | None = None
    net_sent_mbps: float | None = None
    net_recv_mbps: float | None = None
    disk_used_gb: float | None = None
    disk_total_gb: float | None = None
    active_cameras: int | None = None
    uptime_seconds: float | None = None


class ProcessorHeartbeat(BaseModel):
    status: str = "online"
    stats: dict | None = None
    metrics: SystemMetrics | None = None
    ip_address: str | None = None
    media_port: int | None = None
    media_token: str | None = None


# ── Camera assignments ──

class EndpointInfo(BaseModel):
    endpoint_kind: str
    endpoint_url: str
    username: str | None = None
    password_secret: str | None = None


class CameraAssignment(BaseModel):
    camera_id: int
    name: str
    ip_address: str | None = None
    stream_url: str | None = None
    detection_enabled: bool
    recording_mode: str
    tracking_enabled: bool
    tracking_mode: str
    endpoints: list[EndpointInfo] = []


# ── Events ──

class ProcessorEventIn(BaseModel):
    camera_id: int
    event_type: str  # motion | face_recognized | face_unknown | body_detected
    person_id: int | None = None
    confidence: float | None = None
    track_id: int | None = None
    snapshot_b64: str | None = None


class ProcessorEventOut(BaseModel):
    event_id: int


# ── Recordings ──

class ProcessorRecordingIn(BaseModel):
    camera_id: int
    file_path: str
    file_kind: str = "video"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: float | None = None
    file_size_bytes: int | None = None


class ProcessorRecordingOut(BaseModel):
    recording_file_id: int


# ── Gallery ──

class GalleryEntry(BaseModel):
    person_id: int
    label: str | None = None
    embedding_b64: str


# ── Admin list ──

class AssignedCameraInfo(BaseModel):
    camera_id: int
    name: str


class ProcessorOut(BaseModel):
    processor_id: int
    name: str
    status: str
    last_heartbeat: datetime | None = None
    capabilities: dict | None = None
    ip_address: str | None = None
    os_info: str | None = None
    version: str | None = None
    metrics: SystemMetrics | None = None
    created_at: datetime
    camera_count: int = 0
    assigned_cameras: list[AssignedCameraInfo] = []


class AssignCamerasIn(BaseModel):
    camera_ids: list[int]


class StorageConfigOut(BaseModel):
    storage_type: str
    root_path: str
    connection_config: dict | None = None
