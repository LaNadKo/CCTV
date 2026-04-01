from pydantic import BaseModel, Field


class UserRegister(BaseModel):
    """Used by admin to create users."""

    login: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=6, max_length=100)
    role_id: int = 3  # default: viewer
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None


class UserOut(BaseModel):
    user_id: int
    login: str
    role_id: int
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    face_login_enabled: bool
    must_change_password: bool = False

    class Config:
        from_attributes = True


class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=100)
