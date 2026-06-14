"""Processor configuration."""
import secrets

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    backend_url: str = Field(default="http://localhost:8000", validation_alias="BACKEND_URL")
    api_key: str = Field(default="", validation_alias="API_KEY")
    processor_id: int | None = Field(default=None, validation_alias="PROCESSOR_ID")
    processor_name: str = Field(default="processor-1", validation_alias="PROCESSOR_NAME")
    processor_node_uid: str | None = Field(default=None, validation_alias="PROCESSOR_NODE_UID")
    advertised_ip: str | None = Field(default=None, validation_alias="PROCESSOR_ADVERTISED_IP")
    poll_interval: int = Field(default=1, validation_alias="POLL_INTERVAL")
    heartbeat_interval: int = Field(default=10, validation_alias="HEARTBEAT_INTERVAL")
    max_workers: int = Field(default=4, validation_alias="MAX_WORKERS")
    processor_accel: str = Field(default="auto", validation_alias="PROCESSOR_ACCEL")
    motion_threshold: float = Field(default=25.0, validation_alias="MOTION_THRESHOLD")
    motion_min_area: int = Field(default=500, validation_alias="MOTION_MIN_AREA")
    face_scan_divisor: int | None = Field(default=None, validation_alias="FACE_SCAN_DIVISOR")
    overlay_frame_divisor: int = Field(default=1, validation_alias="OVERLAY_FRAME_DIVISOR")
    face_scan_interval: float = Field(default=0.35, validation_alias="FACE_SCAN_INTERVAL")
    face_match_threshold: float = Field(default=0.56, validation_alias="FACE_MATCH_THRESHOLD")
    face_match_margin: float = Field(default=0.1, validation_alias="FACE_MATCH_MARGIN")
    antispoof_small_face_ratio: float = Field(default=0.045, validation_alias="ANTISPOOF_SMALL_FACE_RATIO")
    antispoof_min_texture_score: float = Field(default=0.00012, validation_alias="ANTISPOOF_MIN_TEXTURE_SCORE")
    antispoof_face_motion_threshold: float = Field(default=7.0, validation_alias="ANTISPOOF_FACE_MOTION_THRESHOLD")
    antispoof_context_motion_threshold: float = Field(default=4.2, validation_alias="ANTISPOOF_CONTEXT_MOTION_THRESHOLD")
    antispoof_active_ratio: float = Field(default=0.03, validation_alias="ANTISPOOF_ACTIVE_RATIO")
    antispoof_model_enabled: bool = Field(default=True, validation_alias="ANTISPOOF_MODEL_ENABLED")
    antispoof_model_path: str | None = Field(default=None, validation_alias="ANTISPOOF_MODEL_PATH")
    antispoof_model_real_threshold: float = Field(default=0.72, validation_alias="ANTISPOOF_MODEL_REAL_THRESHOLD")
    antispoof_model_fake_threshold: float = Field(default=0.72, validation_alias="ANTISPOOF_MODEL_FAKE_THRESHOLD")
    antispoof_pending_timeout_seconds: float = Field(default=2.8, validation_alias="ANTISPOOF_PENDING_TIMEOUT_SECONDS")
    unknown_face_requires_motion_seconds: float = Field(default=2.0, validation_alias="UNKNOWN_FACE_REQUIRES_MOTION_SECONDS")
    recording_segment_seconds: int = Field(default=60, validation_alias="RECORDING_SEGMENT_SECONDS")
    recording_upload_concurrency: int = Field(default=2, validation_alias="RECORDING_UPLOAD_CONCURRENCY")
    recording_upload_queue_size: int = Field(default=128, validation_alias="RECORDING_UPLOAD_QUEUE_SIZE")
    recording_retention_days: int = Field(default=0, validation_alias="RECORDING_RETENTION_DAYS")
    recording_retention_max_bytes: int = Field(default=0, validation_alias="RECORDING_RETENTION_MAX_BYTES")
    recording_min_free_bytes: int = Field(default=536_870_912, validation_alias="RECORDING_MIN_FREE_BYTES")
    max_capture_pixels: int = Field(default=8_294_400, validation_alias="MAX_CAPTURE_PIXELS")
    media_bind: str = Field(default="0.0.0.0", validation_alias="MEDIA_BIND")
    media_port: int = Field(default=8777, validation_alias="MEDIA_PORT")
    media_token: str = Field(default_factory=lambda: secrets.token_urlsafe(24), validation_alias="MEDIA_TOKEN")
    media_max_connections: int = Field(default=64, validation_alias="MEDIA_MAX_CONNECTIONS")
    media_socket_timeout_seconds: float = Field(default=15.0, validation_alias="MEDIA_SOCKET_TIMEOUT_SECONDS")

    @field_validator("processor_id", mode="before")
    @classmethod
    def _empty_processor_id_is_none(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("recording_segment_seconds", mode="before")
    @classmethod
    def _recording_segment_is_minute_max(cls, value):
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            seconds = 60
        return min(60, max(10, seconds))

    @field_validator("recording_upload_concurrency", mode="before")
    @classmethod
    def _recording_upload_concurrency_bounds(cls, value):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 2
        return min(8, max(1, parsed))

    @field_validator("recording_upload_queue_size", mode="before")
    @classmethod
    def _recording_upload_queue_size_bounds(cls, value):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 128
        return min(512, max(8, parsed))

    @field_validator("recording_retention_days", mode="before")
    @classmethod
    def _recording_retention_days_bounds(cls, value):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 0
        return min(3650, max(0, parsed))

    @field_validator("recording_retention_max_bytes", mode="before")
    @classmethod
    def _recording_retention_max_bytes_bounds(cls, value):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 0
        return max(0, parsed)

    @field_validator("recording_min_free_bytes", mode="before")
    @classmethod
    def _recording_min_free_bytes_bounds(cls, value):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 536_870_912
        return min(100 * 1024**3, max(64 * 1024**2, parsed))

    @field_validator("max_capture_pixels", mode="before")
    @classmethod
    def _max_capture_pixels_bounds(cls, value):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 8_294_400
        return min(33_177_600, max(307_200, parsed))

    @field_validator("media_token", mode="before")
    @classmethod
    def _empty_media_token_generates_secret(cls, value):
        if value is None:
            return secrets.token_urlsafe(24)
        if isinstance(value, str) and not value.strip():
            return secrets.token_urlsafe(24)
        return value

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
