from typing import List, Optional

from pydantic import BaseModel, Field


class GroupCameraPermissionIn(BaseModel):
    camera_id: int
    permission: str = Field(pattern="^(view|control|admin)$")
    target_role: str = Field(default="member", pattern="^(admin|member)$")


class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    camera_permissions: List[GroupCameraPermissionIn] = []
    user_ids: List[int] = []


class GroupOut(BaseModel):
    group_id: int
    name: str
    description: Optional[str] = None
    membership_role: Optional[str] = None

    class Config:
        from_attributes = True


class GroupCameraPermissionOut(BaseModel):
    camera_id: int
    permission: str
    target_role: str


class GroupDetail(GroupOut):
    cameras: List[GroupCameraPermissionOut] = []
    membership_role: Optional[str] = None


class GroupInvite(BaseModel):
    login: str
    password: Optional[str] = None  # если пользователя нет — создать с этим паролем


class GroupRoleUpdate(BaseModel):
    role: str = Field(pattern="^(admin|member)$")


class GroupTransferOwner(BaseModel):
    new_owner_user_id: Optional[int] = None
    login: Optional[str] = None
