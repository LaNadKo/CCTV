from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    login: str
    password: str
    totp_code: str | None = Field(default=None, description="One-time code if TOTP enabled")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UserOut(BaseModel):
    user_id: int
    login: str
    role_id: int
    face_login_enabled: bool
    must_change_password: bool = False

    class Config:
        from_attributes = True


class TotpSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class TotpCodeRequest(BaseModel):
    code: str


class TotpStatusResponse(BaseModel):
    enabled: bool
