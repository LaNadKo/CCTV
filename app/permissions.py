"""Simplified permission system — based on system roles only.

Roles:
  1 = admin   — full access
  2 = user    — can view/control cameras
  3 = viewer  — read-only access
"""
from typing import Optional

from app import models

# Role IDs
ROLE_ADMIN = 1
ROLE_USER = 2
ROLE_VIEWER = 3

# Permission levels
PERMISSION_LEVEL = {"view": 1, "control": 2, "admin": 3}

# Map system roles to camera permission level
ROLE_CAMERA_PERMISSION = {
    ROLE_ADMIN: "admin",
    ROLE_USER: "control",
    ROLE_VIEWER: "view",
}


def user_camera_permission_sync(user: models.User) -> Optional[str]:
    """Get camera permission level from system role."""
    return ROLE_CAMERA_PERMISSION.get(user.role_id)


async def user_camera_permission(session, user_id: int, camera_id: int) -> Optional[str]:
    """Backward-compatible async wrapper for legacy routers."""
    user = await session.get(models.User, user_id)
    if user is None:
        return None
    return user_camera_permission_sync(user)


def check_permission(actual: Optional[str], required: str) -> bool:
    if actual is None:
        return False
    return PERMISSION_LEVEL.get(actual, 0) >= PERMISSION_LEVEL.get(required, 0)


def is_admin(user: models.User) -> bool:
    return user.role_id == ROLE_ADMIN


def is_at_least_user(user: models.User) -> bool:
    return user.role_id in (ROLE_ADMIN, ROLE_USER)


async def is_home_admin(session, user_id: int) -> bool:
    """Backward-compatible helper for legacy routers."""
    user = await session.get(models.User, user_id)
    if user is None:
        return False
    return is_admin(user)
