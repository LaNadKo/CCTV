from typing import Optional

from pydantic import BaseModel


class RecordingOut(BaseModel):
    recording_file_id: int
    camera_id: int
    video_stream_id: int
    file_kind: str
    file_path: str
    started_at: str
    ended_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    file_size_bytes: Optional[int] = None
    checksum: Optional[str] = None

    class Config:
        from_attributes = True


class LocalRecordingOut(BaseModel):
    name: str
    url: str
    size_bytes: int
    modified_at: str
    camera_id: Optional[int] = None
