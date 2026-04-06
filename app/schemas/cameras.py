from typing import Optional

from pydantic import BaseModel, Field


class CameraEndpointInfo(BaseModel):
    endpoint_kind: str
    endpoint_url: str
    is_primary: bool = False


class CameraPtzCapabilitiesOut(BaseModel):
    pan_tilt: bool = False
    zoom: bool = False
    home: bool = False
    presets: bool = False


class CameraOut(BaseModel):
    camera_id: int
    name: str
    location: Optional[str] = None
    ip_address: Optional[str] = None
    stream_url: Optional[str] = None
    permission: str
    detection_enabled: bool
    recording_mode: str
    tracking_enabled: bool = False
    tracking_mode: str = "off"
    tracking_target_person_id: Optional[int] = None
    group_id: Optional[int] = None
    connection_kind: str = "manual"
    onvif_enabled: bool = False
    supports_ptz: bool = False
    ptz_capabilities: CameraPtzCapabilitiesOut = Field(default_factory=CameraPtzCapabilitiesOut)
    endpoint_kinds: list[str] = Field(default_factory=list)
    endpoints: list[CameraEndpointInfo] = Field(default_factory=list)

    class Config:
        from_attributes = True


class CameraPermissionOut(BaseModel):
    camera_id: int
    permission: Optional[str]
    allowed: bool
