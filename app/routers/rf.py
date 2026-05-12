"""RF room diagnostics endpoints."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user
from app.schemas.rf import (
    RfBaselineSummary,
    RfHistoryOut,
    RfRoomLayout,
    RfRoomSnapshot,
    RfSnapshotSample,
)
from app.services.rf_history import append_rf_sample, read_rf_samples, summarize_rf_baseline
from app.services.rf_room import collect_rf_room_snapshot, get_rf_room_layout_path, load_rf_room_layout, save_rf_room_layout

router = APIRouter(prefix="/rf", tags=["rf"])


@router.get("/room", response_model=RfRoomLayout)
async def get_rf_room(_current_user=Depends(get_current_user)) -> RfRoomLayout:
    try:
        return load_rf_room_layout()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load RF room layout from {get_rf_room_layout_path()}: {exc}",
        ) from exc


@router.put("/room", response_model=RfRoomLayout)
async def update_rf_room(
    layout: RfRoomLayout,
    current_user=Depends(get_current_user),
) -> RfRoomLayout:
    if getattr(current_user, "role_id", None) != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can update RF room layout",
        )
    try:
        return save_rf_room_layout(layout)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save RF room layout to {get_rf_room_layout_path()}: {exc}",
        ) from exc


@router.get("/snapshot", response_model=RfRoomSnapshot)
async def get_rf_snapshot(
    include_scan: bool = Query(False, description="Run slow /scan collection on each ESP32 node"),
    _current_user=Depends(get_current_user),
) -> RfRoomSnapshot:
    try:
        return await collect_rf_room_snapshot(include_scan=include_scan)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to collect RF room snapshot: {exc}",
        ) from exc


@router.post("/history/collect", response_model=RfSnapshotSample)
async def collect_rf_history_sample(
    include_scan: bool = Query(False, description="Run slow /scan collection before storing the sample"),
    _current_user=Depends(get_current_user),
) -> RfSnapshotSample:
    try:
        snapshot = await collect_rf_room_snapshot(include_scan=include_scan)
        return append_rf_sample(snapshot)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to collect RF history sample: {exc}",
        ) from exc


@router.get("/history", response_model=RfHistoryOut)
async def get_rf_history(
    limit: int = Query(100, ge=1, le=1000),
    _current_user=Depends(get_current_user),
) -> RfHistoryOut:
    try:
        return read_rf_samples(limit=limit)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read RF history: {exc}",
        ) from exc


@router.get("/baseline", response_model=RfBaselineSummary)
async def get_rf_baseline(
    limit: int = Query(100, ge=1, le=1000),
    _current_user=Depends(get_current_user),
) -> RfBaselineSummary:
    try:
        return summarize_rf_baseline(limit=limit)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to summarize RF baseline: {exc}",
        ) from exc


@router.post("/history/collect-batch", response_model=RfBaselineSummary)
async def collect_rf_history_batch(
    count: int = Query(12, ge=1, le=60, description="Number of samples to collect"),
    interval_seconds: float = Query(5.0, ge=1.0, le=30.0, description="Delay between samples"),
    include_scan: bool = Query(False, description="Run slow /scan collection for every sample"),
    _current_user=Depends(get_current_user),
) -> RfBaselineSummary:
    try:
        for index in range(count):
            snapshot = await collect_rf_room_snapshot(include_scan=include_scan)
            append_rf_sample(snapshot)
            if index < count - 1:
                await asyncio.sleep(interval_seconds)
        return summarize_rf_baseline(limit=max(100, count))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to collect RF baseline batch: {exc}",
        ) from exc
