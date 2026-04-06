from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class CameraEndpointInput(BaseModel):
    endpoint_kind: Literal["onvif", "rtsp", "http"]
    endpoint_url: str
    username: Optional[str] = None
    password_secret: Optional[str] = None
    is_primary: bool = False


class CameraEndpointOut(BaseModel):
    camera_endpoint_id: Optional[int] = None
    endpoint_kind: str
    endpoint_url: str
    username: Optional[str] = None
    has_password: bool = False
    is_primary: bool = False


class PtzCapabilitiesOut(BaseModel):
    pan_tilt: bool = False
    zoom: bool = False
    home: bool = False
    presets: bool = False


class CameraCreate(BaseModel):
    name: str
    ip_address: Optional[str] = None
    stream_url: Optional[str] = None
    status_id: Optional[int] = None
    location: Optional[str] = None
    detection_enabled: bool = False
    recording_mode: str = Field(default="continuous", pattern="^(continuous|event)$")
    connection_kind: str = Field(default="manual", pattern="^(manual|onvif|rtsp|http)$")
    supports_ptz: bool = False
    onvif_profile_token: Optional[str] = None
    device_metadata: Optional[dict[str, Any]] = None
    endpoints: list[CameraEndpointInput] = Field(default_factory=list)


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    ip_address: Optional[str] = None
    stream_url: Optional[str] = None
    status_id: Optional[int] = None
    location: Optional[str] = None
    detection_enabled: Optional[bool] = None
    recording_mode: Optional[str] = Field(default=None, pattern="^(continuous|event)$")
    tracking_enabled: Optional[bool] = None
    tracking_mode: Optional[str] = Field(default=None, pattern="^(off|auto|patrol)$")
    tracking_target_person_id: Optional[int] = None
    connection_kind: Optional[str] = Field(default=None, pattern="^(manual|onvif|rtsp|http)$")
    supports_ptz: Optional[bool] = None
    onvif_profile_token: Optional[str] = None
    device_metadata: Optional[dict[str, Any]] = None
    endpoints: Optional[list[CameraEndpointInput]] = None


class CameraDiscoveryScanRequest(BaseModel):
    timeout: int = Field(default=4, ge=1, le=15)
    interface: Optional[str] = None


class CameraDiscoveryProbeRequest(BaseModel):
    host: str
    username: Optional[str] = None
    password: Optional[str] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    use_https: Optional[bool] = None
    timeout: int = Field(default=5, ge=1, le=20)


class CameraDiscoveryDeviceOut(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    use_https: bool = False
    xaddrs: list[str] = Field(default_factory=list)
    types: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    name: Optional[str] = None


class CameraProbeResultOut(BaseModel):
    name: Optional[str] = None
    ip_address: Optional[str] = None
    connection_kind: str = "manual"
    protocols: list[str] = Field(default_factory=list)
    supports_ptz: bool = False
    ptz_capabilities: Optional[PtzCapabilitiesOut] = None
    onvif_profile_token: Optional[str] = None
    endpoints: list[CameraEndpointOut] = Field(default_factory=list)
    device_metadata: Optional[dict[str, Any]] = None
    presets: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PtzRelativeMoveIn(BaseModel):
    pan: float = 0.0
    tilt: float = 0.0
    zoom: float = 0.0
    speed: Optional[float] = None


class PtzContinuousMoveIn(BaseModel):
    pan: float = 0.0
    tilt: float = 0.0
    zoom: float = 0.0
    timeout_seconds: Optional[float] = Field(default=0.4, ge=0.1, le=10.0)


class PtzAbsoluteMoveIn(BaseModel):
    pan: Optional[float] = None
    tilt: Optional[float] = None
    zoom: Optional[float] = None
    speed: Optional[float] = None


class VideoStreamCreate(BaseModel):
    resolution: Optional[str] = None
    fps: Optional[int] = None
    enabled: bool = True
    stream_url: Optional[str] = None


class VideoStreamUpdate(BaseModel):
    resolution: Optional[str] = None
    fps: Optional[int] = None
    enabled: Optional[bool] = None
    stream_url: Optional[str] = None


class PersonCreate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    category_id: Optional[int] = None


class PersonUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    category_id: Optional[int] = None


class EventCreate(BaseModel):
    camera_id: int
    event_type_id: int
    person_id: Optional[int] = None
    recording_file_id: Optional[int] = None
    confidence: Optional[float] = None


class RecordingFileCreate(BaseModel):
    video_stream_id: int
    storage_target_id: int
    file_kind: str = Field(pattern="^(video|snapshot)$")
    file_path: str
    duration_seconds: Optional[float] = None
    file_size_bytes: Optional[int] = None
    checksum: Optional[str] = None
