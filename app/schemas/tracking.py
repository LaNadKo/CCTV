"""Hybrid camera/RuView active tracking schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CameraTrackBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class ProcessorTrackObservationIn(BaseModel):
    camera_id: int = Field(ge=1)
    track_id: int = Field(ge=0)
    person_id: int | None = None
    person_label: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=100.0)
    bbox: CameraTrackBox | None = None
    frame_width: int | None = Field(default=None, ge=1)
    frame_height: int | None = Field(default=None, ge=1)
    keypoints: list[list[float]] | None = None
    keypoint_conf: list[float] | None = None
    observed_at: datetime | None = None


class ActivePersonTrack(BaseModel):
    track_key: str
    status: Literal["camera", "rf", "ambiguous", "lost"]
    source: Literal["camera", "ruview", "fusion", "none"]
    person_id: int | None = None
    person_label: str | None = None
    processor_id: int | None = None
    camera_id: int | None = None
    processor_track_id: int | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=100.0)
    bbox: CameraTrackBox | None = None
    frame_width: int | None = None
    frame_height: int | None = None
    keypoints: list[list[float]] | None = None
    keypoint_conf: list[float] | None = None
    estimated_x_cm: float | None = None
    estimated_y_cm: float | None = None
    estimated_z_cm: float | None = None
    rf_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    active_nodes: list[int] = Field(default_factory=list)
    first_seen_at: datetime
    last_seen_at: datetime
    last_camera_seen_at: datetime | None = None
    last_rf_seen_at: datetime | None = None
    note: str | None = None


class ActiveTrackingSnapshot(BaseModel):
    generated_at: datetime
    active_count: int = Field(ge=0)
    camera_count: int = Field(ge=0)
    rf_count: int = Field(ge=0)
    tracks: list[ActivePersonTrack] = Field(default_factory=list)
    rf_message: str | None = None
