from typing import List, Optional
import asyncio
import logging
import os
import threading
import time
from urllib.parse import quote

import cv2

from cctv_ai.opencv_capture import open_video_capture
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.db import get_session
from app.dependencies import get_current_user, get_current_user_allow_query
from app.network_policy import validate_camera_endpoint_url, validate_camera_host, validate_camera_stream_source
from app.permissions import check_permission, user_camera_permission_sync
from app.processor_media import (
    get_processor_media_base_urls,
    get_processor_direct_media_headers,
    get_processor_media_headers,
    is_processor_effectively_online,
)
from app.security import decrypt_secret
from app.schemas.cameras import (
    CameraEndpointInfo,
    CameraOut,
    CameraPermissionOut,
    CameraStreamInfoOut,
    CameraStreamSourceOut,
)
from app.services.onvif import (
    endpoint_has_onvif,
    endpoint_kinds,
    load_device_metadata,
    primary_stream_url,
    redact_url_credentials,
    read_ptz_capabilities,
)

router = APIRouter(prefix="/cameras", tags=["cameras"])
log = logging.getLogger("app.activity")
_LIVE_STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Accel-Buffering": "no",
}
_LIVE_PROXY_READ_CHUNK_SIZE = 64 * 1024
_LIVE_PROXY_MAX_BUFFER_SIZE = 4 * 1024 * 1024
_DIRECT_OPEN_TIMEOUT_SECONDS = 3.0
_DIRECT_READ_TIMEOUT_SECONDS = 2.0
_MAX_PROCESSOR_SNAPSHOT_BYTES = 8 * 1024 * 1024


def _append_bounded_bytes(payload: bytearray, chunk: bytes, *, max_bytes: int) -> None:
    payload.extend(chunk)
    if len(payload) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Processor snapshot is too large",
        )


class _DirectMjpegReader:
    """Keep only the latest direct-camera JPEG frame for low-latency MJPEG."""

    def __init__(self, cap: cv2.VideoCapture):
        self._cap = cap
        self._condition = threading.Condition()
        self._running = False
        self._thread: threading.Thread | None = None
        self._seq = 0
        self._frame: bytes | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._running = False
            self._condition.notify_all()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._cap.release()

    @property
    def running(self) -> bool:
        return self._running

    def latest_after(self, last_seq: int, timeout: float) -> tuple[int, bytes | None]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._running and self._seq == last_seq:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
            if self._seq == last_seq:
                return last_seq, None
            return self._seq, self._frame

    def _capture_loop(self) -> None:
        failures = 0
        encode_opts = [int(cv2.IMWRITE_JPEG_QUALITY), 82]
        while self._running:
            ok = self._cap.grab()
            if not ok:
                failures += 1
                if failures >= 30:
                    break
                time.sleep(0.05)
                continue
            ok, frame = self._cap.retrieve()
            if not ok or frame is None:
                failures += 1
                if failures >= 30:
                    break
                time.sleep(0.01)
                continue
            failures = 0
            ok, buf = cv2.imencode(".jpg", frame, encode_opts)
            if not ok:
                continue
            with self._condition:
                self._frame = buf.tobytes()
                self._seq += 1
                self._condition.notify_all()
        with self._condition:
            self._running = False
            self._condition.notify_all()


_DIRECT_READERS_LOCK = threading.Lock()
_DIRECT_READERS: dict[str, tuple[_DirectMjpegReader, int]] = {}


def _direct_reader_key(source: str | int) -> str:
    return f"{type(source).__name__}:{source}"


async def _acquire_direct_reader(camera: models.Camera) -> tuple[str, str | int, _DirectMjpegReader]:
    errors: list[str] = []
    for source in _direct_camera_source_candidates(camera):
        key = _direct_reader_key(source)
        with _DIRECT_READERS_LOCK:
            existing = _DIRECT_READERS.get(key)
            if existing is not None and existing[0].running:
                _DIRECT_READERS[key] = (existing[0], existing[1] + 1)
                return key, source, existing[0]
            if existing is not None:
                _DIRECT_READERS.pop(key, None)
        try:
            cap = await _open_direct_capture_checked(source)
        except Exception as exc:
            errors.append(f"{source}: {exc}")
            continue
        reader = _DirectMjpegReader(cap)
        reader.start()
        with _DIRECT_READERS_LOCK:
            existing = _DIRECT_READERS.get(key)
            if existing is not None and existing[0].running:
                reader.stop()
                _DIRECT_READERS[key] = (existing[0], existing[1] + 1)
                return key, source, existing[0]
            _DIRECT_READERS[key] = (reader, 1)
        return key, source, reader
    raise RuntimeError("; ".join(errors) or "camera stream source is not configured")


async def _release_direct_reader(key: str) -> None:
    reader: _DirectMjpegReader | None = None
    with _DIRECT_READERS_LOCK:
        existing = _DIRECT_READERS.get(key)
        if existing is None:
            return
        current_reader, refs = existing
        refs -= 1
        if refs > 0 and current_reader.running:
            _DIRECT_READERS[key] = (current_reader, refs)
            return
        _DIRECT_READERS.pop(key, None)
        reader = current_reader
    if reader is not None:
        await asyncio.to_thread(reader.stop)


async def _proxy_processor_camera_stream(
    proc: models.Processor,
    camera_id: int,
    overlay: bool,
    max_fps: float,
    request: Request,
) -> StreamingResponse:
    errors: list[str] = []
    for base_url in get_processor_media_base_urls(proc):
        try:
            return await _proxy_processor_camera_stream_url(
                base_url,
                proc,
                camera_id,
                overlay,
                max_fps,
                request,
            )
        except Exception as exc:
            errors.append(f"{base_url}: {exc!r}")
    raise RuntimeError("; ".join(errors) or "processor media endpoint is unknown")


async def _proxy_processor_camera_stream_url(
    base_url: str,
    proc: models.Processor,
    camera_id: int,
    overlay: bool,
    max_fps: float,
    request: Request,
) -> StreamingResponse:
    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=1.0, read=None, write=5.0, pool=5.0))
    stream_cm = client.stream(
        "GET",
        f"{base_url}/cameras/{camera_id}/stream.mjpeg",
        headers=get_processor_media_headers(proc),
        params={"overlay": "1" if overlay else "0", "max_fps": f"{max_fps:.2f}"},
    )
    upstream = await stream_cm.__aenter__()
    if upstream.status_code >= 400:
        body = await upstream.aread()
        await stream_cm.__aexit__(None, None, None)
        await client.aclose()
        raise RuntimeError(body.decode("utf-8", "replace") or f"processor media status {upstream.status_code}")

    latest_frames: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=1)

    def put_latest_frame(frame: bytes | None) -> None:
        if latest_frames.full():
            try:
                latest_frames.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            latest_frames.put_nowait(frame)
        except asyncio.QueueFull:
            pass

    async def read_upstream() -> None:
        buffer = bytearray()
        try:
            try:
                async for chunk in upstream.aiter_raw(chunk_size=_LIVE_PROXY_READ_CHUNK_SIZE):
                    if not chunk:
                        continue
                    buffer.extend(chunk)
                    while True:
                        start = buffer.find(b"\xff\xd8")
                        if start < 0:
                            if len(buffer) > 1024:
                                del buffer[:-128]
                            break
                        end = buffer.find(b"\xff\xd9", start + 2)
                        if end < 0:
                            if start > 0:
                                del buffer[:start]
                            if len(buffer) > _LIVE_PROXY_MAX_BUFFER_SIZE:
                                del buffer[:-1024]
                            break
                        frame = bytes(buffer[start : end + 2])
                        del buffer[: end + 2]
                        put_latest_frame(frame)
            except (httpx.HTTPError, asyncio.TimeoutError) as exc:
                log.warning(
                    "camera.stream.processor_upstream_interrupted camera=%s processor=%s base_url=%s reason=%r",
                    camera_id,
                    proc.processor_id,
                    base_url,
                    exc,
                )
        finally:
            put_latest_frame(None)

    async def gen():
        reader = asyncio.create_task(read_upstream())
        try:
            while True:
                frame = await latest_frames.get()
                if frame is None or await request.is_disconnected():
                    break
                header = (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(frame)}\r\n".encode("ascii")
                    + f"X-CCTV-Proxy-At: {time.time():.6f}\r\n\r\n".encode("ascii")
                )
                yield header + frame + b"\r\n"
        finally:
            reader.cancel()
            try:
                await reader
            except asyncio.CancelledError:
                pass
            await stream_cm.__aexit__(None, None, None)
            await client.aclose()

    return StreamingResponse(
        gen(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "multipart/x-mixed-replace; boundary=frame"),
        headers=_LIVE_STREAM_HEADERS,
    )


async def _online_processor_for_camera(
    session: AsyncSession,
    camera_id: int,
) -> models.Processor | None:
    assignment_result = await session.execute(
        select(models.ProcessorCameraAssignment, models.Processor)
        .join(models.Processor, models.Processor.processor_id == models.ProcessorCameraAssignment.processor_id)
        .where(
            models.ProcessorCameraAssignment.camera_id == camera_id,
            models.Processor.status == "online",
        )
    )
    for row in assignment_result.all():
        processor = row[1]
        if is_processor_effectively_online(processor):
            return processor
    return None


def _camera_proxy_stream_url(camera_id: int, annotate: bool, max_fps: float) -> str:
    return f"/cameras/{camera_id}/stream?annotate={'true' if annotate else 'false'}&max_fps={max_fps:.2f}"


def _processor_direct_stream_sources(
    proc: models.Processor,
    camera_id: int,
    overlay: bool,
    max_fps: float,
) -> list[CameraStreamSourceOut]:
    path = f"/cameras/{camera_id}/stream.mjpeg"
    headers = get_processor_direct_media_headers(proc, path=path)
    sources: list[CameraStreamSourceOut] = []
    for base_url in get_processor_media_base_urls(proc):
        sources.append(
            CameraStreamSourceOut(
                kind="processor_direct",
                url=(
                    f"{base_url}{path}"
                    f"?overlay={'1' if overlay else '0'}&max_fps={max_fps:.2f}"
                ),
                headers=headers,
            )
        )
    return sources


async def _proxy_processor_camera_snapshot(
    proc: models.Processor,
    camera_id: int,
    overlay: bool,
) -> Response:
    errors: list[str] = []
    for base_url in get_processor_media_base_urls(proc):
        try:
            return await _proxy_processor_camera_snapshot_url(
                base_url,
                proc,
                camera_id,
                overlay,
            )
        except HTTPException:
            raise
        except Exception as exc:
            errors.append(f"{base_url}: {exc!r}")
    raise RuntimeError("; ".join(errors) or "processor media endpoint is unknown")


async def _proxy_processor_camera_snapshot_url(
    base_url: str,
    proc: models.Processor,
    camera_id: int,
    overlay: bool,
) -> Response:
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=1.0, read=4, write=4, pool=4)) as client:
        async with client.stream(
            "GET",
            f"{base_url}/cameras/{camera_id}/snapshot.jpg",
            headers=get_processor_media_headers(proc),
            params={"overlay": "1" if overlay else "0"},
        ) as upstream:
            if upstream.status_code >= 400:
                error_body = bytearray()
                async for chunk in upstream.aiter_bytes():
                    if chunk:
                        error_body.extend(chunk)
                    if len(error_body) >= 4096:
                        break
                detail = bytes(error_body[:4096]).decode("utf-8", errors="replace").strip()
                raise RuntimeError(detail or f"processor media status {upstream.status_code}")

            content_length = upstream.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > _MAX_PROCESSOR_SNAPSHOT_BYTES:
                        raise HTTPException(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail="Processor snapshot is too large",
                        )
                except ValueError:
                    pass

            payload = bytearray()
            async for chunk in upstream.aiter_bytes():
                if not chunk:
                    continue
                _append_bounded_bytes(
                    payload,
                    chunk,
                    max_bytes=_MAX_PROCESSOR_SNAPSHOT_BYTES,
                )
            return Response(
                content=bytes(payload),
                status_code=upstream.status_code,
                media_type=upstream.headers.get("content-type", "image/jpeg"),
                headers={"Cache-Control": "no-store"},
            )


def _inject_credentials(url: str, username: str | None, password: str | None) -> str:
    if not username or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" in rest:
        return url
    host_part, sep, path_part = rest.partition("/")
    user = quote(username, safe="")
    pwd = quote(password or "", safe="")
    return f"{scheme}://{user}:{pwd}@{host_part}{sep}{path_part}"


def _with_rtsp_fallbacks(url: str) -> list[str]:
    values = [url]
    lowered = url.lower()
    if lowered.endswith("/stream1"):
        values.append(url[:-1] + "2")
    elif lowered.endswith("/stream2"):
        values.append(url[:-1] + "1")
    return values


def _append_unique(items: list[str | int], value: str | int) -> None:
    if value not in items:
        items.append(value)


def _decrypt_endpoint_password(endpoint: models.CameraEndpoint) -> str | None:
    if not endpoint.password_secret:
        return None
    try:
        return decrypt_secret(endpoint.password_secret)
    except Exception:
        return None


def _direct_camera_source_candidates(camera: models.Camera) -> list[str | int]:
    weighted_rtsp: list[tuple[int, list[str]]] = []
    weighted_http: list[tuple[int, str]] = []
    for endpoint in camera.endpoints:
        kind = endpoint.endpoint_kind
        url = endpoint.endpoint_url
        if not kind or not url:
            continue
        weight = 100 if endpoint.is_primary else 0
        if kind == "rtsp":
            weight += 100
        elif kind == "http":
            weight += 50
        else:
            continue
        try:
            url = validate_camera_endpoint_url(kind, url)
        except ValueError:
            continue
        if not url:
            continue
        resolved_url = _inject_credentials(
            url,
            endpoint.username,
            _decrypt_endpoint_password(endpoint),
        )
        if kind == "rtsp":
            weighted_rtsp.append((weight, _with_rtsp_fallbacks(resolved_url)))
        else:
            weighted_http.append((weight, resolved_url))

    candidates: list[str | int] = []
    if weighted_rtsp:
        weighted_rtsp.sort(reverse=True)
        for _weight, urls in weighted_rtsp:
            for url in urls:
                _append_unique(candidates, url)
    if weighted_http:
        weighted_http.sort(reverse=True)
        for _weight, url in weighted_http:
            _append_unique(candidates, url)

    if camera.stream_url:
        try:
            stream_url = validate_camera_stream_source(camera.stream_url)
        except ValueError:
            stream_url = None
        if stream_url and stream_url.isdigit():
            _append_unique(candidates, int(stream_url))
        elif stream_url and stream_url.lower().startswith("rtsp://"):
            for url in _with_rtsp_fallbacks(stream_url):
                _append_unique(candidates, url)
        elif stream_url:
            _append_unique(candidates, stream_url)
    if camera.ip_address:
        try:
            ip_address = validate_camera_host(camera.ip_address)
        except ValueError:
            ip_address = None
        if not ip_address:
            return candidates
        for url in (
            f"rtsp://{ip_address}:554/stream",
            f"rtsp://{ip_address}:554/stream1",
            f"rtsp://{ip_address}:554/stream2",
        ):
            _append_unique(candidates, url)
    return candidates


def _resolve_direct_camera_source(camera: models.Camera) -> str | int | None:
    candidates = _direct_camera_source_candidates(camera)
    return candidates[0] if candidates else None


async def _open_first_direct_capture_checked(camera: models.Camera) -> tuple[cv2.VideoCapture, str | int]:
    errors: list[str] = []
    for source in _direct_camera_source_candidates(camera):
        try:
            cap = await _open_direct_capture_checked(source)
            return cap, source
        except Exception as exc:
            errors.append(f"{source}: {exc}")
    raise RuntimeError("; ".join(errors) or "camera stream source is not configured")


def _open_direct_capture(source: str | int) -> cv2.VideoCapture:
    return open_video_capture(
        source,
        open_timeout_ms=2500,
        read_timeout_ms=1500,
        buffer_size=1,
    )


def _read_direct_jpeg(cap: cv2.VideoCapture) -> bytes | None:
    ok, frame = cap.read()
    if not ok or frame is None:
        return None
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok:
        return None
    return buf.tobytes()


async def _open_direct_capture_checked(source: str | int) -> cv2.VideoCapture:
    try:
        cap = await asyncio.wait_for(
            asyncio.to_thread(_open_direct_capture, source),
            timeout=_DIRECT_OPEN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise RuntimeError("camera stream open timeout") from exc
    except Exception as exc:
        raise RuntimeError(f"camera stream open failed: {exc}") from exc
    if not cap.isOpened():
        cap.release()
        raise RuntimeError("cannot open camera stream directly")
    return cap


async def _read_direct_jpeg_checked(cap: cv2.VideoCapture) -> bytes | None:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_read_direct_jpeg, cap),
            timeout=_DIRECT_READ_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise RuntimeError("camera frame read timeout") from exc


async def _snapshot_direct_camera(camera: models.Camera) -> Response:
    key, _source, reader = await _acquire_direct_reader(camera)
    try:
        frame = None
        last_seq = 0
        for _ in range(10):
            last_seq, frame = await asyncio.to_thread(reader.latest_after, last_seq, 0.2)
            if frame is not None:
                break
    finally:
        await _release_direct_reader(key)
    if frame is None:
        raise RuntimeError("cannot read camera frame directly")
    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


async def _stream_direct_camera(
    camera: models.Camera,
    max_fps: float = 60.0,
    max_session_seconds: float | None = None,
    request: Request | None = None,
) -> StreamingResponse:
    key, _source, reader = await _acquire_direct_reader(camera)

    async def gen():
        frame_interval = 1.0 / min(max(max_fps, 1.0), 60.0)
        last_sent_at = 0.0
        last_seq = 0
        idle_misses = 0
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        try:
            while True:
                if request is not None and await request.is_disconnected():
                    break
                if max_session_seconds is not None and loop.time() - started_at >= max_session_seconds:
                    break
                next_seq, frame = await asyncio.to_thread(
                    reader.latest_after,
                    last_seq,
                    max(_DIRECT_READ_TIMEOUT_SECONDS, frame_interval * 2),
                )
                if frame is None:
                    idle_misses += 1
                    if idle_misses >= 5:
                        break
                    await asyncio.sleep(0.02)
                    continue
                last_seq = next_seq
                idle_misses = 0

                if last_sent_at:
                    remaining = frame_interval - (loop.time() - last_sent_at)
                    if remaining > 0:
                        await asyncio.sleep(min(remaining, 0.03))
                        newer_seq, newer_frame = await asyncio.to_thread(
                            reader.latest_after,
                            last_seq,
                            0.001,
                        )
                        if newer_frame is not None:
                            last_seq = newer_seq
                            frame = newer_frame

                header = (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(frame)}\r\n".encode("ascii")
                    + f"X-CCTV-Sent-At: {time.time():.6f}\r\n".encode("ascii")
                    + b"\r\n"
                )
                yield header + frame + b"\r\n"
                last_sent_at = loop.time()
                await asyncio.sleep(0)
        finally:
            await _release_direct_reader(key)

    return StreamingResponse(
        gen(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers=_LIVE_STREAM_HEADERS,
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
    camera_ids = [camera.camera_id for camera in cameras]
    fps_by_camera: dict[int, int] = {}
    if camera_ids:
        stream_result = await session.execute(
            select(models.VideoStream.camera_id, models.VideoStream.fps)
            .where(
                models.VideoStream.camera_id.in_(camera_ids),
                models.VideoStream.enabled.is_(True),
                models.VideoStream.fps.is_not(None),
            )
            .order_by(models.VideoStream.video_stream_id)
        )
        for camera_id, fps in stream_result.all():
            if camera_id not in fps_by_camera and fps is not None:
                fps_by_camera[int(camera_id)] = int(fps)

    permission = user_camera_permission_sync(current_user)
    if permission is None:
        return []

    return [
        CameraOut(
            camera_id=camera.camera_id,
            name=camera.name,
            location=camera.location,
            ip_address=camera.ip_address,
            stream_url=redact_url_credentials(primary_stream_url(camera.stream_url, camera.endpoints)),
            fps=fps_by_camera.get(camera.camera_id),
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
                    endpoint_url=redact_url_credentials(endpoint.endpoint_url) or endpoint.endpoint_url,
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


@router.get("/{camera_id}/stream-source", response_model=CameraStreamInfoOut)
async def stream_camera_source(
    camera_id: int,
    annotate: bool = True,
    max_fps: float = Query(60.0, ge=1.0, le=60.0),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> CameraStreamInfoOut:
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
    if not check_permission(permission, "view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to this camera")

    sources: list[CameraStreamSourceOut] = []
    processor = await _online_processor_for_camera(session, camera_id)
    if processor is not None:
        sources.extend(_processor_direct_stream_sources(processor, camera_id, annotate, max_fps))
    sources.append(
        CameraStreamSourceOut(
            kind="backend_proxy",
            url=_camera_proxy_stream_url(camera_id, annotate, max_fps),
            headers={},
        )
    )
    return CameraStreamInfoOut(camera_id=camera_id, sources=sources)


@router.get("/{camera_id}/stream")
async def stream_camera(
    camera_id: int,
    request: Request,
    annotate: bool = True,
    max_fps: float = Query(60.0, ge=1.0, le=60.0),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user_allow_query),
):
    result = await session.execute(
        select(models.Camera)
        .where(models.Camera.camera_id == camera_id)
        .options(selectinload(models.Camera.endpoints))
    )
    camera = result.scalar_one_or_none()
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
        )
    )
    assignment_rows = assignment_result.all()
    assignment_row = None
    for row in assignment_rows:
        if is_processor_effectively_online(row[1]):
            assignment_row = row
            break
    if assignment_row is None:
        try:
            return await _stream_direct_camera(
                camera,
                max_fps=max_fps,
                max_session_seconds=None,
                request=request,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Live stream is unavailable: no online processor and direct stream failed ({exc})",
            ) from exc

    _, processor = assignment_row
    try:
        return await _proxy_processor_camera_stream(
            processor,
            camera_id,
            overlay=annotate,
            max_fps=max_fps,
            request=request,
        )
    except Exception as exc:
        log.warning(
            "camera.stream.processor_proxy_failed camera=%s processor=%s reason=%s",
            camera_id,
            processor.processor_id,
            repr(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Live stream is unavailable: processor proxy failed ({exc!r})",
        ) from exc


@router.get("/{camera_id}/snapshot")
async def snapshot_camera(
    camera_id: int,
    annotate: bool = False,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user_allow_query),
):
    result = await session.execute(
        select(models.Camera)
        .where(models.Camera.camera_id == camera_id)
        .options(selectinload(models.Camera.endpoints))
    )
    camera = result.scalar_one_or_none()
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
    )
    assignment_row = None
    for row in assignment_result.all():
        if is_processor_effectively_online(row[1]):
            assignment_row = row
            break
    if assignment_row is None:
        try:
            return await _snapshot_direct_camera(camera)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Live snapshot is unavailable: no online processor and direct frame failed ({exc})",
            ) from exc

    _, processor = assignment_row
    try:
        return await _proxy_processor_camera_snapshot(processor, camera_id, overlay=annotate)
    except Exception as exc:
        log.warning(
            "camera.snapshot.processor_proxy_failed camera=%s processor=%s reason=%s",
            camera_id,
            processor.processor_id,
            repr(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Live snapshot is unavailable: processor proxy failed ({exc!r})",
        ) from exc
