from typing import List, Optional

from pydantic import BaseModel, Field


class FaceEmbedding(BaseModel):
    embedding: List[float] = Field(min_length=8)
    model: Optional[str] = "insightface"
    distance_metric: Optional[str] = "cosine"
    threshold: Optional[float] = None
    quality_score: Optional[float] = None


class FaceEnrollResponse(BaseModel):
    templates_count: int
    face_login_enabled: bool


class FaceLoginRequest(BaseModel):
    embedding: List[float] = Field(min_length=8)
    totp_code: Optional[str] = None


class FaceLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
