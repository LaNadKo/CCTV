"""Processor-related Pydantic schemas."""
from __future__ import annotations
import json
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


_MAX_PROCESSOR_METADATA_JSON_BYTES = 64 * 1024
_MAX_PROCESSOR_METADATA_DEPTH = 8


def _metadata_depth(value, current: int = 0) -> int:
    if current > _MAX_PROCESSOR_METADATA_DEPTH:
        return current
    if isinstance(value, dict):
        return max(
            [current] + [_metadata_depth(item, current + 1) for item in value.values()]
        )
    if isinstance(value, list):
        return max(
            [current] + [_metadata_depth(item, current + 1) for item in value]
        )
    return current


def _validate_metadata(value):
    if value is None:
        return None
    if _metadata_depth(value) > _MAX_PROCESSOR_METADATA_DEPTH:
        raise ValueError("Processor metadata is nested too deeply")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_PROCESSOR_METADATA_JSON_BYTES:
        raise ValueError("Processor metadata is too large")
    return value


class ProcessorRegister(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    node_uid: str | None = Field(default=None, max_length=128)
    hostname: str | None = Field(default=None, max_length=255)
    ip_address: str | None = Field(default=None, max_length=45)
    os_info: str | None = Field(default=None, max_length=255)
    version: str | None = Field(default=None, max_length=50)
    capabilities: dict | None = None

    _validate_capabilities = field_validator("capabilities")(_validate_metadata)


class ProcessorRegisterOut(BaseModel):
    processor_id: int
    name: str
    status: str


class ProcessorCommandCreate(BaseModel):
    command_type: str
    payload: dict | None = None


class ProcessorCommandResult(BaseModel):
    status: str = Field(pattern="^(succeeded|failed)$")
    result: dict | str | None = None
    error_message: str | None = Field(default=None, max_length=65536)


class ProcessorCommandOut(BaseModel):
    command_id: int
    processor_id: int
    command_type: str
    payload: dict | None = None
    status: str
    result: dict | str | None = None
    error_message: str | None = None
    requested_by_user_id: int | None = None
    created_at: datetime
    claimed_at: datetime | None = None
    completed_at: datetime | None = None


# ── Connection code flow ──

class GenerateCodeOut(BaseModel):
    code: str
    expires_at: datetime


class ProcessorConnect(BaseModel):
    code: str = Field(min_length=6, max_length=20)
    name: str = Field(min_length=1, max_length=150)
    node_uid: str | None = Field(default=None, max_length=128)
    hostname: str | None = Field(default=None, max_length=255)
    ip_address: str | None = Field(default=None, max_length=45)
    os_info: str | None = Field(default=None, max_length=255)
    version: str | None = Field(default=None, max_length=50)
    capabilities: dict | None = None

    _validate_capabilities = field_validator("capabilities")(_validate_metadata)


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
    bottleneck: str | None = Field(default=None, max_length=1000)
    camera_bottlenecks: dict[str, str] | None = None

    _validate_camera_bottlenecks = field_validator("camera_bottlenecks")(_validate_metadata)


class ProcessorHeartbeat(BaseModel):
    status: str = Field(default="online", max_length=32)
    stats: dict | None = None
    metrics: SystemMetrics | None = None
    ip_address: str | None = Field(default=None, max_length=45)
    hostname: str | None = Field(default=None, max_length=255)
    os_info: str | None = Field(default=None, max_length=255)
    version: str | None = Field(default=None, max_length=50)
    capabilities: dict | None = None
    media_port: int | None = Field(default=None, ge=1, le=65535)
    media_token: str | None = Field(default=None, max_length=256)

    _validate_stats = field_validator("stats")(_validate_metadata)
    _validate_capabilities = field_validator("capabilities")(_validate_metadata)


# ── Camera assignments ──

class EndpointInfo(BaseModel):
    endpoint_kind: str
    endpoint_url: str
    username: str | None = None
    password_secret: str | None = None
    is_primary: bool = False


class PresetInfo(BaseModel):
    camera_preset_id: int
    name: str
    preset_token: str | None = None
    order_index: int = 0
    dwell_seconds: int = 10


class CameraAssignment(BaseModel):
    camera_id: int
    name: str
    ip_address: str | None = None
    stream_url: str | None = None
    detection_enabled: bool
    recording_mode: str
    tracking_enabled: bool
    tracking_mode: str
    tracking_target_person_id: int | None = None
    connection_kind: str = "manual"
    supports_ptz: bool = False
    onvif_profile_token: str | None = None
    endpoints: list[EndpointInfo] = []
    presets: list[PresetInfo] = []


# ── Events ──

class ProcessorEventIn(BaseModel):
    camera_id: int
    event_type: str  # face_recognized | face_unknown | motion_detected | person_detected
    person_id: int | None = None
    confidence: float | None = None
    track_id: int | None = None
    snapshot_b64: str | None = None
    event_ts: datetime | None = None


class ProcessorEventOut(BaseModel):
    event_id: int


# ── Recordings ──

class ProcessorRecordingIn(BaseModel):
    camera_id: int
    file_path: str = Field(min_length=1, max_length=1024)
    file_kind: str = Field(default="video", pattern="^(video|snapshot)$")
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
    node_uid: str | None = None
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
    pending_commands: int = 0
    running_commands: int = 0
    last_command: ProcessorCommandOut | None = None


class AssignCamerasIn(BaseModel):
    camera_ids: list[int]


class StorageConfigOut(BaseModel):
    storage_type: str
    root_path: str
    connection_config: dict | None = None
