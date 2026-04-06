from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.permissions import is_admin
from app.schemas.camera_admin import (
    CameraCreate,
    CameraDiscoveryProbeRequest,
    CameraDiscoveryScanRequest,
    CameraEndpointInput,
    CameraProbeResultOut,
    CameraUpdate,
    EventCreate,
    PersonCreate,
    PersonUpdate,
    PtzAbsoluteMoveIn,
    PtzContinuousMoveIn,
    PtzRelativeMoveIn,
    RecordingFileCreate,
    VideoStreamCreate,
    VideoStreamUpdate,
)
from app.schemas.users import UserRegister, UserOut
from app.security import hash_password
from app.services.onvif import (
    ONVIFServiceError,
    camera_to_detail_payload,
    discover_onvif_devices,
    dump_device_metadata,
    endpoint_has_onvif,
    goto_home,
    goto_preset,
    load_device_metadata,
    primary_stream_url,
    probe_camera,
    ptz_absolute_move,
    ptz_continuous_move,
    ptz_relative_move,
    ptz_stop,
    remove_preset,
    set_preset,
)


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


def _ensure_admin(user: models.User) -> None:
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


def _is_deleted(instance: Any) -> bool:
    return getattr(instance, "deleted_at", None) is not None


def _invalidate_gallery_cache() -> None:
    from app.routers import processors as processors_router

    processors_router.invalidate_gallery_cache()


def _normalize_endpoint_payloads(endpoints: list[CameraEndpointInput]) -> list[CameraEndpointInput]:
    seen: set[tuple[str, str]] = set()
    result: list[CameraEndpointInput] = []
    for endpoint in endpoints:
        url = endpoint.endpoint_url.strip()
        if not url:
            continue
        key = (endpoint.endpoint_kind, url)
        if key in seen:
            continue
        seen.add(key)
        result.append(endpoint.model_copy(update={"endpoint_url": url}))
    return result


async def _replace_camera_endpoints(
    session: AsyncSession,
    camera_id: int,
    endpoints: list[CameraEndpointInput],
) -> list[models.CameraEndpoint]:
    normalized = _normalize_endpoint_payloads(endpoints)
    existing_rows = (
        await session.execute(select(models.CameraEndpoint).where(models.CameraEndpoint.camera_id == camera_id))
    ).scalars().all()
    existing_map = {(row.endpoint_kind, row.endpoint_url): row for row in existing_rows}
    await session.execute(delete(models.CameraEndpoint).where(models.CameraEndpoint.camera_id == camera_id))

    persisted: list[models.CameraEndpoint] = []
    for endpoint in normalized:
        existing = existing_map.get((endpoint.endpoint_kind, endpoint.endpoint_url))
        username = endpoint.username if endpoint.username is not None else (existing.username if existing else None)
        password_secret = endpoint.password_secret
        if password_secret is None and existing is not None:
            password_secret = existing.password_secret
        row = models.CameraEndpoint(
            camera_id=camera_id,
            endpoint_kind=endpoint.endpoint_kind,
            endpoint_url=endpoint.endpoint_url,
            username=username,
            password_secret=password_secret,
            is_primary=endpoint.is_primary,
        )
        session.add(row)
        persisted.append(row)
    await session.flush()
    return persisted


async def _sync_presets_from_device(
    session: AsyncSession,
    camera: models.Camera,
    presets: list[dict[str, Any]],
) -> list[models.CameraPreset]:
    await session.execute(delete(models.CameraPreset).where(models.CameraPreset.camera_id == camera.camera_id))
    result: list[models.CameraPreset] = []
    for index, preset in enumerate(presets):
        row = models.CameraPreset(
            camera_id=camera.camera_id,
            name=str(preset.get("name") or f"Preset {index + 1}"),
            preset_token=preset.get("preset_token"),
            order_index=index,
            dwell_seconds=10,
        )
        session.add(row)
        result.append(row)
    await session.flush()
    return result


async def _load_camera(camera_id: int, session: AsyncSession) -> models.Camera:
    result = await session.execute(
        select(models.Camera)
        .where(models.Camera.camera_id == camera_id)
        .options(
            selectinload(models.Camera.endpoints),
            selectinload(models.Camera.presets),
            selectinload(models.Camera.roi_zones),
        )
    )
    camera = result.scalar_one_or_none()
    if camera is None or _is_deleted(camera):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    return camera


async def _camera_detail(camera_id: int, session: AsyncSession) -> dict[str, Any]:
    camera = await _load_camera(camera_id, session)
    payload = camera_to_detail_payload(camera)
    payload["presets"] = [PresetOut.model_validate(item).model_dump() for item in sorted(camera.presets, key=lambda row: row.order_index)]
    payload["roi_zones"] = [RoiZoneOut.model_validate(item).model_dump() for item in camera.roi_zones]
    return payload


# Users

@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserRegister,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> UserOut:
    _ensure_admin(current_user)
    existing = await session.execute(select(models.User).where(models.User.login == payload.login))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Login already exists")
    if payload.role_id not in (1, 2, 3):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="role_id must be 1 (admin), 2 (user) or 3 (viewer)")
    user = models.User(
        login=payload.login,
        password_hash=hash_password(payload.password),
        role_id=payload.role_id,
        first_name=payload.first_name.strip() if payload.first_name else None,
        last_name=payload.last_name.strip() if payload.last_name else None,
        middle_name=payload.middle_name.strip() if payload.middle_name else None,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserOut.model_validate(user)


@router.get("/users", response_model=List[UserOut])
async def list_users(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> List[UserOut]:
    _ensure_admin(current_user)
    result = await session.execute(select(models.User).order_by(models.User.user_id))
    return [UserOut.model_validate(user) for user in result.scalars().all()]


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    if user_id == current_user.user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete yourself")
    user = await session.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await session.delete(user)
    await session.commit()
    return {}


@router.post("/users/{user_id}/role")
async def set_user_role(
    user_id: int,
    role_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    if role_id not in (1, 2, 3):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="role_id must be 1, 2 or 3")
    user = await session.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.role_id = role_id
    await session.commit()
    return {"user_id": user.user_id, "role_id": user.role_id}


# Camera discovery and connection management

@router.post("/cameras/discovery/scan")
async def scan_cameras(
    payload: CameraDiscoveryScanRequest,
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    devices = await asyncio.to_thread(discover_onvif_devices, payload.timeout, payload.interface)
    return devices


@router.post("/cameras/discovery/probe", response_model=CameraProbeResultOut)
async def probe_camera_connection(
    payload: CameraDiscoveryProbeRequest,
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    try:
        result = await asyncio.to_thread(
            probe_camera,
            payload.host,
            payload.username,
            payload.password,
            payload.port,
            payload.use_https,
            payload.timeout,
            None,
        )
    except ONVIFServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return CameraProbeResultOut.model_validate(result.as_dict())


# Cameras CRUD

@router.get("/cameras/{camera_id}")
async def get_camera_detail(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    return await _camera_detail(camera_id, session)


@router.post("/cameras", status_code=status.HTTP_201_CREATED)
async def create_camera(
    payload: CameraCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    endpoints = _normalize_endpoint_payloads(payload.endpoints)
    camera = models.Camera(
        name=payload.name,
        ip_address=payload.ip_address,
        stream_url=primary_stream_url(payload.stream_url, endpoints),
        status_id=payload.status_id,
        location=payload.location,
        detection_enabled=payload.detection_enabled,
        recording_mode=payload.recording_mode,
        connection_kind=payload.connection_kind,
        supports_ptz=payload.supports_ptz,
        onvif_profile_token=payload.onvif_profile_token,
        device_metadata=dump_device_metadata(payload.device_metadata),
    )
    session.add(camera)
    await session.flush()
    if endpoints:
        await _replace_camera_endpoints(session, camera.camera_id, endpoints)
    await session.commit()
    return {"camera_id": camera.camera_id}


@router.patch("/cameras/{camera_id}")
async def update_camera(
    camera_id: int,
    payload: CameraUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    camera = await _load_camera(camera_id, session)
    data = payload.model_dump(exclude_unset=True)
    endpoints_payload = data.pop("endpoints", None)
    device_metadata = data.pop("device_metadata", None)
    for field, value in data.items():
        setattr(camera, field, value)
    if device_metadata is not None:
        camera.device_metadata = dump_device_metadata(device_metadata)
    if endpoints_payload is not None:
        endpoints = _normalize_endpoint_payloads([CameraEndpointInput.model_validate(item) if isinstance(item, dict) else item for item in endpoints_payload])
        await _replace_camera_endpoints(session, camera.camera_id, endpoints)
        camera.stream_url = primary_stream_url(camera.stream_url, endpoints)
    elif payload.stream_url is not None:
        camera.stream_url = payload.stream_url
    await session.commit()
    return {"camera_id": camera.camera_id}


@router.post("/cameras/{camera_id}/onvif/refresh")
async def refresh_onvif_camera(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    camera = await _load_camera(camera_id, session)
    onvif_endpoint = next((endpoint for endpoint in camera.endpoints if endpoint.endpoint_kind == "onvif"), None)
    if onvif_endpoint is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Camera is not configured for ONVIF")
    metadata = load_device_metadata(camera.device_metadata) or {}
    host = metadata.get("host") or camera.ip_address or urlparse(onvif_endpoint.endpoint_url).hostname
    port = int(metadata.get("port") or urlparse(onvif_endpoint.endpoint_url).port or 80)
    use_https = bool(metadata.get("use_https") or urlparse(onvif_endpoint.endpoint_url).scheme == "https")
    if not host:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Camera host is not configured")
    try:
        result = await asyncio.to_thread(
            probe_camera,
            host,
            onvif_endpoint.username,
            onvif_endpoint.password_secret,
            port,
            use_https,
            6,
            None,
        )
    except ONVIFServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    camera.ip_address = result.ip_address or camera.ip_address
    camera.stream_url = primary_stream_url(camera.stream_url, result.endpoints)
    camera.connection_kind = result.connection_kind
    camera.supports_ptz = result.supports_ptz
    camera.onvif_profile_token = result.onvif_profile_token
    camera.device_metadata = dump_device_metadata(result.device_metadata)
    persisted_endpoints = []
    for item in result.endpoints:
        persisted_endpoints.append(
            CameraEndpointInput(
                endpoint_kind=item["endpoint_kind"],
                endpoint_url=item["endpoint_url"],
                username=onvif_endpoint.username,
                password_secret=onvif_endpoint.password_secret,
                is_primary=bool(item.get("is_primary")),
            )
        )
    await _replace_camera_endpoints(session, camera.camera_id, persisted_endpoints)
    await _sync_presets_from_device(session, camera, result.presets)
    await session.commit()
    return await _camera_detail(camera_id, session)


@router.delete("/cameras/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    camera = await session.get(models.Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    if _is_deleted(camera):
        return {}
    camera.deleted_at = datetime.utcnow()
    camera.detection_enabled = False
    camera.tracking_enabled = False
    camera.tracking_mode = "off"
    await session.execute(
        delete(models.ProcessorCameraAssignment).where(models.ProcessorCameraAssignment.camera_id == camera_id)
    )
    await session.commit()
    return {}


@router.post("/cameras/{camera_id}/streams", status_code=status.HTTP_201_CREATED)
async def add_stream(
    camera_id: int,
    payload: VideoStreamCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    camera = await session.get(models.Camera, camera_id)
    if camera is None or _is_deleted(camera):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    stream = models.VideoStream(
        camera_id=camera_id,
        resolution=payload.resolution,
        fps=payload.fps,
        enabled=payload.enabled,
        stream_url=payload.stream_url,
    )
    session.add(stream)
    await session.commit()
    await session.refresh(stream)
    return {"video_stream_id": stream.video_stream_id}


@router.patch("/streams/{stream_id}")
async def update_stream(
    stream_id: int,
    payload: VideoStreamUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    stream = await session.get(models.VideoStream, stream_id)
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stream not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(stream, field, value)
    await session.commit()
    return {"video_stream_id": stream.video_stream_id}


# Persons

@router.get("/persons")
async def list_persons(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    counts = (
        select(
            models.PersonEmbedding.person_id,
            func.count(models.PersonEmbedding.person_embedding_id).label("embedding_count"),
        )
        .group_by(models.PersonEmbedding.person_id)
        .subquery()
    )
    result = await session.execute(
        select(models.Person, func.coalesce(counts.c.embedding_count, 0))
        .outerjoin(counts, counts.c.person_id == models.Person.person_id)
        .where(models.Person.deleted_at.is_(None))
        .order_by(models.Person.person_id)
    )
    return [
        {
            "person_id": person.person_id,
            "first_name": person.first_name,
            "last_name": person.last_name,
            "middle_name": person.middle_name,
            "category_id": person.category_id,
            "has_embedding": int(embedding_count or 0) > 0,
            "created_at": str(person.created_at) if person.created_at else None,
        }
        for person, embedding_count in result.all()
    ]


@router.post("/persons", status_code=status.HTTP_201_CREATED)
async def create_person(
    payload: PersonCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    person = models.Person(
        first_name=payload.first_name,
        last_name=payload.last_name,
        middle_name=payload.middle_name,
        category_id=payload.category_id,
    )
    session.add(person)
    await session.commit()
    await session.refresh(person)
    _invalidate_gallery_cache()
    return {"person_id": person.person_id}


@router.patch("/persons/{person_id}")
async def update_person(
    person_id: int,
    payload: PersonUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    person = await session.get(models.Person, person_id)
    if person is None or _is_deleted(person):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(person, field, value)
    await session.commit()
    _invalidate_gallery_cache()
    return {"person_id": person.person_id}


@router.delete("/persons/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(
    person_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    person = await session.get(models.Person, person_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")
    if _is_deleted(person):
        return {}
    person.deleted_at = datetime.utcnow()
    result = await session.execute(select(models.Camera).where(models.Camera.tracking_target_person_id == person_id))
    for camera in result.scalars().all():
        camera.tracking_target_person_id = None
    await session.commit()
    _invalidate_gallery_cache()
    return {}


# Events

@router.post("/events", status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    event = models.Event(
        camera_id=payload.camera_id,
        event_type_id=payload.event_type_id,
        person_id=payload.person_id,
        recording_file_id=payload.recording_file_id,
        confidence=payload.confidence,
        created_by_user_id=current_user.user_id,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return {"event_id": event.event_id}


@router.get("/events", response_model=List[dict])
async def list_events(
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    result = await session.execute(select(models.Event))
    events = result.scalars().all()
    return [
        {
            "event_id": item.event_id,
            "camera_id": item.camera_id,
            "event_type_id": item.event_type_id,
            "person_id": item.person_id,
            "recording_file_id": item.recording_file_id,
            "confidence": float(item.confidence) if item.confidence is not None else None,
            "event_ts": item.event_ts,
        }
        for item in events
    ]


# Recordings

@router.post("/recordings", status_code=status.HTTP_201_CREATED)
async def create_recording(
    payload: RecordingFileCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    recording = models.RecordingFile(
        video_stream_id=payload.video_stream_id,
        storage_target_id=payload.storage_target_id,
        file_kind=payload.file_kind,
        file_path=payload.file_path,
        duration_seconds=payload.duration_seconds,
        file_size_bytes=payload.file_size_bytes,
        checksum=payload.checksum,
    )
    session.add(recording)
    await session.commit()
    await session.refresh(recording)
    return {"recording_file_id": recording.recording_file_id}


# Presets

@router.get("/cameras/{camera_id}/presets", response_model=List[PresetOut])
async def list_presets(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    result = await session.execute(
        select(models.CameraPreset)
        .where(models.CameraPreset.camera_id == camera_id)
        .order_by(models.CameraPreset.order_index)
    )
    return result.scalars().all()


@router.post("/cameras/{camera_id}/presets/refresh", response_model=List[PresetOut])
async def refresh_presets(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    camera = await _load_camera(camera_id, session)
    if not endpoint_has_onvif(camera.endpoints):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Camera is not configured for ONVIF")
    try:
        detail = await refresh_onvif_camera(camera_id, session, current_user)
    except HTTPException:
        raise
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
    _ensure_admin(current_user)
    camera = await _load_camera(camera_id, session)
    preset_token = payload.preset_token
    if endpoint_has_onvif(camera.endpoints):
        try:
            preset_token = await asyncio.to_thread(set_preset, camera, payload.name, payload.preset_token)
        except ONVIFServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    preset = models.CameraPreset(
        camera_id=camera_id,
        name=payload.name,
        preset_token=preset_token,
        order_index=payload.order_index,
        dwell_seconds=payload.dwell_seconds,
    )
    session.add(preset)
    await session.commit()
    await session.refresh(preset)
    return preset


@router.post("/cameras/{camera_id}/presets/{preset_id}/goto")
async def goto_camera_preset(
    camera_id: int,
    preset_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    camera = await _load_camera(camera_id, session)
    preset = await session.get(models.CameraPreset, preset_id)
    if not preset or preset.camera_id != camera_id or not preset.preset_token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset not found")
    if not endpoint_has_onvif(camera.endpoints):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Camera is not configured for ONVIF")
    try:
        await asyncio.to_thread(goto_preset, camera, preset.preset_token)
    except ONVIFServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"ok": True}


@router.delete("/cameras/{camera_id}/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(
    camera_id: int,
    preset_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    camera = await _load_camera(camera_id, session)
    preset = await session.get(models.CameraPreset, preset_id)
    if not preset or preset.camera_id != camera_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset not found")
    if endpoint_has_onvif(camera.endpoints) and preset.preset_token:
        try:
            await asyncio.to_thread(remove_preset, camera, preset.preset_token)
        except ONVIFServiceError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.delete(preset)
    await session.commit()
    return {}


# ROI zones

@router.get("/cameras/{camera_id}/roi-zones", response_model=List[RoiZoneOut])
async def list_roi_zones(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    result = await session.execute(select(models.CameraRoiZone).where(models.CameraRoiZone.camera_id == camera_id))
    return result.scalars().all()


@router.post("/cameras/{camera_id}/roi-zones", status_code=status.HTTP_201_CREATED, response_model=RoiZoneOut)
async def create_roi_zone(
    camera_id: int,
    payload: RoiZoneCreate,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    camera = await session.get(models.Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
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
    _ensure_admin(current_user)
    zone = await session.get(models.CameraRoiZone, zone_id)
    if not zone or zone.camera_id != camera_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ROI zone not found")
    await session.delete(zone)
    await session.commit()
    return {}


# ONVIF PTZ

@router.post("/cameras/{camera_id}/onvif/ptz/relative")
async def camera_ptz_relative(
    camera_id: int,
    payload: PtzRelativeMoveIn,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    camera = await _load_camera(camera_id, session)
    try:
        return await asyncio.to_thread(ptz_relative_move, camera, payload.pan, payload.tilt, payload.zoom, payload.speed)
    except ONVIFServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/cameras/{camera_id}/onvif/ptz/continuous")
async def camera_ptz_continuous(
    camera_id: int,
    payload: PtzContinuousMoveIn,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    camera = await _load_camera(camera_id, session)
    try:
        return await asyncio.to_thread(ptz_continuous_move, camera, payload.pan, payload.tilt, payload.zoom, payload.timeout_seconds)
    except ONVIFServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/cameras/{camera_id}/onvif/ptz/absolute")
async def camera_ptz_absolute(
    camera_id: int,
    payload: PtzAbsoluteMoveIn,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    camera = await _load_camera(camera_id, session)
    try:
        return await asyncio.to_thread(ptz_absolute_move, camera, payload.pan, payload.tilt, payload.zoom, payload.speed)
    except ONVIFServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/cameras/{camera_id}/onvif/ptz/home")
async def camera_ptz_home(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    camera = await _load_camera(camera_id, session)
    try:
        return await asyncio.to_thread(goto_home, camera)
    except ONVIFServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/cameras/{camera_id}/onvif/ptz/stop")
async def camera_ptz_stop(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    _ensure_admin(current_user)
    camera = await _load_camera(camera_id, session)
    try:
        return await asyncio.to_thread(ptz_stop, camera)
    except ONVIFServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
