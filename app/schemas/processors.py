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


class ProcessorHeartbeat(BaseModel):
    status: str = "online"
    stats: dict | None = None


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


class ProcessorEventIn(BaseModel):
    camera_id: int
    event_type: str  # motion | face_recognized | face_unknown | body_detected
    person_id: int | None = None
    confidence: float | None = None
    track_id: int | None = None
    snapshot_b64: str | None = None


class ProcessorEventOut(BaseModel):
    event_id: int


class ProcessorRecordingIn(BaseModel):
    camera_id: int
    file_path: str
    file_kind: str = "video"
    duration_seconds: float | None = None
    file_size_bytes: int | None = None


class ProcessorRecordingOut(BaseModel):
    recording_file_id: int


class GalleryEntry(BaseModel):
    person_id: int
    label: str | None = None
    embedding_b64: str


class AssignedCameraInfo(BaseModel):
    camera_id: int
    name: str


class ProcessorOut(BaseModel):
    processor_id: int
    name: str
    status: str
    last_heartbeat: datetime | None = None
    capabilities: dict | None = None
    created_at: datetime
    camera_count: int = 0
    assigned_cameras: list[AssignedCameraInfo] = []


class AssignCamerasIn(BaseModel):
    camera_ids: list[int]


class StorageConfigOut(BaseModel):
    storage_type: str
    root_path: str
    connection_config: dict | None = None
