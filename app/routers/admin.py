from typing import List, Optional
import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.permissions import check_permission, is_home_admin, user_camera_permission
from app.schemas.camera_admin import (
    CameraCreate,
    CameraUpdate,
    EventCreate,
    PersonCreate,
    PersonUpdate,
    RecordingFileCreate,
    VideoStreamCreate,
    VideoStreamUpdate,
)
from app.security import hash_password


# ── Preset / ROI schemas ──

class PresetCreate(BaseModel):
    name: str
    preset_token: Optional[str] = None
    order_index: int = 0
    dwell_seconds: int = 10

class PresetOut(BaseModel):
    camera_preset_id: int
    camera_id: int
    name: str
    preset_token: Optional[str] = None
    order_index: int
    dwell_seconds: int
    class Config:
        from_attributes = True

class RoiZoneCreate(BaseModel):
    name: str
    zone_type: str = "include"
    polygon_points: Optional[str] = None

class RoiZoneOut(BaseModel):
    roi_zone_id: int
    camera_id: int
    name: str
    zone_type: str
    polygon_points: Optional[str] = None
    class Config:
        from_attributes = True

router = APIRouter(prefix="/admin", tags=["admin"])


async def _ensure_admin(user: models.User, session: AsyncSession) -> None:
    if user.role_id == 1:
        return
    if await is_home_admin(session, user.user_id):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


async def _ensure_camera_admin(
    session: AsyncSession, user: models.User, camera_id: int
) -> None:
    if user.role_id == 1:
        return
    perm = await user_camera_permission(session, user.user_id, camera_id)
    if not check_permission(perm, "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not camera admin")


@router.post("/cameras", status_code=status.HTTP_201_CREATED)
async def create_camera(
    payload: CameraCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    cam = models.Camera(
        name=payload.name,
        ip_address=payload.ip_address,
        stream_url=payload.stream_url,
        status_id=payload.status_id,
        location=payload.location,
        detection_enabled=payload.detection_enabled,
        recording_mode=payload.recording_mode,
    )
    session.add(cam)
    await session.flush()
    # give creator admin permission on this camera
    session.add(
        models.UserCameraPermission(
            user_id=current_user.user_id,
            camera_id=cam.camera_id,
            permission="admin",
        )
    )
    await session.commit()
    await session.refresh(cam)
    return {"camera_id": cam.camera_id}


@router.patch("/cameras/{camera_id}")
async def update_camera(
    camera_id: int,
    payload: CameraUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    cam = await session.get(models.Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    await _ensure_camera_admin(session, current_user, camera_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(cam, field, value)
    await session.commit()
    return {"camera_id": cam.camera_id}


@router.delete("/cameras/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    cam = await session.get(models.Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    await _ensure_camera_admin(session, current_user, camera_id)
    await session.delete(cam)
    await session.commit()
    return {}


@router.post("/cameras/{camera_id}/streams", status_code=status.HTTP_201_CREATED)
async def add_stream(
    camera_id: int,
    payload: VideoStreamCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    cam = await session.get(models.Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    await _ensure_camera_admin(session, current_user, camera_id)
    vs = models.VideoStream(
        camera_id=camera_id,
        resolution=payload.resolution,
        fps=payload.fps,
        enabled=payload.enabled,
        stream_url=payload.stream_url,
    )
    session.add(vs)
    await session.commit()
    await session.refresh(vs)
    return {"video_stream_id": vs.video_stream_id}


@router.patch("/streams/{stream_id}")
async def update_stream(
    stream_id: int,
    payload: VideoStreamUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    vs = await session.get(models.VideoStream, stream_id)
    if vs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stream not found")
    await _ensure_camera_admin(session, current_user, vs.camera_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(vs, field, value)
    await session.commit()
    return {"video_stream_id": vs.video_stream_id}


@router.get("/persons")
async def list_persons(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    result = await session.execute(select(models.Person).order_by(models.Person.person_id))
    persons = result.scalars().all()
    return [
        {
            "person_id": p.person_id,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "middle_name": p.middle_name,
            "category_id": p.category_id,
            "has_embedding": p.embeddings is not None,
            "created_at": str(p.created_at) if p.created_at else None,
        }
        for p in persons
    ]


@router.post("/persons", status_code=status.HTTP_201_CREATED)
async def create_person(
    payload: PersonCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    person = models.Person(
        first_name=payload.first_name,
        last_name=payload.last_name,
        middle_name=payload.middle_name,
        category_id=payload.category_id,
        embeddings=payload.embeddings,
    )
    session.add(person)
    await session.commit()
    await session.refresh(person)
    return {"person_id": person.person_id}


@router.patch("/persons/{person_id}")
async def update_person(
    person_id: int,
    payload: PersonUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    person = await session.get(models.Person, person_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(person, field, value)
    await session.commit()
    return {"person_id": person.person_id}


@router.delete("/persons/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(
    person_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    person = await session.get(models.Person, person_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    await session.delete(person)
    await session.commit()
    return {}


@router.post("/events", status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    evt = models.Event(
        camera_id=payload.camera_id,
        event_type_id=payload.event_type_id,
        person_id=payload.person_id,
        recording_file_id=payload.recording_file_id,
        confidence=payload.confidence,
        created_by_user_id=current_user.user_id,
    )
    session.add(evt)
    await session.commit()
    await session.refresh(evt)
    return {"event_id": evt.event_id}


@router.get("/events", response_model=List[dict])
async def list_events(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    res = await session.execute(select(models.Event))
    events = res.scalars().all()
    return [
        {
            "event_id": e.event_id,
            "camera_id": e.camera_id,
            "event_type_id": e.event_type_id,
            "person_id": e.person_id,
            "recording_file_id": e.recording_file_id,
            "confidence": float(e.confidence) if e.confidence is not None else None,
            "event_ts": e.event_ts,
        }
        for e in events
    ]


@router.post("/recordings", status_code=status.HTTP_201_CREATED)
async def create_recording(
    payload: RecordingFileCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    rf = models.RecordingFile(
        video_stream_id=payload.video_stream_id,
        storage_target_id=payload.storage_target_id,
        file_kind=payload.file_kind,
        file_path=payload.file_path,
        duration_seconds=payload.duration_seconds,
        file_size_bytes=payload.file_size_bytes,
        checksum=payload.checksum,
    )
    session.add(rf)
    await session.commit()
    await session.refresh(rf)
    return {"recording_file_id": rf.recording_file_id}


@router.post("/users/{user_id}/role")
async def set_user_role(
    user_id: int,
    role_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    user = await session.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.role_id = role_id
    await session.commit()
    return {"user_id": user.user_id, "role_id": user.role_id}


# ── Presets (Phase 2) ──

@router.get("/cameras/{camera_id}/presets", response_model=List[PresetOut])
async def list_presets(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_camera_admin(session, current_user, camera_id)
    result = await session.execute(
        select(models.CameraPreset)
        .where(models.CameraPreset.camera_id == camera_id)
        .order_by(models.CameraPreset.order_index)
    )
    return result.scalars().all()


@router.post("/cameras/{camera_id}/presets", status_code=status.HTTP_201_CREATED, response_model=PresetOut)
async def create_preset(
    camera_id: int,
    payload: PresetCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    cam = await session.get(models.Camera, camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    await _ensure_camera_admin(session, current_user, camera_id)
    preset = models.CameraPreset(
        camera_id=camera_id,
        name=payload.name,
        preset_token=payload.preset_token,
        order_index=payload.order_index,
        dwell_seconds=payload.dwell_seconds,
    )
    session.add(preset)
    await session.commit()
    await session.refresh(preset)
    return preset


@router.delete("/cameras/{camera_id}/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(
    camera_id: int,
    preset_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_camera_admin(session, current_user, camera_id)
    preset = await session.get(models.CameraPreset, preset_id)
    if not preset or preset.camera_id != camera_id:
        raise HTTPException(status_code=404, detail="Preset not found")
    await session.delete(preset)
    await session.commit()
    return {}


# ── ROI Zones (Phase 3) ──

@router.get("/cameras/{camera_id}/roi-zones", response_model=List[RoiZoneOut])
async def list_roi_zones(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_camera_admin(session, current_user, camera_id)
    result = await session.execute(
        select(models.CameraRoiZone).where(models.CameraRoiZone.camera_id == camera_id)
    )
    return result.scalars().all()


@router.post("/cameras/{camera_id}/roi-zones", status_code=status.HTTP_201_CREATED, response_model=RoiZoneOut)
async def create_roi_zone(
    camera_id: int,
    payload: RoiZoneCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    cam = await session.get(models.Camera, camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    await _ensure_camera_admin(session, current_user, camera_id)
    zone = models.CameraRoiZone(
        camera_id=camera_id,
        name=payload.name,
        zone_type=payload.zone_type,
        polygon_points=payload.polygon_points,
    )
    session.add(zone)
    await session.commit()
    await session.refresh(zone)
    return zone


@router.delete("/cameras/{camera_id}/roi-zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_roi_zone(
    camera_id: int,
    zone_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_camera_admin(session, current_user, camera_id)
    zone = await session.get(models.CameraRoiZone, zone_id)
    if not zone or zone.camera_id != camera_id:
        raise HTTPException(status_code=404, detail="ROI zone not found")
    await session.delete(zone)
    await session.commit()
    return {}


# ── Storage Targets CRUD (Phase 4) ──


class StorageTargetCreate(BaseModel):
    name: str
    root_path: str = "./recordings"
    total_gb: Optional[float] = None
    reserved_gb: Optional[float] = None
    retention_days: Optional[int] = None
    device_kind: str = "ssd"
    purpose: str = "recording"
    is_primary_recording: bool = False
    storage_type: str = "local"
    connection_config: Optional[str] = None


class StorageTargetUpdate(BaseModel):
    name: Optional[str] = None
    root_path: Optional[str] = None
    total_gb: Optional[float] = None
    reserved_gb: Optional[float] = None
    retention_days: Optional[int] = None
    device_kind: Optional[str] = None
    purpose: Optional[str] = None
    is_primary_recording: Optional[bool] = None
    storage_type: Optional[str] = None
    connection_config: Optional[str] = None


class StorageTargetOut(BaseModel):
    storage_target_id: int
    name: str
    root_path: str
    total_gb: Optional[float] = None
    reserved_gb: Optional[float] = None
    retention_days: Optional[int] = None
    device_kind: str
    purpose: str
    is_primary_recording: bool
    is_active: bool = True
    storage_type: str
    connection_config: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/storage-targets", response_model=List[StorageTargetOut])
async def list_storage_targets(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    result = await session.execute(select(models.StorageTarget))
    return result.scalars().all()


@router.post("/storage-targets", status_code=status.HTTP_201_CREATED, response_model=StorageTargetOut)
async def create_storage_target(
    payload: StorageTargetCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    st = models.StorageTarget(
        name=payload.name,
        root_path=payload.root_path,
        total_gb=payload.total_gb,
        reserved_gb=payload.reserved_gb,
        retention_days=payload.retention_days,
        device_kind=payload.device_kind,
        purpose=payload.purpose,
        is_primary_recording=payload.is_primary_recording,
        storage_type=payload.storage_type,
        connection_config=payload.connection_config,
    )
    session.add(st)
    await session.commit()
    await session.refresh(st)
    return st


@router.patch("/storage-targets/{target_id}", response_model=StorageTargetOut)
async def update_storage_target(
    target_id: int,
    payload: StorageTargetUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    target = await session.get(models.StorageTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Storage target not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(target, field, value)
    await session.commit()
    await session.refresh(target)
    return target


@router.delete("/storage-targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_storage_target(
    target_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    target = await session.get(models.StorageTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Storage target not found")
    await session.delete(target)
    await session.commit()
    return {}


@router.post("/storage-targets/{target_id}/test")
async def test_storage_target(
    target_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    await _ensure_admin(current_user, session)
    target = await session.get(models.StorageTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Storage target not found")

    from app.storage import create_backend
    try:
        backend = create_backend(target)
        healthy = await backend.health_check()
        return {"ok": healthy, "storage_type": target.storage_type}
    except Exception as e:
        return {"ok": False, "storage_type": target.storage_type, "error": str(e)}
