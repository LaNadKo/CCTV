from typing import List, Optional
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.db import get_session
from app.dependencies import get_current_user, get_current_user_allow_query
from app.permissions import check_permission, user_camera_permission_sync
from app.processor_media import get_processor_media_base_url, get_processor_media_headers
from app.schemas.cameras import CameraEndpointInfo, CameraOut, CameraPermissionOut
from app.services.onvif import (
    endpoint_has_onvif,
    endpoint_kinds,
    load_device_metadata,
    primary_stream_url,
    read_ptz_capabilities,
)

router = APIRouter(prefix="/cameras", tags=["cameras"])
log = logging.getLogger("app.activity")


async def _proxy_processor_camera_stream(
    proc: models.Processor,
    camera_id: int,
    overlay: bool,
) -> StreamingResponse:
    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=3, read=10, write=10, pool=10))
    stream_cm = client.stream(
        "GET",
        f"{get_processor_media_base_url(proc)}/cameras/{camera_id}/stream.mjpeg",
        headers=get_processor_media_headers(proc),
        params={"overlay": "1" if overlay else "0"},
    )
    upstream = await stream_cm.__aenter__()
    if upstream.status_code >= 400:
        body = await upstream.aread()
        await stream_cm.__aexit__(None, None, None)
        await client.aclose()
        raise RuntimeError(body.decode("utf-8", "replace") or f"processor media status {upstream.status_code}")

    async def gen():
        try:
            async for chunk in upstream.aiter_bytes():
                if chunk:
                    yield chunk
        finally:
            await stream_cm.__aexit__(None, None, None)
            await client.aclose()

    return StreamingResponse(
        gen(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "multipart/x-mixed-replace; boundary=frame"),
    )


@router.get("", response_model=List[CameraOut])
async def list_cameras(
    group_id: Optional[int] = Query(None, description="Filter cameras by group"),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> List[CameraOut]:
    stmt = select(models.Camera).where(models.Camera.deleted_at.is_(None)).options(selectinload(models.Camera.endpoints))
    if group_id is not None:
        stmt = stmt.where(models.Camera.group_id == group_id)
    result = await session.execute(stmt)
    cameras = result.scalars().all()

    permission = user_camera_permission_sync(current_user)
    if permission is None:
        return []

    return [
        CameraOut(
            camera_id=camera.camera_id,
            name=camera.name,
            location=camera.location,
            ip_address=camera.ip_address,
            stream_url=primary_stream_url(camera.stream_url, camera.endpoints),
            permission=permission,
            detection_enabled=camera.detection_enabled,
            recording_mode=camera.recording_mode,
            tracking_enabled=camera.tracking_enabled,
            tracking_mode=camera.tracking_mode,
            tracking_target_person_id=camera.tracking_target_person_id,
            group_id=camera.group_id,
            connection_kind=camera.connection_kind,
            onvif_enabled=endpoint_has_onvif(camera.endpoints),
            supports_ptz=camera.supports_ptz,
            ptz_capabilities=read_ptz_capabilities(load_device_metadata(camera.device_metadata), camera.supports_ptz),
            endpoint_kinds=endpoint_kinds(camera.endpoints),
            endpoints=[
                CameraEndpointInfo(
                    endpoint_kind=endpoint.endpoint_kind,
                    endpoint_url=endpoint.endpoint_url,
                    is_primary=endpoint.is_primary,
                )
                for endpoint in camera.endpoints
            ],
        )
        for camera in cameras
    ]


@router.get("/{camera_id}/permission", response_model=CameraPermissionOut)
async def get_camera_permission(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> CameraPermissionOut:
    result = await session.execute(
        select(models.Camera).where(
            models.Camera.camera_id == camera_id,
            models.Camera.deleted_at.is_(None),
        )
    )
    camera = result.scalar_one_or_none()
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    permission = user_camera_permission_sync(current_user)
    return CameraPermissionOut(camera_id=camera_id, permission=permission, allowed=permission is not None)


@router.get("/{camera_id}/stream")
async def stream_camera(
    camera_id: int,
    annotate: bool = True,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user_allow_query),
):
    camera = await session.get(models.Camera, camera_id)
    if camera is None or camera.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    permission = user_camera_permission_sync(current_user)
    if not check_permission(permission, "view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this camera")

    assignment_result = await session.execute(
        select(models.ProcessorCameraAssignment, models.Processor)
        .join(models.Processor, models.Processor.processor_id == models.ProcessorCameraAssignment.processor_id)
        .where(
            models.ProcessorCameraAssignment.camera_id == camera_id,
            models.Processor.status == "online",
        )
        .limit(1)
    )
    assignment_row = assignment_result.first()
    if assignment_row is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Live stream is available only through an assigned processor",
        )

    _, processor = assignment_row
    try:
        return await _proxy_processor_camera_stream(processor, camera_id, overlay=annotate)
    except Exception as exc:
        log.warning(
            "camera.stream.processor_proxy_failed camera=%s processor=%s reason=%s",
            camera_id,
            processor.processor_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Processor stream is unavailable: {exc}",
        ) from exc
