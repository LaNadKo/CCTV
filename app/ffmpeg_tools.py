from __future__ import annotations

import os
import shutil
from pathlib import Path


def _existing_executable(candidate: str | None) -> str | None:
    if not candidate:
        return None
    found = shutil.which(candidate)
    if found:
        return found
    path = Path(candidate)
    if path.exists():
        return str(path)
    return None


def ffmpeg_bin() -> str | None:
    configured = _existing_executable(os.environ.get("FFMPEG_BIN"))
    if configured:
        return configured

    bundled = _existing_executable("ffmpeg")
    if bundled:
        return bundled

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

    return _existing_executable(r"C:\ffmpeg-essentials\ffmpeg.exe")


def ffprobe_bin(ffmpeg_path: str | None = None) -> str | None:
    configured = _existing_executable(os.environ.get("FFPROBE_BIN"))
    if configured:
        return configured

    found = _existing_executable("ffprobe")
    if found:
        return found

    candidates = []
    if ffmpeg_path:
        ffmpeg_file = Path(ffmpeg_path)
        candidates.extend(
            [
                str(ffmpeg_file.with_name("ffprobe.exe")),
                str(ffmpeg_file.with_name("ffprobe")),
            ]
        )
    candidates.append(r"C:\ffmpeg-essentials\ffprobe.exe")

    for candidate in candidates:
        found = _existing_executable(candidate)
        if found:
            return found
    return None
