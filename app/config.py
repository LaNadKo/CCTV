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
