-- DDL for PostgreSQL 8.1 (3NF) based on the provided diagram
-- Theme: Video surveillance with recognition

BEGIN;

-- Roles for users
CREATE TABLE roles (
    role_id    SERIAL PRIMARY KEY,
    name       VARCHAR(50) NOT NULL,
    CONSTRAINT roles_name_unique UNIQUE (name)
);

-- User profiles (one per user)
CREATE TABLE profiles (
    profile_id   SERIAL PRIMARY KEY,
    last_name    VARCHAR(100),
    first_name   VARCHAR(100),
    middle_name  VARCHAR(100),
    email        VARCHAR(150),
    phone        VARCHAR(30),
    CONSTRAINT profiles_email_unique UNIQUE (email)
);
-- Allow only one non-null phone per profile (partial unique)
CREATE UNIQUE INDEX profiles_phone_unique_idx ON profiles(phone) WHERE phone IS NOT NULL;

-- Application users
CREATE TABLE users (
    user_id       SERIAL PRIMARY KEY,
    login         VARCHAR(80) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    face_login_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    role_id       INTEGER NOT NULL REFERENCES roles(role_id) ON DELETE RESTRICT,
    profile_id    INTEGER UNIQUE REFERENCES profiles(profile_id) ON DELETE SET NULL,
    created_at    TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT users_login_unique UNIQUE (login)
);
CREATE INDEX users_role_idx ON users(role_id);

-- User face templates for authentication
CREATE TABLE user_face_templates (
    user_face_id    SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    embedding       BYTEA NOT NULL,
    model           VARCHAR(50),
    distance_metric VARCHAR(20) NOT NULL DEFAULT 'cosine',
    threshold       NUMERIC(5,3),
    quality_score   NUMERIC(5,2),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT user_face_templates_metric_chk CHECK (distance_metric IN ('cosine', 'l2'))
);
CREATE INDEX user_face_templates_user_idx ON user_face_templates(user_id);

-- Status dictionary for cameras
CREATE TABLE statuses (
    status_id  SERIAL PRIMARY KEY,
    name       VARCHAR(50) NOT NULL,
    CONSTRAINT statuses_name_unique UNIQUE (name)
);

-- Cameras
CREATE TABLE cameras (
    camera_id    SERIAL PRIMARY KEY,
    name         VARCHAR(150) NOT NULL,
    ip_address   VARCHAR(45),
    stream_url   VARCHAR(500),
    status_id    INTEGER REFERENCES statuses(status_id) ON DELETE SET NULL,
    location     VARCHAR(255),
    created_at   TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX cameras_status_idx ON cameras(status_id);

-- Camera endpoints (ONVIF/RTSP/HTTP) with credentials if required
CREATE TABLE camera_endpoints (
    camera_endpoint_id SERIAL PRIMARY KEY,
    camera_id          INTEGER NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    endpoint_kind      VARCHAR(20) NOT NULL, -- onvif, rtsp, http
    endpoint_url       VARCHAR(500) NOT NULL,
    username           VARCHAR(100),
    password_secret    VARCHAR(255), -- store encrypted/hashed; avoid plain text if possible
    is_primary         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT camera_endpoints_kind_chk CHECK (endpoint_kind IN ('onvif', 'rtsp', 'http')),
    CONSTRAINT camera_endpoints_unique UNIQUE (camera_id, endpoint_kind, endpoint_url)
);
CREATE INDEX camera_endpoints_camera_idx ON camera_endpoints(camera_id);

-- Video streams (logical streams per camera)
CREATE TABLE video_streams (
    video_stream_id SERIAL PRIMARY KEY,
    camera_id       INTEGER NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    resolution      VARCHAR(50),
    fps             INTEGER,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    stream_url      VARCHAR(500),
    created_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX video_streams_camera_idx ON video_streams(camera_id);

-- Storage targets (e.g., mount points on Raspberry Pi)
CREATE TABLE storage_targets (
    storage_target_id SERIAL PRIMARY KEY,
    name              VARCHAR(100) NOT NULL,
    root_path         VARCHAR(500) NOT NULL,
    total_gb          NUMERIC(10,2),
    reserved_gb       NUMERIC(10,2),
    retention_days    INTEGER,
    device_kind       VARCHAR(20) NOT NULL DEFAULT 'ssd', -- ssd, hdd, microsd, network, other
    purpose           VARCHAR(20) NOT NULL DEFAULT 'recording', -- system, recording, backup, export
    is_primary_recording BOOLEAN NOT NULL DEFAULT FALSE,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT storage_targets_name_unique UNIQUE (name),
    CONSTRAINT storage_targets_root_unique UNIQUE (root_path),
    CONSTRAINT storage_targets_positive_chk CHECK (
        (total_gb IS NULL OR total_gb >= 0) AND
        (reserved_gb IS NULL OR reserved_gb >= 0) AND
        (retention_days IS NULL OR retention_days >= 0)
    ),
    CONSTRAINT storage_targets_kind_chk CHECK (device_kind IN ('ssd', 'hdd', 'microsd', 'network', 'other')),
    CONSTRAINT storage_targets_purpose_chk CHECK (purpose IN ('system', 'recording', 'backup', 'export')),
    CONSTRAINT storage_targets_primary_chk CHECK (is_primary_recording = FALSE OR purpose = 'recording')
);

-- User-to-camera permissions (view/control/admin)
CREATE TABLE user_camera_permissions (
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    camera_id  INTEGER NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    permission VARCHAR(20) NOT NULL,
    granted_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, camera_id, permission),
    CONSTRAINT user_camera_permissions_chk CHECK (permission IN ('view', 'control', 'admin'))
);
CREATE INDEX user_camera_permissions_camera_idx ON user_camera_permissions(camera_id);

-- Groups for shared permissions
CREATE TABLE groups (
    group_id    SERIAL PRIMARY KEY,
    name        VARCHAR(150) NOT NULL,
    description VARCHAR(500),
    created_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT groups_name_unique UNIQUE (name)
);

-- User membership in groups
CREATE TABLE user_groups (
    user_id  INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES groups(group_id) ON DELETE CASCADE,
    membership_role VARCHAR(10) NOT NULL DEFAULT 'member',
    invited_by INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, group_id),
    CONSTRAINT user_groups_role_chk CHECK (membership_role IN ('owner', 'admin', 'member'))
);
CREATE INDEX user_groups_group_idx ON user_groups(group_id);

-- Group-to-camera permissions (view/control/admin) per target role
CREATE TABLE group_camera_permissions (
    group_id    INTEGER NOT NULL REFERENCES groups(group_id) ON DELETE CASCADE,
    camera_id   INTEGER NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
    target_role VARCHAR(10) NOT NULL DEFAULT 'member',
    permission  VARCHAR(20) NOT NULL,
    granted_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (group_id, camera_id, target_role, permission),
    CONSTRAINT group_camera_permissions_chk CHECK (permission IN ('view', 'control', 'admin')),
    CONSTRAINT group_camera_permissions_target_chk CHECK (target_role IN ('admin', 'member'))
);
CREATE INDEX group_camera_permissions_camera_idx ON group_camera_permissions(camera_id);

-- Multi-factor authentication methods (TOTP/SMS/Email)
CREATE TABLE user_mfa_methods (
    user_mfa_id   SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    mfa_type      VARCHAR(20) NOT NULL, -- totp, sms, email
    secret        VARCHAR(255), -- store hashed/encrypted secret or seed
    destination   VARCHAR(150), -- phone/email for out-of-band channels
    is_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    last_used_at  TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT user_mfa_methods_type_chk CHECK (mfa_type IN ('totp', 'sms', 'email')),
    CONSTRAINT user_mfa_methods_unique UNIQUE (user_id, mfa_type, destination)
);
CREATE INDEX user_mfa_methods_user_idx ON user_mfa_methods(user_id);

-- Notification preferences per user
CREATE TABLE notification_preferences (
    user_id         INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    enable_push     BOOLEAN NOT NULL DEFAULT TRUE,
    enable_email    BOOLEAN NOT NULL DEFAULT TRUE,
    enable_sms      BOOLEAN NOT NULL DEFAULT FALSE,
    quiet_hours_from SMALLINT, -- 0-23, optional
    quiet_hours_to   SMALLINT, -- 0-23, optional
    CONSTRAINT notification_preferences_quiet_chk CHECK (
        (quiet_hours_from IS NULL OR (quiet_hours_from >= 0 AND quiet_hours_from <= 23)) AND
        (quiet_hours_to   IS NULL OR (quiet_hours_to   >= 0 AND quiet_hours_to   <= 23))
    )
);

-- Push subscriptions per device/user
CREATE TABLE push_subscriptions (
    push_subscription_id SERIAL PRIMARY KEY,
    user_id              INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    device_info          VARCHAR(200),
    token                TEXT NOT NULL,
    created_at           TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at           TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT push_subscriptions_token_unique UNIQUE (token)
);
CREATE INDEX push_subscriptions_user_idx ON push_subscriptions(user_id);

-- Event types dictionary
CREATE TABLE event_types (
    event_type_id SERIAL PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    CONSTRAINT event_types_name_unique UNIQUE (name)
);

-- Person categories dictionary
CREATE TABLE person_categories (
    person_category_id SERIAL PRIMARY KEY,
    name               VARCHAR(100) NOT NULL,
    CONSTRAINT person_categories_name_unique UNIQUE (name)
);

-- Persons (recognized identities)
CREATE TABLE persons (
    person_id      SERIAL PRIMARY KEY,
    last_name      VARCHAR(100),
    first_name     VARCHAR(100),
    middle_name    VARCHAR(100),
    embeddings     BYTEA,
    category_id    INTEGER REFERENCES person_categories(person_category_id) ON DELETE SET NULL,
    created_at     TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX persons_category_idx ON persons(category_id);

-- Recording files (video segments or snapshots) stored on disk
CREATE TABLE recording_files (
    recording_file_id SERIAL PRIMARY KEY,
    video_stream_id   INTEGER NOT NULL REFERENCES video_streams(video_stream_id) ON DELETE CASCADE,
    storage_target_id INTEGER NOT NULL REFERENCES storage_targets(storage_target_id) ON DELETE RESTRICT,
    file_kind         VARCHAR(20) NOT NULL, -- video, snapshot
    file_path         VARCHAR(1000) NOT NULL,
    started_at        TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    ended_at          TIMESTAMP WITHOUT TIME ZONE,
    duration_seconds  NUMERIC(12,2),
    file_size_bytes   NUMERIC(20,0),
    checksum          VARCHAR(100),
    created_at        TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT recording_files_kind_chk CHECK (file_kind IN ('video', 'snapshot')),
    CONSTRAINT recording_files_size_chk CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0),
    CONSTRAINT recording_files_unique_path UNIQUE (file_path)
);
CREATE INDEX recording_files_stream_idx ON recording_files(video_stream_id);
CREATE INDEX recording_files_started_idx ON recording_files(started_at);
CREATE INDEX recording_files_storage_idx ON recording_files(storage_target_id);

-- Events (detections)
CREATE TABLE events (
    event_id           SERIAL PRIMARY KEY,
    event_ts           TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    camera_id          INTEGER NOT NULL REFERENCES cameras(camera_id) ON DELETE RESTRICT,
    event_type_id      INTEGER NOT NULL REFERENCES event_types(event_type_id) ON DELETE RESTRICT,
    person_id          INTEGER REFERENCES persons(person_id) ON DELETE SET NULL,
    recording_file_id  INTEGER REFERENCES recording_files(recording_file_id) ON DELETE SET NULL,
    created_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    confidence         NUMERIC(5,2),
    CONSTRAINT events_confidence_chk CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 100))
);
CREATE INDEX events_camera_idx ON events(camera_id);
CREATE INDEX events_event_type_idx ON events(event_type_id);
CREATE INDEX events_person_idx ON events(person_id);
CREATE INDEX events_recording_idx ON events(recording_file_id);
CREATE INDEX events_ts_idx ON events(event_ts);

-- Notifications generated from events or system actions
CREATE TABLE notifications (
    notification_id    SERIAL PRIMARY KEY,
    event_id           INTEGER REFERENCES events(event_id) ON DELETE CASCADE,
    title              VARCHAR(200) NOT NULL,
    message            TEXT,
    severity           VARCHAR(20),
    created_at         TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    created_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    CONSTRAINT notifications_severity_chk CHECK (severity IN ('info', 'warning', 'critical'))
);
CREATE INDEX notifications_event_idx ON notifications(event_id);
CREATE INDEX notifications_created_at_idx ON notifications(created_at);

-- Delivery log per user/channel (push/email/sms)
CREATE TABLE notification_deliveries (
    notification_delivery_id SERIAL PRIMARY KEY,
    notification_id          INTEGER NOT NULL REFERENCES notifications(notification_id) ON DELETE CASCADE,
    user_id                  INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    channel                  VARCHAR(10) NOT NULL,
    status                   VARCHAR(20) NOT NULL DEFAULT 'pending',
    sent_at                  TIMESTAMP WITHOUT TIME ZONE,
    error_message            VARCHAR(255),
    CONSTRAINT notification_deliveries_channel_chk CHECK (channel IN ('push', 'email', 'sms')),
    CONSTRAINT notification_deliveries_status_chk CHECK (status IN ('pending', 'sent', 'failed'))
);
CREATE INDEX notification_deliveries_user_idx ON notification_deliveries(user_id);
CREATE INDEX notification_deliveries_notification_idx ON notification_deliveries(notification_id);
CREATE INDEX notification_deliveries_channel_idx ON notification_deliveries(channel);

-- Event review queue (unknown faces, manual review)
CREATE TABLE event_reviews (
    event_review_id   SERIAL PRIMARY KEY,
    event_id          INTEGER NOT NULL UNIQUE REFERENCES events(event_id) ON DELETE CASCADE,
    status            VARCHAR(20) NOT NULL DEFAULT 'pending',
    reviewer_user_id  INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    person_id         INTEGER REFERENCES persons(person_id) ON DELETE SET NULL,
    note              TEXT,
    created_at        TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT event_reviews_status_chk CHECK (status IN ('pending', 'approved', 'rejected'))
);
CREATE INDEX event_reviews_status_idx ON event_reviews(status);
CREATE INDEX event_reviews_reviewer_idx ON event_reviews(reviewer_user_id);

-- API keys for service access
CREATE TABLE api_keys (
    api_key_id   SERIAL PRIMARY KEY,
    key_hash     VARCHAR(255) NOT NULL UNIQUE,
    description  VARCHAR(255),
    scopes       TEXT, -- comma-separated scopes, e.g., detections:create
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at   TIMESTAMP WITHOUT TIME ZONE,
    created_at   TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- Authentication events log
CREATE TABLE auth_events (
    auth_event_id SERIAL PRIMARY KEY,
    user_id       INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    method        VARCHAR(30) NOT NULL, -- password, face, password+totp, face+totp
    success       BOOLEAN NOT NULL,
    reason        VARCHAR(255),
    source_ip     VARCHAR(45),
    user_agent    VARCHAR(255),
    occurred_at   TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX auth_events_user_idx ON auth_events(user_id);
CREATE INDEX auth_events_method_idx ON auth_events(method);
CREATE INDEX auth_events_ts_idx ON auth_events(occurred_at);

-- Audit log for data changes
CREATE TABLE audit_log (
    audit_id      SERIAL PRIMARY KEY,
    table_name    VARCHAR(100) NOT NULL,
    record_pk     VARCHAR(100) NOT NULL,
    action        VARCHAR(10) NOT NULL, -- INSERT, UPDATE, DELETE
    changed_at    TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    changed_by    INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    source_ip     VARCHAR(45),
    change_data   TEXT, -- serialized snapshot of changes (JSON text or key=value pairs)
    CONSTRAINT audit_log_action_chk CHECK (action IN ('INSERT', 'UPDATE', 'DELETE'))
);
CREATE INDEX audit_log_table_idx ON audit_log(table_name);
CREATE INDEX audit_log_changed_at_idx ON audit_log(changed_at);
CREATE INDEX audit_log_changed_by_idx ON audit_log(changed_by);

COMMIT;
