from __future__ import annotations

from typing import Optional
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    LargeBinary,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


class Role(Base):
    __tablename__ = "roles"

    role_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    middle_name: Mapped[Optional[str]] = mapped_column(String(100))
    face_login_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.role_id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    role: Mapped[Role] = relationship()


class Status(Base):
    __tablename__ = "statuses"

    status_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)


class Group(Base):
    __tablename__ = "groups"

    group_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())


class Camera(Base):
    __tablename__ = "cameras"

    camera_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    stream_url: Mapped[Optional[str]] = mapped_column(String(500))
    status_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("statuses.status_id", ondelete="SET NULL")
    )
    location: Mapped[Optional[str]] = mapped_column(String(255))
    group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("groups.group_id", ondelete="SET NULL")
    )
    detection_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    recording_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="continuous", server_default="continuous"
    )  # continuous | event
    # Phase 2: ONVIF tracking
    tracking_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    tracking_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="off", server_default="off")  # off | auto | patrol
    tracking_target_person_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("persons.person_id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False))

    status: Mapped[Optional[Status]] = relationship()
    group: Mapped[Optional[Group]] = relationship()


class CameraEndpoint(Base):
    __tablename__ = "camera_endpoints"
    __table_args__ = (
        UniqueConstraint("camera_id", "endpoint_kind", "endpoint_url", name="camera_endpoints_unique"),
        CheckConstraint("endpoint_kind IN ('onvif', 'rtsp', 'http')", name="camera_endpoints_kind_chk"),
    )

    camera_endpoint_id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False)
    endpoint_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(500), nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(100))
    password_secret: Mapped[Optional[str]] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    camera: Mapped[Camera] = relationship()


class VideoStream(Base):
    __tablename__ = "video_streams"

    video_stream_id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False)
    resolution: Mapped[Optional[str]] = mapped_column(String(50))
    fps: Mapped[Optional[int]] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    stream_url: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    camera: Mapped[Camera] = relationship()


class StorageTarget(Base):
    __tablename__ = "storage_targets"
    __table_args__ = (
        UniqueConstraint("name", name="storage_targets_name_unique"),
        CheckConstraint(
            "(total_gb IS NULL OR total_gb >= 0) AND (reserved_gb IS NULL OR reserved_gb >= 0) AND (retention_days IS NULL OR retention_days >= 0)",
            name="storage_targets_positive_chk",
        ),
        CheckConstraint("device_kind IN ('ssd', 'hdd', 'microsd', 'network', 'cloud', 'other')", name="storage_targets_kind_chk"),
        CheckConstraint("purpose IN ('system', 'recording', 'backup', 'export')", name="storage_targets_purpose_chk"),
        CheckConstraint("is_primary_recording = FALSE OR purpose = 'recording'", name="storage_targets_primary_chk"),
        CheckConstraint("storage_type IN ('local', 'network', 's3', 'ftp')", name="storage_targets_type_chk"),
    )

    storage_target_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    root_path: Mapped[str] = mapped_column(String(500), nullable=False)
    total_gb: Mapped[Optional[Numeric]] = mapped_column(Numeric(10, 2))
    reserved_gb: Mapped[Optional[Numeric]] = mapped_column(Numeric(10, 2))
    retention_days: Mapped[Optional[int]] = mapped_column(Integer)
    device_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="ssd", server_default="ssd")
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, default="recording", server_default="recording")
    is_primary_recording: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # Phase 4: Cloud storage
    storage_type: Mapped[str] = mapped_column(String(20), nullable=False, default="local", server_default="local")
    connection_config: Mapped[Optional[str]] = mapped_column(Text)  # JSON blob for S3/FTP configs
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())


class UserMfaMethod(Base):
    __tablename__ = "user_mfa_methods"
    __table_args__ = (
        UniqueConstraint("user_id", "mfa_type", "destination", name="user_mfa_methods_unique"),
        CheckConstraint("mfa_type IN ('totp', 'sms', 'email')", name="user_mfa_methods_type_chk"),
    )

    user_mfa_id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    mfa_type: Mapped[str] = mapped_column(String(20), nullable=False)
    secret: Mapped[Optional[str]] = mapped_column(String(255))
    destination: Mapped[Optional[str]] = mapped_column(String(150))
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False))

    user: Mapped[User] = relationship()


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        CheckConstraint(
            "(quiet_hours_from IS NULL OR (quiet_hours_from >= 0 AND quiet_hours_from <= 23)) AND "
            "(quiet_hours_to IS NULL OR (quiet_hours_to >= 0 AND quiet_hours_to <= 23))",
            name="notification_preferences_quiet_chk",
        ),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    enable_push: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    enable_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    enable_sms: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    quiet_hours_from: Mapped[Optional[int]] = mapped_column(SmallInteger)
    quiet_hours_to: Mapped[Optional[int]] = mapped_column(SmallInteger)

    user: Mapped[User] = relationship()


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("token", name="push_subscriptions_token_unique"),)

    push_subscription_id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    device_info: Mapped[Optional[str]] = mapped_column(String(200))
    token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False))

    user: Mapped[User] = relationship()


class EventType(Base):
    __tablename__ = "event_types"

    event_type_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class PersonCategory(Base):
    __tablename__ = "person_categories"

    person_category_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class Person(Base):
    __tablename__ = "persons"

    person_id: Mapped[int] = mapped_column(primary_key=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    middle_name: Mapped[Optional[str]] = mapped_column(String(100))
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("person_categories.person_category_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False))

    category: Mapped[Optional[PersonCategory]] = relationship()
    embeddings_list: Mapped[list["PersonEmbedding"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )


class PersonEmbedding(Base):
    __tablename__ = "person_embeddings"

    person_embedding_id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.person_id", ondelete="CASCADE"), nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    person: Mapped[Person] = relationship(back_populates="embeddings_list")


class RecordingFile(Base):
    __tablename__ = "recording_files"
    __table_args__ = (
        UniqueConstraint("file_path", name="recording_files_unique_path"),
        CheckConstraint("file_kind IN ('video', 'snapshot')", name="recording_files_kind_chk"),
        CheckConstraint("file_size_bytes IS NULL OR file_size_bytes >= 0", name="recording_files_size_chk"),
    )

    recording_file_id: Mapped[int] = mapped_column(primary_key=True)
    video_stream_id: Mapped[int] = mapped_column(ForeignKey("video_streams.video_stream_id", ondelete="CASCADE"), nullable=False)
    storage_target_id: Mapped[int] = mapped_column(ForeignKey("storage_targets.storage_target_id", ondelete="RESTRICT"), nullable=False)
    file_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False))
    duration_seconds: Mapped[Optional[Numeric]] = mapped_column(Numeric(12, 2))
    file_size_bytes: Mapped[Optional[Numeric]] = mapped_column(Numeric(20, 0))
    checksum: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    video_stream: Mapped[VideoStream] = relationship()
    storage_target: Mapped[StorageTarget] = relationship()


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 100)", name="events_confidence_chk"),
    )

    event_id: Mapped[int] = mapped_column(primary_key=True)
    event_ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.camera_id", ondelete="RESTRICT"), nullable=False)
    event_type_id: Mapped[int] = mapped_column(ForeignKey("event_types.event_type_id", ondelete="RESTRICT"), nullable=False)
    person_id: Mapped[Optional[int]] = mapped_column(ForeignKey("persons.person_id", ondelete="SET NULL"))
    recording_file_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recording_files.recording_file_id", ondelete="SET NULL"))
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"))
    confidence: Mapped[Optional[Numeric]] = mapped_column(Numeric(5, 2))
    # Phase 1: processor source
    processor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("processors.processor_id", ondelete="SET NULL"))
    # Phase 3: object tracking
    track_id: Mapped[Optional[int]] = mapped_column(Integer)

    camera: Mapped[Camera] = relationship()
    event_type: Mapped[EventType] = relationship()
    person: Mapped[Optional[Person]] = relationship()
    recording_file: Mapped[Optional[RecordingFile]] = relationship()
    created_by_user: Mapped[Optional[User]] = relationship()


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="notifications_severity_chk"),
    )

    notification_id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[Optional[int]] = mapped_column(ForeignKey("events.event_id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text)
    severity: Mapped[Optional[str]] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"))

    event: Mapped[Optional[Event]] = relationship()
    created_by_user: Mapped[Optional[User]] = relationship()


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        CheckConstraint("channel IN ('push', 'email', 'sms')", name="notification_deliveries_channel_chk"),
        CheckConstraint("status IN ('pending', 'sent', 'failed')", name="notification_deliveries_status_chk"),
    )

    notification_delivery_id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(
        ForeignKey("notifications.notification_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False))
    error_message: Mapped[Optional[str]] = mapped_column(String(255))

    notification: Mapped[Notification] = relationship()
    user: Mapped[User] = relationship()


class EventReview(Base):
    __tablename__ = "event_reviews"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="event_reviews_status_chk"),
    )

    event_review_id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.event_id", ondelete="CASCADE"), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    reviewer_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"))
    person_id: Mapped[Optional[int]] = mapped_column(ForeignKey("persons.person_id", ondelete="SET NULL"))
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    event: Mapped[Event] = relationship()
    reviewer: Mapped[Optional[User]] = relationship(foreign_keys=[reviewer_user_id])
    person: Mapped[Optional[Person]] = relationship()


class AuthEvent(Base):
    __tablename__ = "auth_events"

    auth_event_id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"))
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255))
    source_ip: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    user: Mapped[Optional[User]] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (CheckConstraint("action IN ('INSERT', 'UPDATE', 'DELETE')", name="audit_log_action_chk"),)

    audit_id: Mapped[int] = mapped_column(primary_key=True)
    table_name: Mapped[str] = mapped_column(String(100), nullable=False)
    record_pk: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    changed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"))
    source_ip: Mapped[Optional[str]] = mapped_column(String(45))
    change_data: Mapped[Optional[str]] = mapped_column(Text)

    changed_by_user: Mapped[Optional[User]] = relationship()


class UserFaceTemplate(Base):
    __tablename__ = "user_face_templates"
    __table_args__ = (
        CheckConstraint("distance_metric IN ('cosine', 'l2')", name="user_face_templates_metric_chk"),
    )

    user_face_id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(50))
    distance_metric: Mapped[str] = mapped_column(String(20), nullable=False, default="cosine", server_default="cosine")
    threshold: Mapped[Optional[Numeric]] = mapped_column(Numeric(5, 3))
    quality_score: Mapped[Optional[Numeric]] = mapped_column(Numeric(5, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship()


# Indexes (including partials)
Index("users_role_idx", User.role_id)
Index("cameras_status_idx", Camera.status_id)
Index("cameras_group_idx", Camera.group_id)
Index("camera_endpoints_camera_idx", CameraEndpoint.camera_id)
Index("video_streams_camera_idx", VideoStream.camera_id)
Index("user_mfa_methods_user_idx", UserMfaMethod.user_id)
Index("push_subscriptions_user_idx", PushSubscription.user_id)
Index("events_camera_idx", Event.camera_id)
Index("events_event_type_idx", Event.event_type_id)
Index("events_person_idx", Event.person_id)
Index("events_recording_idx", Event.recording_file_id)
Index("events_ts_idx", Event.event_ts)
Index("recording_files_stream_idx", RecordingFile.video_stream_id)
Index("recording_files_started_idx", RecordingFile.started_at)
Index("recording_files_storage_idx", RecordingFile.storage_target_id)
Index("notifications_event_idx", Notification.event_id)
Index("notifications_created_at_idx", Notification.created_at)
Index("notification_deliveries_user_idx", NotificationDelivery.user_id)
Index("notification_deliveries_notification_idx", NotificationDelivery.notification_id)
Index("notification_deliveries_channel_idx", NotificationDelivery.channel)
Index("auth_events_user_idx", AuthEvent.user_id)
Index("auth_events_method_idx", AuthEvent.method)
Index("auth_events_ts_idx", AuthEvent.occurred_at)
Index("persons_category_idx", Person.category_id)
Index("user_face_templates_user_idx", UserFaceTemplate.user_id)
Index("event_reviews_status_idx", EventReview.status)
Index("event_reviews_reviewer_idx", EventReview.reviewer_user_id)
Index("audit_log_table_idx", AuditLog.table_name)
Index("audit_log_changed_at_idx", AuditLog.changed_at)
Index("audit_log_changed_by_idx", AuditLog.changed_by)


# ── Phase 1: Processor Microservice ──

class Processor(Base):
    __tablename__ = "processors"

    processor_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    api_key_id: Mapped[Optional[int]] = mapped_column(ForeignKey("api_keys.api_key_id", ondelete="SET NULL"))
    hostname: Mapped[Optional[str]] = mapped_column(String(255))
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    os_info: Mapped[Optional[str]] = mapped_column(String(255))
    version: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="registered", server_default="registered")
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False))
    last_metrics: Mapped[Optional[str]] = mapped_column(Text)
    capabilities: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())


class ProcessorConnectionCode(Base):
    __tablename__ = "processor_connection_codes"

    code_id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False))
    used_by_processor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("processors.processor_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    created_by: Mapped[User] = relationship()


class ProcessorCameraAssignment(Base):
    __tablename__ = "processor_camera_assignments"

    processor_id: Mapped[int] = mapped_column(ForeignKey("processors.processor_id", ondelete="CASCADE"), primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.camera_id", ondelete="CASCADE"), primary_key=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    processor: Mapped[Processor] = relationship()
    camera: Mapped[Camera] = relationship()


# ── Phase 2: Camera Presets ──

class CameraPreset(Base):
    __tablename__ = "camera_presets"

    camera_preset_id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    preset_token: Mapped[Optional[str]] = mapped_column(String(100))
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    dwell_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10, server_default="10")

    camera: Mapped[Camera] = relationship()


# ── Phase 3: ROI Zones ──

class CameraRoiZone(Base):
    __tablename__ = "camera_roi_zones"
    __table_args__ = (
        CheckConstraint("zone_type IN ('include', 'exclude')", name="camera_roi_zones_type_chk"),
    )

    roi_zone_id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.camera_id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    zone_type: Mapped[str] = mapped_column(String(20), nullable=False, default="include", server_default="include")
    polygon_points: Mapped[Optional[str]] = mapped_column(Text)  # JSON array of {x, y}

    camera: Mapped[Camera] = relationship()


# ── Phase 5: Homes (Xiaomi Home style) ──

class ApiKey(Base):
    __tablename__ = "api_keys"

    api_key_id: Mapped[int] = mapped_column(primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    scopes: Mapped[Optional[str]] = mapped_column(Text)  # comma-separated
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())


# ── Additional Indexes ──

Index("processors_status_idx", Processor.status)
Index("processor_assignments_camera_idx", ProcessorCameraAssignment.camera_id)
Index("camera_presets_camera_idx", CameraPreset.camera_id)
Index("camera_roi_zones_camera_idx", CameraRoiZone.camera_id)
Index("events_processor_idx", Event.processor_id)
Index("cameras_deleted_at_idx", Camera.deleted_at)
Index("persons_deleted_at_idx", Person.deleted_at)
