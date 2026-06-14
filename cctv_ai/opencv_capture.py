from __future__ import annotations

import os
import threading

import cv2


_FFMPEG_OPTIONS_LOCK = threading.Lock()
_RTSP_FFMPEG_OPTIONS = (
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0|buffer_size;102400"
    "|analyzeduration;0|probesize;32768|flush_packets;1"
)


def _capture_open_params(open_timeout_ms: int, read_timeout_ms: int) -> list[int]:
    params: list[int] = []
    for name, value in (
        ("CAP_PROP_OPEN_TIMEOUT_MSEC", open_timeout_ms),
        ("CAP_PROP_READ_TIMEOUT_MSEC", read_timeout_ms),
    ):
        prop = getattr(cv2, name, None)
        if prop is not None and value > 0:
            params.extend((int(prop), int(value)))
    return params


def _open_rtsp_capture(source: str, open_timeout_ms: int, read_timeout_ms: int) -> cv2.VideoCapture:
    params = _capture_open_params(open_timeout_ms, read_timeout_ms)
    with _FFMPEG_OPTIONS_LOCK:
        previous_options = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS")
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = _RTSP_FFMPEG_OPTIONS
        try:
            try:
                return cv2.VideoCapture(source, cv2.CAP_FFMPEG, params)
            except (TypeError, cv2.error):
                return cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        finally:
            if previous_options is None:
                os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)
            else:
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = previous_options


def open_video_capture(
    source: str | int,
    *,
    open_timeout_ms: int = 5000,
    read_timeout_ms: int = 5000,
    buffer_size: int = 1,
) -> cv2.VideoCapture:
    if isinstance(source, str) and source.lower().startswith("rtsp://"):
        capture = _open_rtsp_capture(source, open_timeout_ms, read_timeout_ms)
    else:
        capture = cv2.VideoCapture(source)

    buffer_property = getattr(cv2, "CAP_PROP_BUFFERSIZE", None)
    if buffer_property is not None and buffer_size > 0:
        try:
            capture.set(buffer_property, int(buffer_size))
        except Exception:
            pass
    return capture
