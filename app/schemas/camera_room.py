"""Camera-to-room projection schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.tracking import CameraTrackBox


class CameraRoomImagePoint(BaseModel):
    x: float = Field(ge=0.0)
    y: float = Field(ge=0.0)
    normalized: bool = True


class CameraRoomPoint(BaseModel):
    x_cm: float
    y_cm: float
    z_cm: float = 0.0


class CameraRoomCalibrationIn(BaseModel):
    enabled: bool = True
    label: str | None = None
    image_points: list[CameraRoomImagePoint] = Field(min_length=4, max_length=4)
    room_points: list[CameraRoomPoint] = Field(min_length=4, max_length=4)
    source: str = "manual"


class CameraRoomCalibration(CameraRoomCalibrationIn):
    camera_id: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class CameraRoomCalibrationList(BaseModel):
    storage_path: str
    calibrations: list[CameraRoomCalibration] = Field(default_factory=list)


class CameraRoomProjectionIn(BaseModel):
    camera_id: int = Field(ge=1)
    bbox: CameraTrackBox
    frame_width: int = Field(ge=1)
    frame_height: int = Field(ge=1)


class CameraRoomProjectionOut(BaseModel):
    camera_id: int = Field(ge=1)
    x_cm: float
    y_cm: float
    z_cm: float = 0.0
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str
    clamped: bool = False
    related_nodes: list[int] = Field(default_factory=list)


class CameraRoomLedCandidate(BaseModel):
    x: float = Field(ge=0.0)
    y: float = Field(ge=0.0)
    radius: float = Field(ge=0.0)
    score: float = Field(ge=0.0)


class CameraRoomLedDetectionOut(BaseModel):
    camera_id: int = Field(ge=1)
    frame_width: int = Field(ge=1)
    frame_height: int = Field(ge=1)
    candidates: list[CameraRoomLedCandidate] = Field(default_factory=list)
