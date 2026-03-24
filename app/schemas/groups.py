from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel


class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class GroupOut(BaseModel):
    group_id: int
    name: str
    description: Optional[str] = None
    created_at: datetime
    camera_count: int = 0

    class Config:
        from_attributes = True


class GroupCameraOut(BaseModel):
    camera_id: int
    name: str
    location: Optional[str] = None


class GroupDetail(GroupOut):
    cameras: List[GroupCameraOut] = []
