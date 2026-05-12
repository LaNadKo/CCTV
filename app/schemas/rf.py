"""RF room and ESP32 node schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RfCoordinateSystem(BaseModel):
    origin: str
    x_axis: str
    y_axis: str
    z_axis: str


class RfRoomDimensions(BaseModel):
    width_cm: float = Field(gt=0)
    depth_cm: float = Field(gt=0)
    height_cm: float | None = Field(default=None, gt=0)


class RfNodeConfig(BaseModel):
    node_id: str
    ip: str
    mac: str
    physical_label: str
    position_label: str
    x_cm: float = Field(ge=0)
    y_cm: float = Field(ge=0)
    z_cm: float | None = Field(default=None, ge=0)


class RfRoomObject(BaseModel):
    object_id: str
    label: str
    object_type: str = "box"
    x_cm: float = Field(ge=0)
    y_cm: float = Field(ge=0)
    z_cm: float = Field(default=0, ge=0)
    width_cm: float = Field(gt=0)
    depth_cm: float = Field(gt=0)
    height_cm: float = Field(gt=0)
    rotation_deg: float = 0


class RfRoomLayout(BaseModel):
    schema_version: int = 1
    name: str
    units: str = "cm"
    coordinate_system: RfCoordinateSystem
    room: RfRoomDimensions
    nodes: list[RfNodeConfig]
    objects: list[RfRoomObject] = Field(default_factory=list)


class RfNodeRuntime(BaseModel):
    config: RfNodeConfig
    online: bool
    latency_ms: float | None = None
    health: dict[str, Any] | None = None
    scan: dict[str, Any] | None = None
    error: str | None = None


class RfRoomSnapshot(BaseModel):
    generated_at: datetime
    layout: RfRoomLayout
    nodes: list[RfNodeRuntime]
    include_scan: bool = False
    online_count: int = Field(ge=0)


class RfNodeSample(BaseModel):
    node_id: str
    physical_label: str
    position_label: str
    ip: str
    mac: str
    x_cm: float
    y_cm: float
    z_cm: float | None = None
    online: bool
    latency_ms: float | None = None
    rssi: int | None = None
    ssid: str | None = None
    bssid: str | None = None
    uptime_ms: int | None = None
    scan_network_count: int | None = None
    strongest_networks: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class RfSnapshotSample(BaseModel):
    generated_at: datetime
    include_scan: bool = False
    online_count: int = Field(ge=0)
    node_count: int = Field(ge=0)
    nodes: list[RfNodeSample]


class RfHistoryOut(BaseModel):
    storage_path: str
    total_samples: int = Field(ge=0)
    returned_samples: int = Field(ge=0)
    samples: list[RfSnapshotSample]


class RfBaselineNodeStats(BaseModel):
    node_id: str
    physical_label: str
    position_label: str
    ip: str
    x_cm: float
    y_cm: float
    z_cm: float | None = None
    samples: int = Field(ge=0)
    online_samples: int = Field(ge=0)
    avg_rssi: float | None = None
    min_rssi: int | None = None
    max_rssi: int | None = None
    last_rssi: int | None = None
    last_seen_at: datetime | None = None


class RfBaselineSummary(BaseModel):
    generated_at: datetime
    storage_path: str
    sample_count: int = Field(ge=0)
    node_count: int = Field(ge=0)
    nodes: list[RfBaselineNodeStats]

