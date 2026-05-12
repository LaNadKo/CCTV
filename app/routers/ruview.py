"""RuView CSI bridge endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user
from app.schemas.ruview import (
    RuViewBridgeStatus,
    RuViewCalibrationHistory,
    RuViewCalibrationSample,
    RuViewCalibrationSampleIn,
    RuViewUpstreamStatus,
    RuViewZoneEstimate,
)
from app.services.ruview_calibration import collect_calibration_sample, estimate_current_zone, read_calibration_samples
from app.services.ruview_bridge import get_ruview_bridge_status, reset_ruview_bridge, start_ruview_bridge
from app.services.ruview_upstream import get_ruview_upstream_status

router = APIRouter(prefix="/ruview", tags=["ruview"])


@router.get("/status", response_model=RuViewBridgeStatus)
async def get_status(_current_user=Depends(get_current_user)) -> RuViewBridgeStatus:
    return get_ruview_bridge_status()


@router.post("/start", response_model=RuViewBridgeStatus)
async def start_bridge(current_user=Depends(get_current_user)) -> RuViewBridgeStatus:
    if getattr(current_user, "role_id", None) != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only administrators can start RuView bridge")
    start_ruview_bridge()
    return get_ruview_bridge_status()


@router.post("/reset", response_model=RuViewBridgeStatus)
async def reset_bridge(current_user=Depends(get_current_user)) -> RuViewBridgeStatus:
    if getattr(current_user, "role_id", None) != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only administrators can reset RuView bridge")
    reset_ruview_bridge()
    return get_ruview_bridge_status()


@router.post("/calibration/collect", response_model=RuViewCalibrationSample)
async def collect_calibration(
    payload: RuViewCalibrationSampleIn,
    current_user=Depends(get_current_user),
) -> RuViewCalibrationSample:
    if getattr(current_user, "role_id", None) != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only administrators can collect RuView calibration")
    return await collect_calibration_sample(payload)


@router.get("/calibration", response_model=RuViewCalibrationHistory)
async def get_calibration_history(
    limit: int = Query(100, ge=1, le=1000),
    _current_user=Depends(get_current_user),
) -> RuViewCalibrationHistory:
    return read_calibration_samples(limit=limit)


@router.get("/estimate", response_model=RuViewZoneEstimate)
async def get_zone_estimate(
    limit: int = Query(200, ge=1, le=1000),
    _current_user=Depends(get_current_user),
) -> RuViewZoneEstimate:
    return estimate_current_zone(limit=limit)


@router.get("/upstream", response_model=RuViewUpstreamStatus)
async def get_upstream_status(_current_user=Depends(get_current_user)) -> RuViewUpstreamStatus:
    return await get_ruview_upstream_status()
