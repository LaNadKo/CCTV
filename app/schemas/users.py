from typing import Optional

from pydantic import BaseModel, Field


class UserRegister(BaseModel):
    login: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=6, max_length=100)
    role_id: Optional[int] = None


class UserOut(BaseModel):
    user_id: int
    login: str
    role_id: int
    face_login_enabled: bool

    class Config:
        from_attributes = True
