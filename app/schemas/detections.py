from typing import Optional, List

from pydantic import BaseModel, Field


class DetectionIn(BaseModel):
    camera_id: int
    person_id: Optional[int] = None
    recording_file_id: Optional[int] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=100)
    event_type: Optional[str] = Field(default=None, description="Optional override event type name")


class DetectionResponse(BaseModel):
    event_id: int
    review_required: bool


class EventReviewUpdate(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    person_id: Optional[int] = None
    note: Optional[str] = None


class PendingEvent(BaseModel):
    event_id: int
    camera_id: int
    camera_name: Optional[str] = None
    camera_location: Optional[str] = None
    event_type_id: int
    event_ts: str
    person_id: Optional[int] = None
    person_label: Optional[str] = None
    recording_file_id: Optional[int] = None
    confidence: Optional[float] = None
    snapshot_url: Optional[str] = None
