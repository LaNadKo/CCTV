from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app import models
from app.dependencies import get_current_user
from app.permissions import is_admin
from app.schemas.ruview import (
    RuViewBridgeStatus,
    RuViewCalibrationStartIn,
    RuViewCalibrationStatus,
    RuViewPoseSnapshot,
    RuViewUpstreamStatus,
)
from app.services.ruview_bridge import (
    get_ruview_bridge_status,
    reset_ruview_bridge,
    start_ruview_bridge,
)
from app.services.ruview_calibration import (
    get_calibration_status,
    start_calibration_session,
    stop_calibration_session,
)
from app.services.ruview_pose import get_ruview_pose_snapshot, reset_ruview_pose_tracks
from app.services.ruview_upstream import get_ruview_upstream_status

router = APIRouter(prefix="/ruview", tags=["ruview"])


def _ensure_admin(user: models.User) -> None:
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


@router.get("/status", response_model=RuViewBridgeStatus)
async def ruview_status(_user: models.User = Depends(get_current_user)) -> RuViewBridgeStatus:
    return get_ruview_bridge_status()


@router.get("/upstream", response_model=RuViewUpstreamStatus)
async def ruview_upstream(_user: models.User = Depends(get_current_user)) -> RuViewUpstreamStatus:
    return await get_ruview_upstream_status()


@router.get("/pose", response_model=RuViewPoseSnapshot)
async def ruview_pose(_user: models.User = Depends(get_current_user)) -> RuViewPoseSnapshot:
    return await get_ruview_pose_snapshot()


@router.get("/calibration/status", response_model=RuViewCalibrationStatus)
async def ruview_calibration_status(
    _user: models.User = Depends(get_current_user),
) -> RuViewCalibrationStatus:
    return RuViewCalibrationStatus(**get_calibration_status())


@router.post("/calibration/start", response_model=RuViewCalibrationStatus)
async def ruview_calibration_start(
    payload: RuViewCalibrationStartIn,
    user: models.User = Depends(get_current_user),
) -> RuViewCalibrationStatus:
    _ensure_admin(user)
    return RuViewCalibrationStatus(
        **start_calibration_session(
            label=payload.label,
            scenario=payload.scenario,
            duration_seconds=payload.duration_seconds,
            notes=payload.notes,
        )
    )


@router.post("/calibration/stop", response_model=RuViewCalibrationStatus)
async def ruview_calibration_stop(
    user: models.User = Depends(get_current_user),
) -> RuViewCalibrationStatus:
    _ensure_admin(user)
    return RuViewCalibrationStatus(**stop_calibration_session())


@router.post("/start", response_model=RuViewBridgeStatus)
async def ruview_start(user: models.User = Depends(get_current_user)) -> RuViewBridgeStatus:
    _ensure_admin(user)
    start_ruview_bridge()
    return get_ruview_bridge_status()


@router.post("/reset", response_model=RuViewBridgeStatus)
async def ruview_reset(user: models.User = Depends(get_current_user)) -> RuViewBridgeStatus:
    _ensure_admin(user)
    reset_ruview_bridge()
    reset_ruview_pose_tracks()
    return get_ruview_bridge_status()
