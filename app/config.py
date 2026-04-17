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

    # RuView / WiFi DensePose integration. This is deliberately kept separate
    # from room-coordinate RF mapping: RuView feeds pose/skeleton data only.
    ruview_bridge_enabled: bool = Field(
        default=True,
        validation_alias="RUVIEW_BRIDGE_ENABLED",
    )
    ruview_udp_bind: str = Field(default="0.0.0.0", validation_alias="RUVIEW_UDP_BIND")
    ruview_udp_port: int = Field(default=5005, validation_alias="RUVIEW_UDP_PORT")
    ruview_stale_after_seconds: float = Field(
        default=10.0,
        validation_alias="RUVIEW_STALE_AFTER_SECONDS",
    )
    ruview_require_live_csi_for_pose: bool = Field(
        default=True,
        validation_alias="RUVIEW_REQUIRE_LIVE_CSI_FOR_POSE",
    )
    ruview_node_ips: str = Field(default="", validation_alias="RUVIEW_NODE_IPS")
    ruview_upstream_enabled: bool = Field(
        default=True,
        validation_alias="RUVIEW_UPSTREAM_ENABLED",
    )
    ruview_upstream_urls: str = Field(
        default="http://ruview-sensing:3000,http://host.docker.internal:3100,http://127.0.0.1:3100",
        validation_alias="RUVIEW_UPSTREAM_URLS",
    )
    ruview_upstream_timeout_seconds: float = Field(
        default=1.0,
        validation_alias="RUVIEW_UPSTREAM_TIMEOUT_SECONDS",
    )
    ruview_upstream_forward_enabled: bool = Field(
        default=True,
        validation_alias="RUVIEW_UPSTREAM_FORWARD_ENABLED",
    )
    ruview_upstream_udp_host: str = Field(
        default="ruview-sensing",
        validation_alias="RUVIEW_UPSTREAM_UDP_HOST",
    )
    ruview_upstream_udp_port: int = Field(
        default=5005,
        validation_alias="RUVIEW_UPSTREAM_UDP_PORT",
    )
    ruview_upstream_forward_min_interval_seconds: float = Field(
        default=0.0,
        validation_alias="RUVIEW_UPSTREAM_FORWARD_MIN_INTERVAL_SECONDS",
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
