from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CCTV API"
    debug: bool = False
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")

    # Database
    db_url: str = Field(
        default="postgresql+asyncpg://postgres:0512@localhost:5432/cctv",
        validation_alias="DATABASE_URL",
    )

    # Security
    jwt_secret: str = Field(default="", validation_alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24
    media_token_expires_seconds: int = Field(default=900, validation_alias="MEDIA_TOKEN_EXPIRES_SECONDS")
    totp_encryption_key: str | None = Field(
        default=None,
        validation_alias="TOTP_ENCRYPTION_KEY",
        description="Base64 URL-safe 32-byte key for Fernet encryption of application secrets",
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        validation_alias="CORS_ORIGINS",
    )
    allowed_hosts: list[str] = Field(default_factory=lambda: ["*"], validation_alias="ALLOWED_HOSTS")
    enable_docs: bool | None = Field(default=None, validation_alias="ENABLE_DOCS")
    bootstrap_admin_login: str = Field(default="admin", validation_alias="BOOTSTRAP_ADMIN_LOGIN")
    bootstrap_admin_password: str | None = Field(default=None, validation_alias="BOOTSTRAP_ADMIN_PASSWORD")
    allow_default_admin: bool = Field(default=True, validation_alias="ALLOW_DEFAULT_ADMIN")
    allow_legacy_query_tokens: bool = Field(default=False, validation_alias="ALLOW_LEGACY_QUERY_TOKENS")
    auth_rate_limit_attempts: int = Field(default=8, validation_alias="AUTH_RATE_LIMIT_ATTEMPTS")
    auth_rate_limit_window_seconds: int = Field(default=60, validation_alias="AUTH_RATE_LIMIT_WINDOW_SECONDS")

    # Phase 1: embedded detector toggle
    enable_embedded_detector: bool = Field(
        default=False,
        validation_alias="ENABLE_EMBEDDED_DETECTOR",
    )

    # Processor shared secret (auto-seeded into api_keys on startup)
    processor_api_key: str = Field(
        default="",
        validation_alias="PROCESSOR_API_KEY",
    )

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"prod", "production", "release"}

    @property
    def docs_enabled(self) -> bool:
        if self.enable_docs is not None:
            return self.enable_docs
        return not self.is_production

    @field_validator("environment", mode="before")
    @classmethod
    def _normalize_environment(cls, value):
        if value is None:
            return "development"
        return str(value).strip().lower()

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

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _parse_csv_list(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def security_startup_errors(self) -> list[str]:
        if not self.is_production:
            return []

        errors: list[str] = []
        weak_jwt_values = {"change-me", "changeme", "changeme-generate-with-openssl-rand-hex-32"}
        if self.jwt_secret.strip().lower() in weak_jwt_values or len(self.jwt_secret.strip()) < 32:
            errors.append("JWT_SECRET must be a non-default secret with at least 32 characters")
        weak_processor_values = {"processor-secret-key-2026", "changeme", "changeme-generate-with-openssl-rand-hex-24"}
        if self.processor_api_key.strip().lower() in weak_processor_values or len(self.processor_api_key.strip()) < 24:
            errors.append("PROCESSOR_API_KEY must be a non-default secret with at least 24 characters")
        if not self.totp_encryption_key:
            errors.append("TOTP_ENCRYPTION_KEY must be set to encrypt TOTP and camera secrets at rest")
        else:
            try:
                from cryptography.fernet import Fernet

                Fernet(self.totp_encryption_key.encode())
            except Exception:
                errors.append("TOTP_ENCRYPTION_KEY must be a valid Fernet key")
        if "*" in self.cors_origins:
            errors.append("CORS_ORIGINS must not contain '*' in production")
        if "*" in self.allowed_hosts:
            errors.append("ALLOWED_HOSTS must not contain '*' in production")
        if self.allow_legacy_query_tokens:
            errors.append("ALLOW_LEGACY_QUERY_TOKENS must be false in production")
        if self.allow_default_admin and not self.bootstrap_admin_password:
            errors.append("BOOTSTRAP_ADMIN_PASSWORD is required when ALLOW_DEFAULT_ADMIN=true in production")
        return errors

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
