from typing import Optional

from pydantic import BaseModel, Field


class CameraCreate(BaseModel):
    name: str
    ip_address: Optional[str] = None
    stream_url: Optional[str] = None
    status_id: Optional[int] = None
    location: Optional[str] = None
    detection_enabled: bool = False
    recording_mode: str = Field(default="continuous", pattern="^(continuous|event)$")


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
