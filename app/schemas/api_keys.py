from typing import Optional, List

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    description: Optional[str] = None
    scopes: List[str] = Field(default_factory=lambda: ["detections:create"])
    expires_at: Optional[str] = None  # ISO string


class ApiKeyOut(BaseModel):
    api_key_id: int
    description: Optional[str] = None
    scopes: List[str]
    is_active: bool
    expires_at: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class ApiKeyPlain(BaseModel):
    api_key: str
    api_key_id: int


class ApiKeyUpdate(BaseModel):
    description: Optional[str] = None
    scopes: Optional[List[str]] = None
    is_active: Optional[bool] = None
    expires_at: Optional[str] = None
