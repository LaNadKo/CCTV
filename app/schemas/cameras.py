from typing import Optional

from pydantic import BaseModel


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

    class Config:
        from_attributes = True


class CameraPermissionOut(BaseModel):
    camera_id: int
    permission: Optional[str]
    allowed: bool
