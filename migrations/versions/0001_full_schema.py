"""full schema - all tables

Revision ID: 0001
Revises:
Create Date: 2026-03-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Lookup tables (no FK dependencies) ──

    op.create_table('roles',
        sa.Column('role_id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(50), unique=True, nullable=False),
    )

    op.create_table('statuses',
        sa.Column('status_id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(50), unique=True, nullable=False),
    )

    op.create_table('event_types',
        sa.Column('event_type_id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), unique=True, nullable=False),
    )

    op.create_table('person_categories',
        sa.Column('person_category_id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), unique=True, nullable=False),
    )

    # ── Profiles ──

    op.create_table('profiles',
        sa.Column('profile_id', sa.Integer(), primary_key=True),
        sa.Column('last_name', sa.String(100)),
        sa.Column('first_name', sa.String(100)),
        sa.Column('middle_name', sa.String(100)),
        sa.Column('email', sa.String(150), unique=True),
        sa.Column('phone', sa.String(30)),
    )
    op.create_index('profiles_phone_unique_idx', 'profiles', ['phone'], unique=True,
                    postgresql_where=sa.text('phone IS NOT NULL'))

    # ── Users ──

    op.create_table('users',
        sa.Column('user_id', sa.Integer(), primary_key=True),
        sa.Column('login', sa.String(80), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('face_login_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('role_id', sa.Integer(), sa.ForeignKey('roles.role_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('profile_id', sa.Integer(), sa.ForeignKey('profiles.profile_id', ondelete='SET NULL'), unique=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('users_role_idx', 'users', ['role_id'])

    # ── Persons ──

    op.create_table('persons',
        sa.Column('person_id', sa.Integer(), primary_key=True),
        sa.Column('last_name', sa.String(100)),
        sa.Column('first_name', sa.String(100)),
        sa.Column('middle_name', sa.String(100)),
        sa.Column('embeddings', sa.LargeBinary()),
        sa.Column('category_id', sa.Integer(), sa.ForeignKey('person_categories.person_category_id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('persons_category_idx', 'persons', ['category_id'])

    # ── Cameras ──

    op.create_table('cameras',
        sa.Column('camera_id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('stream_url', sa.String(500)),
        sa.Column('status_id', sa.Integer(), sa.ForeignKey('statuses.status_id', ondelete='SET NULL')),
        sa.Column('location', sa.String(255)),
        sa.Column('detection_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('recording_mode', sa.String(20), nullable=False, server_default='continuous'),
        sa.Column('tracking_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('tracking_mode', sa.String(20), nullable=False, server_default='off'),
        sa.Column('tracking_target_person_id', sa.Integer(), sa.ForeignKey('persons.person_id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('cameras_status_idx', 'cameras', ['status_id'])

    # ── Camera Endpoints ──

    op.create_table('camera_endpoints',
        sa.Column('camera_endpoint_id', sa.Integer(), primary_key=True),
        sa.Column('camera_id', sa.Integer(), sa.ForeignKey('cameras.camera_id', ondelete='CASCADE'), nullable=False),
        sa.Column('endpoint_kind', sa.String(20), nullable=False),
        sa.Column('endpoint_url', sa.String(500), nullable=False),
        sa.Column('username', sa.String(100)),
        sa.Column('password_secret', sa.String(255)),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('camera_id', 'endpoint_kind', 'endpoint_url', name='camera_endpoints_unique'),
        sa.CheckConstraint("endpoint_kind IN ('onvif', 'rtsp', 'http')", name='camera_endpoints_kind_chk'),
    )
    op.create_index('camera_endpoints_camera_idx', 'camera_endpoints', ['camera_id'])

    # ── Video Streams ──

    op.create_table('video_streams',
        sa.Column('video_stream_id', sa.Integer(), primary_key=True),
        sa.Column('camera_id', sa.Integer(), sa.ForeignKey('cameras.camera_id', ondelete='CASCADE'), nullable=False),
        sa.Column('resolution', sa.String(50)),
        sa.Column('fps', sa.Integer()),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('stream_url', sa.String(500)),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('video_streams_camera_idx', 'video_streams', ['camera_id'])

    # ── Storage Targets ──

    op.create_table('storage_targets',
        sa.Column('storage_target_id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('root_path', sa.String(500), nullable=False),
        sa.Column('total_gb', sa.Numeric(10, 2)),
        sa.Column('reserved_gb', sa.Numeric(10, 2)),
        sa.Column('retention_days', sa.Integer()),
        sa.Column('device_kind', sa.String(20), nullable=False, server_default='ssd'),
        sa.Column('purpose', sa.String(20), nullable=False, server_default='recording'),
        sa.Column('is_primary_recording', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('storage_type', sa.String(20), nullable=False, server_default='local'),
        sa.Column('connection_config', sa.Text()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('name', name='storage_targets_name_unique'),
        sa.CheckConstraint(
            "(total_gb IS NULL OR total_gb >= 0) AND (reserved_gb IS NULL OR reserved_gb >= 0) AND (retention_days IS NULL OR retention_days >= 0)",
            name='storage_targets_positive_chk'),
        sa.CheckConstraint("device_kind IN ('ssd', 'hdd', 'microsd', 'network', 'cloud', 'other')", name='storage_targets_kind_chk'),
        sa.CheckConstraint("purpose IN ('system', 'recording', 'backup', 'export')", name='storage_targets_purpose_chk'),
        sa.CheckConstraint("is_primary_recording = FALSE OR purpose = 'recording'", name='storage_targets_primary_chk'),
        sa.CheckConstraint("storage_type IN ('local', 'network', 's3', 'ftp')", name='storage_targets_type_chk'),
    )

    # ── Recording Files ──

    op.create_table('recording_files',
        sa.Column('recording_file_id', sa.Integer(), primary_key=True),
        sa.Column('video_stream_id', sa.Integer(), sa.ForeignKey('video_streams.video_stream_id', ondelete='CASCADE'), nullable=False),
        sa.Column('storage_target_id', sa.Integer(), sa.ForeignKey('storage_targets.storage_target_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('file_kind', sa.String(20), nullable=False),
        sa.Column('file_path', sa.String(1000), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('ended_at', sa.DateTime()),
        sa.Column('duration_seconds', sa.Numeric(12, 2)),
        sa.Column('file_size_bytes', sa.Numeric(20, 0)),
        sa.Column('checksum', sa.String(100)),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('file_path', name='recording_files_unique_path'),
        sa.CheckConstraint("file_kind IN ('video', 'snapshot')", name='recording_files_kind_chk'),
        sa.CheckConstraint("file_size_bytes IS NULL OR file_size_bytes >= 0", name='recording_files_size_chk'),
    )
    op.create_index('recording_files_stream_idx', 'recording_files', ['video_stream_id'])
    op.create_index('recording_files_started_idx', 'recording_files', ['started_at'])
    op.create_index('recording_files_storage_idx', 'recording_files', ['storage_target_id'])

    # ── Groups ──

    op.create_table('groups',
        sa.Column('group_id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(150), unique=True, nullable=False),
        sa.Column('description', sa.String(500)),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ── User Camera Permissions ──

    op.create_table('user_camera_permissions',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('camera_id', sa.Integer(), sa.ForeignKey('cameras.camera_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('permission', sa.String(20), primary_key=True),
        sa.Column('granted_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("permission IN ('view', 'control', 'admin')", name='user_camera_permissions_chk'),
    )
    op.create_index('user_camera_permissions_camera_idx', 'user_camera_permissions', ['camera_id'])

    # ── Group Camera Permissions ──

    op.create_table('group_camera_permissions',
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.group_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('camera_id', sa.Integer(), sa.ForeignKey('cameras.camera_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('target_role', sa.String(10), primary_key=True, server_default='member'),
        sa.Column('permission', sa.String(20), primary_key=True),
        sa.Column('granted_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("permission IN ('view', 'control', 'admin')", name='group_camera_permissions_chk'),
        sa.CheckConstraint("target_role IN ('admin', 'member')", name='group_camera_permissions_target_chk'),
    )
    op.create_index('group_camera_permissions_camera_idx', 'group_camera_permissions', ['camera_id'])

    # ── User Groups ──

    op.create_table('user_groups',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('groups.group_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('membership_role', sa.String(10), nullable=False, server_default='member'),
        sa.Column('invited_by', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("membership_role IN ('owner', 'admin', 'member')", name='user_groups_role_chk'),
    )
    op.create_index('user_groups_group_idx', 'user_groups', ['group_id'])

    # ── User MFA Methods ──

    op.create_table('user_mfa_methods',
        sa.Column('user_mfa_id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False),
        sa.Column('mfa_type', sa.String(20), nullable=False),
        sa.Column('secret', sa.String(255)),
        sa.Column('destination', sa.String(150)),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('last_used_at', sa.DateTime()),
        sa.UniqueConstraint('user_id', 'mfa_type', 'destination', name='user_mfa_methods_unique'),
        sa.CheckConstraint("mfa_type IN ('totp', 'sms', 'email')", name='user_mfa_methods_type_chk'),
    )
    op.create_index('user_mfa_methods_user_idx', 'user_mfa_methods', ['user_id'])

    # ── Notification Preferences ──

    op.create_table('notification_preferences',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('enable_push', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('enable_email', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('enable_sms', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('quiet_hours_from', sa.SmallInteger()),
        sa.Column('quiet_hours_to', sa.SmallInteger()),
        sa.CheckConstraint(
            "(quiet_hours_from IS NULL OR (quiet_hours_from >= 0 AND quiet_hours_from <= 23)) AND "
            "(quiet_hours_to IS NULL OR (quiet_hours_to >= 0 AND quiet_hours_to <= 23))",
            name='notification_preferences_quiet_chk'),
    )

    # ── Push Subscriptions ──

    op.create_table('push_subscriptions',
        sa.Column('push_subscription_id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False),
        sa.Column('device_info', sa.String(200)),
        sa.Column('token', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime()),
        sa.UniqueConstraint('token', name='push_subscriptions_token_unique'),
    )
    op.create_index('push_subscriptions_user_idx', 'push_subscriptions', ['user_id'])

    # ── API Keys ──

    op.create_table('api_keys',
        sa.Column('api_key_id', sa.Integer(), primary_key=True),
        sa.Column('key_hash', sa.String(255), unique=True, nullable=False),
        sa.Column('description', sa.String(255)),
        sa.Column('scopes', sa.Text()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('expires_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ── Processors (Phase 1) ──

    op.create_table('processors',
        sa.Column('processor_id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('api_key_id', sa.Integer(), sa.ForeignKey('api_keys.api_key_id', ondelete='SET NULL')),
        sa.Column('hostname', sa.String(255)),
        sa.Column('status', sa.String(20), nullable=False, server_default='registered'),
        sa.Column('last_heartbeat', sa.DateTime()),
        sa.Column('capabilities', sa.Text()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('processors_status_idx', 'processors', ['status'])

    # ── Processor Camera Assignments ──

    op.create_table('processor_camera_assignments',
        sa.Column('processor_id', sa.Integer(), sa.ForeignKey('processors.processor_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('camera_id', sa.Integer(), sa.ForeignKey('cameras.camera_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('assigned_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('processor_assignments_camera_idx', 'processor_camera_assignments', ['camera_id'])

    # ── Events ──

    op.create_table('events',
        sa.Column('event_id', sa.Integer(), primary_key=True),
        sa.Column('event_ts', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('camera_id', sa.Integer(), sa.ForeignKey('cameras.camera_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('event_type_id', sa.Integer(), sa.ForeignKey('event_types.event_type_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('persons.person_id', ondelete='SET NULL')),
        sa.Column('recording_file_id', sa.Integer(), sa.ForeignKey('recording_files.recording_file_id', ondelete='SET NULL')),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='SET NULL')),
        sa.Column('confidence', sa.Numeric(5, 2)),
        sa.Column('processor_id', sa.Integer(), sa.ForeignKey('processors.processor_id', ondelete='SET NULL')),
        sa.Column('track_id', sa.Integer()),
        sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 100)", name='events_confidence_chk'),
    )
    op.create_index('events_camera_idx', 'events', ['camera_id'])
    op.create_index('events_event_type_idx', 'events', ['event_type_id'])
    op.create_index('events_person_idx', 'events', ['person_id'])
    op.create_index('events_recording_idx', 'events', ['recording_file_id'])
    op.create_index('events_ts_idx', 'events', ['event_ts'])
    op.create_index('events_processor_idx', 'events', ['processor_id'])

    # ── Notifications ──

    op.create_table('notifications',
        sa.Column('notification_id', sa.Integer(), primary_key=True),
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('events.event_id', ondelete='CASCADE')),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text()),
        sa.Column('severity', sa.String(20)),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='SET NULL')),
        sa.CheckConstraint("severity IN ('info', 'warning', 'critical')", name='notifications_severity_chk'),
    )
    op.create_index('notifications_event_idx', 'notifications', ['event_id'])
    op.create_index('notifications_created_at_idx', 'notifications', ['created_at'])

    # ── Notification Deliveries ──

    op.create_table('notification_deliveries',
        sa.Column('notification_delivery_id', sa.Integer(), primary_key=True),
        sa.Column('notification_id', sa.Integer(), sa.ForeignKey('notifications.notification_id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False),
        sa.Column('channel', sa.String(10), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('sent_at', sa.DateTime()),
        sa.Column('error_message', sa.String(255)),
        sa.CheckConstraint("channel IN ('push', 'email', 'sms')", name='notification_deliveries_channel_chk'),
        sa.CheckConstraint("status IN ('pending', 'sent', 'failed')", name='notification_deliveries_status_chk'),
    )
    op.create_index('notification_deliveries_user_idx', 'notification_deliveries', ['user_id'])
    op.create_index('notification_deliveries_notification_idx', 'notification_deliveries', ['notification_id'])
    op.create_index('notification_deliveries_channel_idx', 'notification_deliveries', ['channel'])

    # ── Event Reviews ──

    op.create_table('event_reviews',
        sa.Column('event_review_id', sa.Integer(), primary_key=True),
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('events.event_id', ondelete='CASCADE'), unique=True, nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('reviewer_user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='SET NULL')),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('persons.person_id', ondelete='SET NULL')),
        sa.Column('note', sa.Text()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name='event_reviews_status_chk'),
    )
    op.create_index('event_reviews_status_idx', 'event_reviews', ['status'])
    op.create_index('event_reviews_reviewer_idx', 'event_reviews', ['reviewer_user_id'])

    # ── Auth Events ──

    op.create_table('auth_events',
        sa.Column('auth_event_id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='SET NULL')),
        sa.Column('method', sa.String(30), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.String(255)),
        sa.Column('source_ip', sa.String(45)),
        sa.Column('user_agent', sa.String(255)),
        sa.Column('occurred_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('auth_events_user_idx', 'auth_events', ['user_id'])
    op.create_index('auth_events_method_idx', 'auth_events', ['method'])
    op.create_index('auth_events_ts_idx', 'auth_events', ['occurred_at'])

    # ── Audit Log ──

    op.create_table('audit_log',
        sa.Column('audit_id', sa.Integer(), primary_key=True),
        sa.Column('table_name', sa.String(100), nullable=False),
        sa.Column('record_pk', sa.String(100), nullable=False),
        sa.Column('action', sa.String(10), nullable=False),
        sa.Column('changed_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('changed_by', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='SET NULL')),
        sa.Column('source_ip', sa.String(45)),
        sa.Column('change_data', sa.Text()),
        sa.CheckConstraint("action IN ('INSERT', 'UPDATE', 'DELETE')", name='audit_log_action_chk'),
    )
    op.create_index('audit_log_table_idx', 'audit_log', ['table_name'])
    op.create_index('audit_log_changed_at_idx', 'audit_log', ['changed_at'])
    op.create_index('audit_log_changed_by_idx', 'audit_log', ['changed_by'])

    # ── User Face Templates ──

    op.create_table('user_face_templates',
        sa.Column('user_face_id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False),
        sa.Column('embedding', sa.LargeBinary(), nullable=False),
        sa.Column('model', sa.String(50)),
        sa.Column('distance_metric', sa.String(20), nullable=False, server_default='cosine'),
        sa.Column('threshold', sa.Numeric(5, 3)),
        sa.Column('quality_score', sa.Numeric(5, 2)),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("distance_metric IN ('cosine', 'l2')", name='user_face_templates_metric_chk'),
    )
    op.create_index('user_face_templates_user_idx', 'user_face_templates', ['user_id'])

    # ── Camera Presets (Phase 2) ──

    op.create_table('camera_presets',
        sa.Column('camera_preset_id', sa.Integer(), primary_key=True),
        sa.Column('camera_id', sa.Integer(), sa.ForeignKey('cameras.camera_id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('preset_token', sa.String(100)),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('dwell_seconds', sa.Integer(), nullable=False, server_default='10'),
    )
    op.create_index('camera_presets_camera_idx', 'camera_presets', ['camera_id'])

    # ── Camera ROI Zones (Phase 3) ──

    op.create_table('camera_roi_zones',
        sa.Column('roi_zone_id', sa.Integer(), primary_key=True),
        sa.Column('camera_id', sa.Integer(), sa.ForeignKey('cameras.camera_id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('zone_type', sa.String(20), nullable=False, server_default='include'),
        sa.Column('polygon_points', sa.Text()),
        sa.CheckConstraint("zone_type IN ('include', 'exclude')", name='camera_roi_zones_type_chk'),
    )
    op.create_index('camera_roi_zones_camera_idx', 'camera_roi_zones', ['camera_id'])

    # ── Homes (Phase 5) ──

    op.create_table('homes',
        sa.Column('home_id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('description', sa.String(500)),
        sa.Column('invite_code', sa.String(100), unique=True),
        sa.Column('invite_code_expires_at', sa.DateTime()),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('homes_created_by_idx', 'homes', ['created_by_user_id'])

    op.create_table('rooms',
        sa.Column('room_id', sa.Integer(), primary_key=True),
        sa.Column('home_id', sa.Integer(), sa.ForeignKey('homes.home_id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('rooms_home_idx', 'rooms', ['home_id'])

    op.create_table('room_cameras',
        sa.Column('room_id', sa.Integer(), sa.ForeignKey('rooms.room_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('camera_id', sa.Integer(), sa.ForeignKey('cameras.camera_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('added_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('room_cameras_camera_idx', 'room_cameras', ['camera_id'])

    op.create_table('home_members',
        sa.Column('home_id', sa.Integer(), sa.ForeignKey('homes.home_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('role', sa.String(20), nullable=False, server_default='member'),
        sa.Column('invited_by', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='SET NULL')),
        sa.Column('invited_at', sa.DateTime()),
        sa.Column('joined_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member', 'guest')", name='home_members_role_chk'),
    )
    op.create_index('home_members_user_idx', 'home_members', ['user_id'])

    op.create_table('home_invitations',
        sa.Column('invitation_id', sa.Integer(), primary_key=True),
        sa.Column('home_id', sa.Integer(), sa.ForeignKey('homes.home_id', ondelete='CASCADE'), nullable=False),
        sa.Column('invited_by_user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False),
        sa.Column('invite_type', sa.String(20), nullable=False, server_default='link'),
        sa.Column('invite_code', sa.String(100), unique=True, nullable=False),
        sa.Column('target_email', sa.String(255)),
        sa.Column('role', sa.String(20), nullable=False, server_default='member'),
        sa.Column('expires_at', sa.DateTime()),
        sa.Column('accepted_at', sa.DateTime()),
        sa.Column('accepted_by_user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='SET NULL')),
        sa.CheckConstraint("invite_type IN ('link', 'email', 'qr')", name='home_invitations_type_chk'),
        sa.CheckConstraint("role IN ('admin', 'member', 'guest')", name='home_invitations_role_chk'),
    )
    op.create_index('home_invitations_home_idx', 'home_invitations', ['home_id'])
    op.create_index('home_invitations_code_idx', 'home_invitations', ['invite_code'])

    op.create_table('home_activity_log',
        sa.Column('activity_id', sa.Integer(), primary_key=True),
        sa.Column('home_id', sa.Integer(), sa.ForeignKey('homes.home_id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.user_id', ondelete='SET NULL')),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('details', sa.Text()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('home_activity_home_idx', 'home_activity_log', ['home_id'])
    op.create_index('home_activity_created_idx', 'home_activity_log', ['created_at'])

    # ── Person embeddings (multi-embedding support) ──
    op.create_table(
        'person_embeddings',
        sa.Column('person_embedding_id', sa.Integer(), primary_key=True),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('persons.person_id', ondelete='CASCADE'), nullable=False),
        sa.Column('embedding', sa.LargeBinary(), nullable=False),
        sa.Column('source', sa.String(50)),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('person_embeddings_person_idx', 'person_embeddings', ['person_id'])

    # ── Seed data ──

    op.execute("INSERT INTO roles (role_id, name) VALUES (1, 'system_admin'), (2, 'user') ON CONFLICT DO NOTHING")
    op.execute("INSERT INTO statuses (status_id, name) VALUES (1, 'active'), (2, 'inactive'), (3, 'maintenance') ON CONFLICT DO NOTHING")
    op.execute("INSERT INTO event_types (event_type_id, name) VALUES (1, 'face_recognized'), (2, 'face_unknown'), (3, 'motion'), (4, 'person_entered'), (5, 'person_left') ON CONFLICT DO NOTHING")
    op.execute("INSERT INTO person_categories (person_category_id, name) VALUES (1, 'employee'), (2, 'visitor'), (3, 'unknown'), (4, 'blocked') ON CONFLICT DO NOTHING")


def downgrade() -> None:
    op.drop_table('home_activity_log')
    op.drop_table('home_invitations')
    op.drop_table('home_members')
    op.drop_table('room_cameras')
    op.drop_table('rooms')
    op.drop_table('homes')
    op.drop_table('camera_roi_zones')
    op.drop_table('camera_presets')
    op.drop_table('user_face_templates')
    op.drop_table('audit_log')
    op.drop_table('auth_events')
    op.drop_table('event_reviews')
    op.drop_table('notification_deliveries')
    op.drop_table('notifications')
    op.drop_table('events')
    op.drop_table('processor_camera_assignments')
    op.drop_table('processors')
    op.drop_table('api_keys')
    op.drop_table('push_subscriptions')
    op.drop_table('notification_preferences')
    op.drop_table('user_mfa_methods')
    op.drop_table('user_groups')
    op.drop_table('group_camera_permissions')
    op.drop_table('user_camera_permissions')
    op.drop_table('groups')
    op.drop_table('recording_files')
    op.drop_table('storage_targets')
    op.drop_table('video_streams')
    op.drop_table('camera_endpoints')
    op.drop_table('cameras')
    op.drop_table('persons')
    op.drop_table('users')
    op.drop_table('profiles')
    op.drop_table('person_categories')
    op.drop_table('event_types')
    op.drop_table('statuses')
    op.drop_table('roles')
