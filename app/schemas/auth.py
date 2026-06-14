from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(
        default=None,
        min_length=6,
        max_length=12,
        description="One-time code if TOTP enabled",
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False
    media_access_token: str | None = None
    media_token_expires_seconds: int | None = None


class MediaTokenResponse(BaseModel):
    media_access_token: str
    token_type: str = "bearer"
    media_token_expires_seconds: int


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=100)


class UserOut(BaseModel):
    user_id: int
    login: str
    role_id: int
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    must_change_password: bool = False
    totp_enabled: bool = False


class ProfileUpdateRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None


class TotpSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class TotpSetupRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)


class TotpCodeRequest(BaseModel):
    code: str
    current_password: str = Field(min_length=1, max_length=256)


class TotpDisableRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=6, max_length=12)


class TotpStatusResponse(BaseModel):
    enabled: bool
