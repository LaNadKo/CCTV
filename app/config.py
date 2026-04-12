from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CCTV API"
    debug: bool = False

    # Database
    db_url: str = Field(
        default="postgresql+asyncpg://postgres:0512@localhost:5432/cctv",
        validation_alias="DATABASE_URL",
    )

    # Security
    jwt_secret: str = Field(default="change-me", validation_alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24
    totp_encryption_key: str | None = Field(
        default=None,
        validation_alias="TOTP_ENCRYPTION_KEY",
        description="Base64 URL-safe 32-byte key for Fernet encryption of TOTP secrets",
    )

    # Phase 1: embedded detector toggle
    enable_embedded_detector: bool = Field(
        default=False,
        validation_alias="ENABLE_EMBEDDED_DETECTOR",
    )

    # Processor shared secret (auto-seeded into api_keys on startup)
    processor_api_key: str = Field(
        default="processor-secret-key-2026",
        validation_alias="PROCESSOR_API_KEY",
    )
    rf_room_layout_path: str = Field(
        default="config/rf_room_layout.json",
        validation_alias="RF_ROOM_LAYOUT_PATH",
    )
    rf_history_path: str = Field(
        default="data/rf_samples.jsonl",
        validation_alias="RF_HISTORY_PATH",
    )
    ruview_bridge_enabled: bool = Field(
        default=True,
        validation_alias="RUVIEW_BRIDGE_ENABLED",
    )
    ruview_udp_bind: str = Field(
        default="0.0.0.0",
        validation_alias="RUVIEW_UDP_BIND",
    )
    ruview_udp_port: int = Field(
        default=5005,
        validation_alias="RUVIEW_UDP_PORT",
    )
    ruview_stale_after_seconds: float = Field(
        default=10.0,
        validation_alias="RUVIEW_STALE_AFTER_SECONDS",
    )
    ruview_calibration_path: str = Field(
        default="data/ruview_calibration_samples.jsonl",
        validation_alias="RUVIEW_CALIBRATION_PATH",
    )
    camera_room_calibration_path: str = Field(
        default="data/camera_room_calibrations.json",
        validation_alias="CAMERA_ROOM_CALIBRATION_PATH",
    )
    camera_supervision_enabled: bool = Field(
        default=True,
        validation_alias="CAMERA_SUPERVISION_ENABLED",
    )
    camera_supervision_min_interval_seconds: float = Field(
        default=1.0,
        validation_alias="CAMERA_SUPERVISION_MIN_INTERVAL_SECONDS",
    )
    camera_supervision_min_confidence: float = Field(
        default=0.0,
        validation_alias="CAMERA_SUPERVISION_MIN_CONFIDENCE",
    )
    camera_supervision_require_manual_calibration: bool = Field(
        default=True,
        validation_alias="CAMERA_SUPERVISION_REQUIRE_MANUAL_CALIBRATION",
    )
    ruview_stimulator_enabled: bool = Field(
        default=True,
        validation_alias="RUVIEW_STIMULATOR_ENABLED",
    )
    ruview_stimulator_interval_seconds: float = Field(
        default=0.25,
        validation_alias="RUVIEW_STIMULATOR_INTERVAL_SECONDS",
    )
    ruview_stimulator_timeout_seconds: float = Field(
        default=0.35,
        validation_alias="RUVIEW_STIMULATOR_TIMEOUT_SECONDS",
    )
    active_tracking_camera_fresh_seconds: float = Field(
        default=5.0,
        validation_alias="ACTIVE_TRACKING_CAMERA_FRESH_SECONDS",
    )
    active_tracking_camera_merge_seconds: float = Field(
        default=2.5,
        validation_alias="ACTIVE_TRACKING_CAMERA_MERGE_SECONDS",
    )
    active_tracking_camera_merge_radius_cm: float = Field(
        default=130.0,
        validation_alias="ACTIVE_TRACKING_CAMERA_MERGE_RADIUS_CM",
    )
    active_tracking_camera_merge_min_score: float = Field(
        default=0.18,
        validation_alias="ACTIVE_TRACKING_CAMERA_MERGE_MIN_SCORE",
    )
    active_tracking_rf_min_confidence: float = Field(
        default=0.55,
        validation_alias="ACTIVE_TRACKING_RF_MIN_CONFIDENCE",
    )
    active_tracking_rf_assignment_radius_cm: float = Field(
        default=180.0,
        validation_alias="ACTIVE_TRACKING_RF_ASSIGNMENT_RADIUS_CM",
    )
    active_tracking_room_hold_seconds: float = Field(
        default=45.0,
        validation_alias="ACTIVE_TRACKING_ROOM_HOLD_SECONDS",
    )
    active_tracking_expire_seconds: float = Field(
        default=75.0,
        validation_alias="ACTIVE_TRACKING_EXPIRE_SECONDS",
    )

    @field_validator("debug", mode="before")
    @classmethod
    def _parse_debug(cls, value):
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"release", "prod", "production", "0", "false", "no", "off"}:
                return False
            if lowered in {"debug", "dev", "development", "1", "true", "yes", "on"}:
                return True
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
