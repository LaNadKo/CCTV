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
    poll_interval: int = Field(default=3, validation_alias="POLL_INTERVAL")
    heartbeat_interval: int = Field(default=30, validation_alias="HEARTBEAT_INTERVAL")
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
    unknown_face_requires_motion_seconds: float = Field(default=2.0, validation_alias="UNKNOWN_FACE_REQUIRES_MOTION_SECONDS")
    recording_segment_seconds: int = Field(default=60, validation_alias="RECORDING_SEGMENT_SECONDS")
    media_port: int = Field(default=8777, validation_alias="MEDIA_PORT")
    media_token: str = Field(default_factory=lambda: secrets.token_urlsafe(24), validation_alias="MEDIA_TOKEN")

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
