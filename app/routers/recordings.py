import os
from pathlib import Path
import re
from typing import List, Optional
import mimetypes
import asyncio
import shutil
import subprocess

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
import cv2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user, get_current_user_allow_query
from app.permissions import user_camera_permission, check_permission
from app.schemas.recordings import RecordingOut, LocalRecordingOut

router = APIRouter(prefix="/recordings", tags=["recordings"])
FFMPEG_BIN = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or r"C:\ffmpeg-essentials\ffmpeg.exe"
CACHE_DIR = Path("recordings_cache")
CACHE_DIR.mkdir(exist_ok=True)


@router.get("", response_model=List[RecordingOut])
async def list_recordings(
    camera_id: Optional[int] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> List[RecordingOut]:
    stmt = (
        select(models.RecordingFile, models.VideoStream.camera_id)
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .order_by(models.RecordingFile.started_at.desc())
        .limit(limit)
    )
    if camera_id:
        stmt = stmt.where(models.VideoStream.camera_id == camera_id)

    res = await session.execute(stmt)
    rows = res.all()

    output: List[RecordingOut] = []
    for recording, cam_id in rows:
        perm = await user_camera_permission(session, current_user.user_id, cam_id)
        if not check_permission(perm, "view") and current_user.role_id != 1:
            continue
        output.append(
            RecordingOut(
                recording_file_id=recording.recording_file_id,
                camera_id=cam_id,
                video_stream_id=recording.video_stream_id,
                file_kind=recording.file_kind,
                file_path=recording.file_path,
                started_at=str(recording.started_at),
                ended_at=str(recording.ended_at) if recording.ended_at else None,
                duration_seconds=float(recording.duration_seconds) if recording.duration_seconds else None,
                file_size_bytes=int(recording.file_size_bytes) if recording.file_size_bytes else None,
                checksum=recording.checksum,
            )
        )

    return output


@router.get("/files", response_model=List[LocalRecordingOut])
async def list_local_recordings(
    current_user: models.User = Depends(get_current_user),
    camera_id: Optional[int] = Query(default=None),
) -> List[LocalRecordingOut]:
    """
    List video files from local recordings directory (recordings/).
    This is filesystem-only (detector output), not DB-linked.
    """
    base = Path("recordings")
    if not base.exists():
        return []

    items: List[LocalRecordingOut] = []
    for entry in sorted(base.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = entry.stat()
        cam_id: Optional[int] = None
        m = re.search(r"cam(\\d+)", entry.name)
        if m:
            try:
                cam_id = int(m.group(1))
            except ValueError:
                cam_id = None
        if camera_id and cam_id and cam_id != camera_id:
            continue
        items.append(
            LocalRecordingOut(
                name=entry.name,
                url=f"/recordings/static/{entry.name}",
                size_bytes=stat.st_size,
                modified_at=str(
                    __import__("datetime").datetime.fromtimestamp(stat.st_mtime)
                ),
                camera_id=cam_id,
            )
        )
    return items


def _range_stream(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024):
    with path.open("rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/file/{recording_id}")
async def download_recording(
    recording_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user_allow_query),
):
    res = await session.execute(
        select(models.RecordingFile, models.VideoStream.camera_id)
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .where(models.RecordingFile.recording_file_id == recording_id)
    )
    row = res.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    recording, cam_id = row
    perm = await user_camera_permission(session, current_user.user_id, cam_id)
    if not check_permission(perm, "view") and current_user.role_id != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    path = Path(recording.file_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing")

    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "video/mp4"

    # If AVI/MJPG: transcode to MP4 with ffmpeg once and cache
    if mime == "video/avi" and FFMPEG_BIN:
        cached = CACHE_DIR / f"{recording.recording_file_id}.mp4"
        need_build = True
        if cached.exists():
            try:
                if cached.stat().st_mtime >= path.stat().st_mtime:
                    need_build = False
            except Exception:
                need_build = True
        if need_build:
            cmd = [
                FFMPEG_BIN,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(path),
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-tune",
                "zerolatency",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                str(cached),
            ]
            proc = subprocess.run(cmd, capture_output=True)
            if proc.returncode != 0 or not cached.exists():
                # fall back to MJPEG streaming below
                cached = None
        if cached and cached.exists():
            path = cached
            mime = "video/mp4"

    file_size = path.stat().st_size

    # if avi/mjpg — transcode to mp4 via ffmpeg (no Range support here)
    if mime == "video/avi" and FFMPEG_BIN:
        async def _transcode():
            cmd = [
                FFMPEG_BIN,
                "-hide_banner",
                "-loglevel", "error",
                "-i", str(path),
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-tune", "zerolatency",
                "-pix_fmt", "yuv420p",
                "-an",
                "-movflags", "+faststart",
                "-f", "mp4",
                "pipe:1",
            ]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
            try:
                while True:
                    chunk = await proc.stdout.read(1024 * 64)
                    if not chunk:
                        break
                    yield chunk
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()

        return StreamingResponse(_transcode(), media_type="video/mp4")

    file_size = path.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")
    if range_header:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else file_size - 1
            end = min(end, file_size - 1)
            if start >= file_size:
                raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Range not satisfiable")
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1),
            }
            return StreamingResponse(_range_stream(path, start, end), status_code=206, media_type=mime, headers=headers)
    return FileResponse(
        path,
        media_type=mime,
        filename=path.name,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            # Safari иногда требует Content-Disposition для inline
            "Content-Disposition": f'inline; filename="{path.name}"',
        },
    )


@router.get("/file/{recording_id}/mjpeg")
async def stream_recording_mjpeg(
    recording_id: int,
    fps: float | None = Query(default=None, ge=1, le=30, description="Кадров в секунду (по умолчанию из файла)"),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user_allow_query),
):
    res = await session.execute(
        select(models.RecordingFile, models.VideoStream.camera_id)
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .where(models.RecordingFile.recording_file_id == recording_id)
    )
    row = res.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    recording, cam_id = row
    perm = await user_camera_permission(session, current_user.user_id, cam_id)
    if not check_permission(perm, "view") and current_user.role_id != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    path = Path(recording.file_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Cannot open video")
    try:
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
        delay = 1.0 / (fps or src_fps or 10.0)

        async def gen():
            try:
                while True:
                    ok, frame = await asyncio.to_thread(cap.read)
                    if not ok or frame is None:
                        break
                    ok, buf = cv2.imencode(".jpg", frame)
                    if not ok:
                        continue
                    chunk = buf.tobytes()
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + chunk + b"\r\n"
                    await asyncio.sleep(delay)
            finally:
                cap.release()

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")
    except Exception:
        cap.release()
        raise


@router.get("/snapshot/{recording_id}")
async def snapshot_recording(
    recording_id: int,
    ts: float | None = Query(default=None, description="Timestamp in seconds"),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user_allow_query),
):
    res = await session.execute(
        select(models.RecordingFile, models.VideoStream.camera_id)
        .join(models.VideoStream, models.VideoStream.video_stream_id == models.RecordingFile.video_stream_id)
        .where(models.RecordingFile.recording_file_id == recording_id)
    )
    row = res.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    recording, cam_id = row
    perm = await user_camera_permission(session, current_user.user_id, cam_id)
    if not check_permission(perm, "view") and current_user.role_id != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    path = Path(recording.file_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Cannot open video")
    try:
        if ts is not None:
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
        else:
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            if frames and frames > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frames / 2)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Cannot read frame")
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Encode failed")
        return Response(content=buf.tobytes(), media_type="image/jpeg")
    finally:
        cap.release()
