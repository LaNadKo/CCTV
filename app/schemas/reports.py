from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class AppearanceItem(BaseModel):
    event_id: int
    event_ts: str
    camera_id: int
    camera_name: Optional[str] = None
    camera_location: Optional[str] = None
    group_name: Optional[str] = None
    person_id: Optional[int] = None
    person_label: Optional[str] = None
    confidence: Optional[float] = None


class AppearanceReport(BaseModel):
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    person_id: Optional[int] = None
    total: int = 0
    items: List[AppearanceItem] = []


class ReportValueLabel(BaseModel):
    label: str
    value: int = 0


class ReportStorageStat(BaseModel):
    storage_target_id: int
    name: str
    file_count: int = 0
    total_bytes: int = 0


class UserActionActorStat(BaseModel):
    user_id: Optional[int] = None
    user_label: str
    audit_actions: int = 0
    auth_success: int = 0
    auth_failures: int = 0
    review_actions: int = 0
    total_actions: int = 0


class RecentUserAction(BaseModel):
    action_kind: str
    occurred_at: str
    user_id: Optional[int] = None
    user_label: str
    action: str
    details: Optional[str] = None
    success: Optional[bool] = None
    source_ip: Optional[str] = None


class UserActionsReport(BaseModel):
    active_users: int = 0
    total_audit_actions: int = 0
    total_auth_events: int = 0
    failed_auth_events: int = 0
    review_actions: int = 0
    totp_enabled_users: int = 0
    top_users: List[UserActionActorStat] = []
    recent_actions: List[RecentUserAction] = []


class GroupReportItem(BaseModel):
    group_id: int
    name: str
    camera_count: int = 0
    online_cameras: int = 0
    offline_cameras: int = 0
    event_count: int = 0
    recognized_count: int = 0
    pending_reviews: int = 0
    recordings_count: int = 0
    recordings_size_bytes: int = 0


class CameraReportItem(BaseModel):
    camera_id: int
    name: str
    location: Optional[str] = None
    group_name: Optional[str] = None
    connection_kind: str
    assigned_processor: Optional[str] = None
    detection_enabled: bool = False
    supports_ptz: bool = False
    is_online: bool = False
    event_count: int = 0
    recognized_count: int = 0
    unknown_count: int = 0
    motion_count: int = 0
    pending_reviews: int = 0
    recordings_count: int = 0
    recordings_size_bytes: int = 0
    last_event_ts: Optional[str] = None


class ProcessorReportItem(BaseModel):
    processor_id: int
    name: str
    status: str
    is_online: bool = False
    ip_address: Optional[str] = None
    version: Optional[str] = None
    last_heartbeat: Optional[str] = None
    assigned_cameras: int = 0
    event_count: int = 0
    recordings_count: int = 0
    cpu_percent: Optional[float] = None
    ram_percent: Optional[float] = None
    gpu_util_percent: Optional[float] = None
    uptime_seconds: Optional[float] = None


class ReviewerStat(BaseModel):
    user_id: Optional[int] = None
    user_label: str
    approved: int = 0
    rejected: int = 0
    pending: int = 0
    total: int = 0


class EventReviewReport(BaseModel):
    total_events: int = 0
    recognized_events: int = 0
    unknown_events: int = 0
    motion_events: int = 0
    person_events: int = 0
    pending_reviews: int = 0
    approved_reviews: int = 0
    rejected_reviews: int = 0
    average_review_seconds: Optional[float] = None
    events_by_type: List[ReportValueLabel] = []
    top_reviewers: List[ReviewerStat] = []


class ArchiveCameraStat(BaseModel):
    camera_id: int
    camera_name: str
    file_count: int = 0
    total_bytes: int = 0
    last_recording_at: Optional[str] = None


class ArchiveReport(BaseModel):
    total_files: int = 0
    total_bytes: int = 0
    video_files: int = 0
    snapshot_files: int = 0
    by_camera: List[ArchiveCameraStat] = []
    by_storage: List[ReportStorageStat] = []


class SecurityFailureItem(BaseModel):
    occurred_at: str
    user_id: Optional[int] = None
    user_label: str
    method: str
    reason: Optional[str] = None
    source_ip: Optional[str] = None


class SecurityReport(BaseModel):
    total_users: int = 0
    totp_enabled_users: int = 0
    totp_coverage_percent: float = 0
    api_keys_total: int = 0
    api_keys_active: int = 0
    successful_logins: int = 0
    failed_logins: int = 0
    recent_failures: List[SecurityFailureItem] = []


class ReportsDashboard(BaseModel):
    generated_at: str
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    group_id: Optional[int] = None
    camera_id: Optional[int] = None
    processor_id: Optional[int] = None
    user_id: Optional[int] = None
    user_actions: UserActionsReport
    groups: List[GroupReportItem] = []
    cameras: List[CameraReportItem] = []
    processors: List[ProcessorReportItem] = []
    events: EventReviewReport
    archive: ArchiveReport
    security: SecurityReport
