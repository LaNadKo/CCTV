"""Camera bbox to room-plane projection.

The default calibration intentionally maps the full image frame to the room
rectangle. It is coarse, but it lets the camera start producing supervised RF
labels immediately; a manual 4-point homography can replace it later.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.config import settings
from app.schemas.camera_room import (
    CameraRoomCalibration,
    CameraRoomCalibrationIn,
    CameraRoomLedCandidate,
    CameraRoomLedDetectionOut,
    CameraRoomCalibrationList,
    CameraRoomImagePoint,
    CameraRoomPoint,
    CameraRoomProjectionIn,
    CameraRoomProjectionOut,
)
from app.schemas.tracking import CameraTrackBox, ProcessorTrackObservationIn
from app.services.onvif import build_authenticated_url
from app.services.rf_room import load_rf_room_layout


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _calibration_path() -> Path:
    raw = Path(settings.camera_room_calibration_path)
    if raw.is_absolute():
        return raw
    return _repo_root() / raw


def resolve_camera_capture_source(camera: Any) -> str | int | None:
    rtsp_candidates: list[tuple[int, str]] = []
    http_candidates: list[tuple[int, str]] = []
    for endpoint in getattr(camera, "endpoints", []) or []:
        kind = getattr(endpoint, "endpoint_kind", None)
        url = getattr(endpoint, "endpoint_url", None)
        if not kind or not url:
            continue
        weight = 100 if getattr(endpoint, "is_primary", False) else 0
        auth_url = build_authenticated_url(
            str(url),
            getattr(endpoint, "username", None),
            getattr(endpoint, "password_secret", None),
        )
        if kind == "rtsp":
            rtsp_candidates.append((weight, auth_url))
        elif kind == "http":
            http_candidates.append((weight, auth_url))
    if rtsp_candidates:
        rtsp_candidates.sort(reverse=True)
        return rtsp_candidates[0][1]
    if http_candidates:
        http_candidates.sort(reverse=True)
        return http_candidates[0][1]

    stream_url = getattr(camera, "stream_url", None)
    if stream_url:
        stream = str(stream_url)
        if stream.isdigit():
            return int(stream)
        return stream
    ip_address = getattr(camera, "ip_address", None)
    if ip_address:
        return f"rtsp://{ip_address}:554/stream"
    return None


def capture_camera_frame_jpeg(camera: Any, warmup_frames: int = 5) -> tuple[bytes, int, int]:
    source = resolve_camera_capture_source(camera)
    if source is None:
        raise RuntimeError("Camera stream source is not configured")
    if isinstance(source, str) and source.lower().startswith("rtsp://"):
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0|buffer_size;102400"
        )
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    else:
        cap = cv2.VideoCapture(source)
    try:
        for prop, value in (
            (getattr(cv2, "CAP_PROP_BUFFERSIZE", None), 1),
            (getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None), 5000),
            (getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None), 5000),
        ):
            if prop is not None:
                cap.set(prop, value)
        if not cap.isOpened():
            raise RuntimeError("Camera stream could not be opened")

        frame = None
        frames_to_read = max(1, warmup_frames)
        for _ in range(frames_to_read):
            ok, candidate = cap.read()
            if ok and candidate is not None:
                frame = candidate
        if frame is None:
            raise RuntimeError("Camera stream returned no frame")
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            raise RuntimeError("Camera frame could not be encoded")
        height, width = frame.shape[:2]
        return encoded.tobytes(), int(width), int(height)
    finally:
        cap.release()


def detect_red_led_candidates(camera_id: int, jpeg_bytes: bytes) -> CameraRoomLedDetectionOut:
    data = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("Camera frame could not be decoded")
    height, width = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    lower_red_a = cv2.inRange(hsv, np.array([0, 80, 110]), np.array([10, 255, 255]))
    lower_red_b = cv2.inRange(hsv, np.array([170, 80, 110]), np.array([180, 255, 255]))
    mask = cv2.bitwise_or(lower_red_a, lower_red_b)
    mask = cv2.medianBlur(mask, 5)
    mask = cv2.dilate(mask, np.ones((3, 3), dtype=np.uint8), iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[CameraRoomLedCandidate] = []
    frame_area = max(width * height, 1)
    max_led_area = max(80.0, frame_area * 0.0005)
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < 3.0 or area > max_led_area:
            continue
        (x, y), radius = cv2.minEnclosingCircle(contour)
        if radius < 1.2 or radius > min(width, height) * 0.018:
            continue
        perimeter = float(cv2.arcLength(contour, True))
        circularity = 0.0 if perimeter <= 0 else min(1.0, (4.0 * np.pi * area) / (perimeter * perimeter))
        score = float(area * (0.45 + 0.55 * circularity))
        candidates.append(
            CameraRoomLedCandidate(
                x=round(float(x), 1),
                y=round(float(y), 1),
                radius=round(float(radius), 1),
                score=round(score, 2),
            )
        )
    candidates.sort(key=lambda item: item.score, reverse=True)
    return CameraRoomLedDetectionOut(
        camera_id=camera_id,
        frame_width=int(width),
        frame_height=int(height),
        candidates=candidates[:12],
    )


def read_camera_room_calibrations() -> CameraRoomCalibrationList:
    path = _calibration_path()
    if not path.exists():
        return CameraRoomCalibrationList(storage_path=str(path), calibrations=[])
    payload = json.loads(path.read_text(encoding="utf-8"))
    calibrations = payload.get("calibrations", []) if isinstance(payload, dict) else []
    return CameraRoomCalibrationList(
        storage_path=str(path),
        calibrations=[CameraRoomCalibration.model_validate(item) for item in calibrations],
    )


def get_camera_room_calibration(camera_id: int) -> CameraRoomCalibration | None:
    for calibration in read_camera_room_calibrations().calibrations:
        if calibration.camera_id == camera_id:
            return calibration
    return None


def save_camera_room_calibration(camera_id: int, payload: CameraRoomCalibrationIn) -> CameraRoomCalibration:
    existing = get_camera_room_calibration(camera_id)
    now = datetime.now(timezone.utc)
    calibration = CameraRoomCalibration(
        camera_id=camera_id,
        created_at=existing.created_at if existing is not None else now,
        updated_at=now,
        **payload.model_dump(),
    )
    all_calibrations = [
        item for item in read_camera_room_calibrations().calibrations if item.camera_id != camera_id
    ]
    all_calibrations.append(calibration)
    all_calibrations.sort(key=lambda item: item.camera_id)

    path = _calibration_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(
        {
            "schema_version": 1,
            "calibrations": [item.model_dump(mode="json", exclude_none=True) for item in all_calibrations],
        },
        ensure_ascii=False,
        indent=2,
    )
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(f"{raw}\n", encoding="utf-8")
    tmp_path.replace(path)
    return calibration


def build_default_camera_room_calibration(camera_id: int) -> CameraRoomCalibration:
    layout = load_rf_room_layout()
    now = datetime.now(timezone.utc)
    room = layout.room
    return CameraRoomCalibration(
        camera_id=camera_id,
        enabled=True,
        label=f"Camera {camera_id} default full-frame room map",
        image_points=[
            CameraRoomImagePoint(x=0.0, y=0.0),
            CameraRoomImagePoint(x=1.0, y=0.0),
            CameraRoomImagePoint(x=1.0, y=1.0),
            CameraRoomImagePoint(x=0.0, y=1.0),
        ],
        room_points=[
            CameraRoomPoint(x_cm=0.0, y_cm=room.depth_cm),
            CameraRoomPoint(x_cm=room.width_cm, y_cm=room.depth_cm),
            CameraRoomPoint(x_cm=room.width_cm, y_cm=0.0),
            CameraRoomPoint(x_cm=0.0, y_cm=0.0),
        ],
        source="auto_full_frame",
        created_at=now,
        updated_at=now,
    )


def save_default_camera_room_calibration(camera_id: int) -> CameraRoomCalibration:
    default = build_default_camera_room_calibration(camera_id)
    payload = CameraRoomCalibrationIn(
        enabled=default.enabled,
        label=default.label,
        image_points=default.image_points,
        room_points=default.room_points,
        source=default.source,
    )
    return save_camera_room_calibration(camera_id, payload)


def project_track_observation(payload: ProcessorTrackObservationIn) -> CameraRoomProjectionOut | None:
    if payload.bbox is None or payload.frame_width is None or payload.frame_height is None:
        return None
    return project_camera_bbox(
        CameraRoomProjectionIn(
            camera_id=payload.camera_id,
            bbox=payload.bbox,
            frame_width=payload.frame_width,
            frame_height=payload.frame_height,
        )
    )


def project_camera_bbox(payload: CameraRoomProjectionIn) -> CameraRoomProjectionOut | None:
    calibration = get_camera_room_calibration(payload.camera_id)
    if calibration is None:
        calibration = build_default_camera_room_calibration(payload.camera_id)
    if not calibration.enabled:
        return None

    floor_x, floor_y = _bbox_floor_point(payload.bbox)
    image_x, image_y = _normalize_image_point(floor_x, floor_y, payload.frame_width, payload.frame_height, calibration)
    room_x, room_y = _project_homography(calibration, image_x, image_y)
    return _clamp_projection(payload.camera_id, room_x, room_y, calibration.source)


def related_nodes_for_point(x_cm: float, y_cm: float, limit: int = 3) -> list[int]:
    layout = load_rf_room_layout()
    ranked: list[tuple[float, int]] = []
    for node in layout.nodes:
        if not node.physical_label.isdigit():
            continue
        distance_sq = (node.x_cm - x_cm) ** 2 + (node.y_cm - y_cm) ** 2
        ranked.append((distance_sq, int(node.physical_label)))
    return [node_id for _, node_id in sorted(ranked)[:limit]]


def _bbox_floor_point(bbox: CameraTrackBox) -> tuple[float, float]:
    return (bbox.x1 + bbox.x2) / 2.0, bbox.y2


def _normalize_image_point(
    x: float,
    y: float,
    frame_width: int,
    frame_height: int,
    calibration: CameraRoomCalibration,
) -> tuple[float, float]:
    if all(point.normalized for point in calibration.image_points):
        return x / max(frame_width, 1), y / max(frame_height, 1)
    return x, y


def _project_homography(calibration: CameraRoomCalibration, x: float, y: float) -> tuple[float, float]:
    image_points = [(point.x, point.y) for point in calibration.image_points]
    room_points = [(point.x_cm, point.y_cm) for point in calibration.room_points]
    matrix = _homography_matrix(image_points, room_points)
    denominator = matrix[2, 0] * x + matrix[2, 1] * y + matrix[2, 2]
    if abs(denominator) < 1e-9:
        return room_points[-1]
    projected_x = (matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2]) / denominator
    projected_y = (matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2]) / denominator
    return float(projected_x), float(projected_y)


def _homography_matrix(
    source_points: list[tuple[float, float]],
    target_points: list[tuple[float, float]],
) -> np.ndarray:
    rows: list[list[float]] = []
    values: list[float] = []
    for (x, y), (target_x, target_y) in zip(source_points, target_points):
        rows.append([x, y, 1.0, 0.0, 0.0, 0.0, -x * target_x, -y * target_x])
        values.append(target_x)
        rows.append([0.0, 0.0, 0.0, x, y, 1.0, -x * target_y, -y * target_y])
        values.append(target_y)
    solution = np.linalg.solve(np.asarray(rows, dtype=float), np.asarray(values, dtype=float))
    return np.asarray(
        [
            [solution[0], solution[1], solution[2]],
            [solution[3], solution[4], solution[5]],
            [solution[6], solution[7], 1.0],
        ],
        dtype=float,
    )


def _clamp_projection(camera_id: int, x_cm: float, y_cm: float, source: str) -> CameraRoomProjectionOut:
    room = load_rf_room_layout().room
    clamped_x = max(0.0, min(room.width_cm, x_cm))
    clamped_y = max(0.0, min(room.depth_cm, y_cm))
    clamped = abs(clamped_x - x_cm) > 0.01 or abs(clamped_y - y_cm) > 0.01
    return CameraRoomProjectionOut(
        camera_id=camera_id,
        x_cm=round(clamped_x, 1),
        y_cm=round(clamped_y, 1),
        z_cm=0.0,
        confidence=0.55 if source == "auto_full_frame" else 0.9,
        source=source,
        clamped=clamped,
        related_nodes=related_nodes_for_point(clamped_x, clamped_y),
    )
