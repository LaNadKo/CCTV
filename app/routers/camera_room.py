"""Camera-to-room calibration endpoints."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.schemas.camera_room import (
    CameraRoomCalibration,
    CameraRoomCalibrationIn,
    CameraRoomCalibrationList,
    CameraRoomLedDetectionOut,
    CameraRoomProjectionIn,
    CameraRoomProjectionOut,
)
from app.services.camera_room import (
    capture_camera_frame_jpeg,
    detect_red_led_candidates,
    get_camera_room_calibration,
    project_camera_bbox,
    read_camera_room_calibrations,
    save_camera_room_calibration,
    save_default_camera_room_calibration,
)

router = APIRouter(prefix="/camera-room", tags=["camera-room"])


async def _load_camera(camera_id: int, session: AsyncSession) -> models.Camera:
    result = await session.execute(
        select(models.Camera)
        .where(models.Camera.camera_id == camera_id, models.Camera.deleted_at.is_(None))
        .options(selectinload(models.Camera.endpoints))
    )
    camera = result.scalar_one_or_none()
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    return camera


@router.get("/calibrations", response_model=CameraRoomCalibrationList)
async def list_calibrations(_current_user=Depends(get_current_user)) -> CameraRoomCalibrationList:
    return read_camera_room_calibrations()


@router.get("/calibrations/{camera_id}", response_model=CameraRoomCalibration)
async def get_calibration(camera_id: int, _current_user=Depends(get_current_user)) -> CameraRoomCalibration:
    calibration = get_camera_room_calibration(camera_id)
    if calibration is None:
        calibration = save_default_camera_room_calibration(camera_id)
    return calibration


@router.put("/calibrations/{camera_id}", response_model=CameraRoomCalibration)
async def put_calibration(
    camera_id: int,
    payload: CameraRoomCalibrationIn,
    current_user=Depends(get_current_user),
) -> CameraRoomCalibration:
    if getattr(current_user, "role_id", None) != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only administrators can update camera-room calibration")
    return save_camera_room_calibration(camera_id, payload)


@router.post("/calibrations/{camera_id}/default", response_model=CameraRoomCalibration)
async def create_default_calibration(
    camera_id: int,
    current_user=Depends(get_current_user),
) -> CameraRoomCalibration:
    if getattr(current_user, "role_id", None) != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only administrators can update camera-room calibration")
    return save_default_camera_room_calibration(camera_id)


@router.post("/project", response_model=CameraRoomProjectionOut)
async def project_bbox(
    payload: CameraRoomProjectionIn,
    _current_user=Depends(get_current_user),
) -> CameraRoomProjectionOut:
    projection = project_camera_bbox(payload)
    if projection is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Camera-room projection is disabled for this camera")
    return projection


@router.get("/cameras/{camera_id}/frame.jpg")
async def get_camera_frame(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    _current_user=Depends(get_current_user),
) -> Response:
    camera = await _load_camera(camera_id, session)
    try:
        payload, width, height = await asyncio.to_thread(capture_camera_frame_jpeg, camera)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Frame-Width": str(width),
            "X-Frame-Height": str(height),
        },
    )


@router.get("/cameras/{camera_id}/red-leds", response_model=CameraRoomLedDetectionOut)
async def get_camera_red_leds(
    camera_id: int,
    session: AsyncSession = Depends(get_session),
    _current_user=Depends(get_current_user),
) -> CameraRoomLedDetectionOut:
    camera = await _load_camera(camera_id, session)
    try:
        payload, _width, _height = await asyncio.to_thread(capture_camera_frame_jpeg, camera)
        return await asyncio.to_thread(detect_red_led_candidates, camera_id, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
