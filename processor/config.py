"""Processor configuration."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    backend_url: str = Field(default="http://localhost:8000", validation_alias="BACKEND_URL")
    api_key: str = Field(default="", validation_alias="API_KEY")
    processor_name: str = Field(default="processor-1", validation_alias="PROCESSOR_NAME")
    poll_interval: int = Field(default=10, validation_alias="POLL_INTERVAL")
    heartbeat_interval: int = Field(default=30, validation_alias="HEARTBEAT_INTERVAL")
    max_workers: int = Field(default=4, validation_alias="MAX_WORKERS")
    motion_threshold: float = Field(default=25.0, validation_alias="MOTION_THRESHOLD")
    motion_min_area: int = Field(default=500, validation_alias="MOTION_MIN_AREA")
    face_scan_interval: int = Field(default=5, validation_alias="FACE_SCAN_INTERVAL")
    recording_segment_seconds: int = Field(default=300, validation_alias="RECORDING_SEGMENT_SECONDS")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
