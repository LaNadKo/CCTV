"""Simplified groups router — just logical camera groupings, no per-group roles."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.permissions import is_admin, is_at_least_user
from app.schemas.groups import GroupCameraOut, GroupCreate, GroupDetail, GroupOut, GroupUpdate

router = APIRouter(prefix="/groups", tags=["groups"])


def _ensure_admin(user: models.User):
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> GroupOut:
    _ensure_admin(current_user)
    existing = await session.execute(select(models.Group).where(models.Group.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Group name already exists")

    group = models.Group(name=payload.name, description=payload.description)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return GroupOut(
        group_id=group.group_id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        camera_count=0,
    )


@router.get("", response_model=List[GroupOut])
async def list_groups(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> List[GroupOut]:
    result = await session.execute(select(models.Group).order_by(models.Group.group_id))
    groups = result.scalars().all()
    out = []
    for g in groups:
        count = await session.execute(
            select(func.count()).where(
                models.Camera.group_id == g.group_id,
                models.Camera.deleted_at.is_(None),
            )
        )
        out.append(GroupOut(
            group_id=g.group_id,
            name=g.name,
            description=g.description,
            created_at=g.created_at,
            camera_count=count.scalar() or 0,
        ))
    return out


@router.get("/{group_id}", response_model=GroupDetail)
async def get_group(
    group_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> GroupDetail:
    group = await session.get(models.Group, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    cams_result = await session.execute(
        select(models.Camera).where(
            models.Camera.group_id == group_id,
            models.Camera.deleted_at.is_(None),
        )
    )
    cameras = [
        GroupCameraOut(camera_id=c.camera_id, name=c.name, location=c.location)
        for c in cams_result.scalars().all()
    ]
    return GroupDetail(
        group_id=group.group_id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        camera_count=len(cameras),
        cameras=cameras,
    )


@router.patch("/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: int,
    payload: GroupUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> GroupOut:
    _ensure_admin(current_user)
    group = await session.get(models.Group, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await session.commit()
    await session.refresh(group)
    count = await session.execute(
        select(func.count()).where(
            models.Camera.group_id == group.group_id,
            models.Camera.deleted_at.is_(None),
        )
    )
    return GroupOut(
        group_id=group.group_id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
        camera_count=count.scalar() or 0,
    )


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    group = await session.get(models.Group, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    # Unassign cameras from this group
    cams_result = await session.execute(
        select(models.Camera).where(
            models.Camera.group_id == group_id,
            models.Camera.deleted_at.is_(None),
        )
    )
    for cam in cams_result.scalars().all():
        cam.group_id = None
    await session.delete(group)
    await session.commit()
    return {}


@router.post("/{group_id}/cameras/{camera_id}", status_code=status.HTTP_200_OK)
async def assign_camera_to_group(
    group_id: int,
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    group = await session.get(models.Group, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    cam = await session.get(models.Camera, camera_id)
    if cam is None or cam.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    cam.group_id = group_id
    await session.commit()
    return {"ok": True}


@router.delete("/{group_id}/cameras/{camera_id}", status_code=status.HTTP_200_OK)
async def unassign_camera_from_group(
    group_id: int,
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    cam = await session.get(models.Camera, camera_id)
    if cam is None or cam.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    if cam.group_id == group_id:
        cam.group_id = None
        await session.commit()
    return {"ok": True}
