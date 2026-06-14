"""Lightweight HTTP server exposing processor-owned media."""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from cctv_ai.media_auth import verify_scoped_media_token
from processor.embedding_service import EmbeddingService
from processor.paths import RECORDINGS_DIR, SNAPSHOTS_DIR, ensure_media_dirs

if TYPE_CHECKING:
    from processor.main import ProcessorService


log = logging.getLogger(__name__)
MAX_EMBEDDING_IMAGE_BYTES = 8 * 1024 * 1024
MAX_EMBEDDING_IMAGE_PIXELS = 12_000_000
MEDIA_AUTH_FAILURE_LIMIT = 20
MEDIA_AUTH_FAILURE_WINDOW_SECONDS = 60.0


def _embedding_image_pixel_count(image: np.ndarray) -> int:
    if image.ndim < 2:
        return 0
    return int(image.shape[0]) * int(image.shape[1])


def _encoded_image_pixel_count(payload: bytes) -> int:
    try:
        with Image.open(BytesIO(payload)) as image:
            width, height = image.size
    except Image.DecompressionBombError:
        return MAX_EMBEDDING_IMAGE_PIXELS + 1
    except (UnidentifiedImageError, OSError, ValueError):
        return 0
    return max(0, int(width)) * max(0, int(height))


def _decode_embedding_image(payload: bytes) -> np.ndarray:
    encoded_pixels = _encoded_image_pixel_count(payload)
    if encoded_pixels <= 0:
        raise ValueError("Invalid image")
    if encoded_pixels > MAX_EMBEDDING_IMAGE_PIXELS:
        raise OverflowError("Decoded image is too large")
    image_arr = np.frombuffer(payload, np.uint8)
    image = cv2.imdecode(image_arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Invalid image")
    if _embedding_image_pixel_count(image) > MAX_EMBEDDING_IMAGE_PIXELS:
        raise OverflowError("Decoded image is too large")
    return image


def _media_token_matches(expected: str, actual: str) -> bool:
    if not expected or not actual:
        return False
    return secrets.compare_digest(expected, actual)


class _AuthFailureLimiter:
    def __init__(self, *, limit: int, window_seconds: float):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1.0, float(window_seconds))
        self._lock = threading.Lock()
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def is_blocked(self, client_ip: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            attempts = self._attempts[client_ip]
            self._prune(attempts, current)
            return len(attempts) >= self.limit

    def record_failure(self, client_ip: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            attempts = self._attempts[client_ip]
            self._prune(attempts, current)
            attempts.append(current)
            if len(self._attempts) > 2048:
                self._evict_idle(current)
            return len(attempts) >= self.limit

    def clear(self, client_ip: str) -> None:
        with self._lock:
            self._attempts.pop(client_ip, None)

    def _prune(self, attempts: deque[float], now: float) -> None:
        while attempts and now - attempts[0] > self.window_seconds:
            attempts.popleft()

    def _evict_idle(self, now: float) -> None:
        stale = []
        for client_ip, attempts in self._attempts.items():
            self._prune(attempts, now)
            if not attempts:
                stale.append(client_ip)
        for client_ip in stale[:512]:
            self._attempts.pop(client_ip, None)


class _BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        request_handler_class,
        *,
        max_connections: int,
        socket_timeout: float,
    ):
        self._connection_slots = threading.BoundedSemaphore(max(1, int(max_connections)))
        self._socket_timeout = max(1.0, float(socket_timeout))
        super().__init__(server_address, request_handler_class)

    def get_request(self):
        request, client_address = super().get_request()
        request.settimeout(self._socket_timeout)
        return request, client_address

    def process_request(self, request, client_address) -> None:
        if not self._connection_slots.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Connection: close\r\n"
                    b"Content-Length: 0\r\n\r\n"
                )
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._connection_slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()


def _safe_join(root: Path, relative_path: str) -> Path:
    target = (root / unquote(relative_path.lstrip("/"))).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents and target != root_resolved:
        raise FileNotFoundError("Path escapes media root")
    return target


class _MediaRequestHandler(BaseHTTPRequestHandler):
    server_version = "CCTVProcessorMedia/1.0"

    @property
    def media_server(self) -> "ProcessorMediaServer":
        return self.server.media_server  # type: ignore[attr-defined]

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        log.debug("media.http " + format, *args)

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/health":
                self._send_json(200, {"ok": True})
                return

            if not self._authorized():
                self._send_auth_error()
                return

            if path == "/metrics":
                self._serve_metrics()
                return

            if path.startswith("/cameras/") and path.endswith("/snapshot.jpg"):
                self._serve_live_snapshot(path, parsed.query)
                return

            if path.startswith("/cameras/") and path.endswith("/embedding.json"):
                self._serve_live_embedding(path)
                return

            if path.startswith("/cameras/") and path.endswith("/stream.mjpeg"):
                self._serve_live_stream(path, parsed.query)
                return

            if path.startswith("/media/snapshots/"):
                rel = path[len("/media/snapshots/") :]
                self._serve_file(_safe_join(SNAPSHOTS_DIR, rel))
                return

            if path.startswith("/media/recordings-mjpeg/"):
                rel = path[len("/media/recordings-mjpeg/") :]
                self._serve_recording_mjpeg(_safe_join(RECORDINGS_DIR, rel), parsed.query)
                return

            if path.startswith("/media/recordings-snapshot/"):
                rel = path[len("/media/recordings-snapshot/") :]
                qs = parse_qs(parsed.query or "")
                ts_raw = qs.get("ts", [None])[0]
                ts = _parse_float(ts_raw, default=None) if ts_raw not in (None, "") else None
                max_width = _parse_int(qs.get("max_width", ["640"])[0], default=640, minimum=160, maximum=1920)
                quality = _parse_int(qs.get("quality", ["72"])[0], default=72, minimum=40, maximum=95)
                self._serve_recording_snapshot(_safe_join(RECORDINGS_DIR, rel), ts, max_width, quality)
                return

            if path.startswith("/media/recordings/"):
                rel = path[len("/media/recordings/") :]
                self._serve_file(_safe_join(RECORDINGS_DIR, rel))
                return

            self._send_json(404, {"detail": "Not found"})
        except FileNotFoundError:
            self._send_json(404, {"detail": "File missing"})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:
            log.exception("Processor media server request failed")
            try:
                self._send_json(500, {"detail": str(exc)})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path

            if not self._authorized():
                self._send_auth_error()
                return

            if path == "/embeddings/extract":
                self._extract_embedding()
                return

            self._send_json(404, {"detail": "Not found"})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:
            log.exception("Processor media server POST failed")
            try:
                self._send_json(500, {"detail": str(exc)})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    def _authorized(self) -> bool:
        expected = self.media_server.media_token
        if not expected:
            log.warning("Processor media request rejected because media token is not configured")
            return False
        client_ip = str(self.client_address[0]) if self.client_address else "unknown"
        if self.media_server.auth_failure_limiter.is_blocked(client_ip):
            self._auth_rate_limited = True
            return False
        actual = self.headers.get("X-Processor-Media-Token", "")
        request_path = urlparse(self.path).path
        if _media_token_matches(expected, actual) or verify_scoped_media_token(
            expected,
            actual,
            request_path,
        ):
            self.media_server.auth_failure_limiter.clear(client_ip)
            self._auth_rate_limited = False
            return True
        self._auth_rate_limited = self.media_server.auth_failure_limiter.record_failure(client_ip)
        return False

    def _send_auth_error(self) -> None:
        if getattr(self, "_auth_rate_limited", False):
            self._send_json(429, {"detail": "Too many authentication failures"})
            return
        self._send_json(403, {"detail": "Forbidden"})

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_metrics(self) -> None:
        cameras: dict[str, dict[str, str]] = {}
        bottleneck = "нет данных"
        for camera_id, worker in self.media_server.service.workers.items():
            value = worker.bottleneck_text()
            cameras[str(camera_id)] = {"bottleneck": value}
            if bottleneck == "нет данных" and value != "нет данных":
                bottleneck = value
        self._send_json(200, {"bottleneck": bottleneck, "cameras": cameras})

    def _extract_embedding(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except (TypeError, ValueError):
            self._send_json(400, {"detail": "Invalid Content-Length"})
            return
        if length <= 0:
            self._send_json(400, {"detail": "Empty request body"})
            return
        if length > MAX_EMBEDDING_IMAGE_BYTES:
            self._send_json(413, {"detail": "Image is too large"})
            return

        payload = self.rfile.read(length)
        try:
            image = _decode_embedding_image(payload)
        except ValueError:
            self._send_json(400, {"detail": "Invalid image"})
            return
        except OverflowError:
            self._send_json(413, {"detail": "Decoded image is too large"})
            return

        faces = self.media_server.embedding_service.extract(image)
        if not faces:
            self._send_json(400, {"detail": "No face found"})
            return

        best_face = max(
            faces,
            key=lambda face: max(0.0, float(face["box"][2] - face["box"][0]))
            * max(0.0, float(face["box"][3] - face["box"][1])),
        )
        embedding = np.asarray(best_face["embedding"], dtype=np.float32)
        self._send_json(
            200,
            {
                "embedding_b64": base64.b64encode(embedding.tobytes()).decode("ascii"),
                "embedding_len": int(embedding.size),
                "face_count": len(faces),
            },
        )

    def _serve_live_stream(self, path: str, query: str) -> None:
        match = re.match(r"^/cameras/(\d+)/stream\.mjpeg$", path)
        if not match:
            self._send_json(404, {"detail": "Not found"})
            return
        camera_id = int(match.group(1))
        worker = self.media_server.service.workers.get(camera_id)
        if worker is None:
            self._send_json(404, {"detail": "Camera worker not found"})
            return

        qs = parse_qs(query or "")
        overlay = qs.get("overlay", ["1"])[0].lower() not in {"0", "false", "no"}
        max_fps = _parse_float(qs.get("max_fps", ["20"])[0], default=20.0)
        frame_interval = 1.0 / min(max(max_fps, 1.0), 60.0)

        self.send_response(200)
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        last_sequence = 0
        last_sent_at = 0.0
        last_new_frame_at = 0.0
        try:
            while not self.media_server.stop_event.is_set():
                sequence, frame = worker.wait_for_stream_frame(
                    overlay=overlay,
                    after_sequence=last_sequence,
                    timeout=min(0.5, frame_interval),
                )
                now = time.monotonic()
                is_new_frame = frame is not None and sequence > last_sequence
                is_short_stall = (
                    frame is not None
                    and overlay
                    and last_sent_at > 0.0
                    and last_new_frame_at > 0.0
                    and now - last_sent_at >= frame_interval
                    and now - last_new_frame_at <= 0.75
                )
                if frame and (is_new_frame or is_short_stall):
                    now = time.monotonic()
                    if last_sent_at:
                        remaining = frame_interval - (now - last_sent_at)
                        if remaining > 0:
                            time.sleep(remaining)
                    header = (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(frame)}\r\n".encode("ascii")
                        + f"X-CCTV-Sent-At: {time.time():.6f}\r\n\r\n".encode("ascii")
                    )
                    self.wfile.write(header)
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                    if is_new_frame:
                        last_sequence = sequence
                        last_new_frame_at = time.monotonic()
                    last_sent_at = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            log.debug("media.live client disconnected camera=%s", camera_id)

    def _serve_live_snapshot(self, path: str, query: str) -> None:
        match = re.match(r"^/cameras/(\d+)/snapshot\.jpg$", path)
        if not match:
            self._send_json(404, {"detail": "Not found"})
            return
        camera_id = int(match.group(1))
        worker = self.media_server.service.workers.get(camera_id)
        if worker is None:
            self._send_json(404, {"detail": "Camera worker not found"})
            return

        qs = parse_qs(query or "")
        overlay = qs.get("overlay", ["1"])[0].lower() not in {"0", "false", "no"}
        deadline = time.monotonic() + 2.0
        frame = None
        while time.monotonic() < deadline and not self.media_server.stop_event.is_set():
            frame = worker.get_stream_frame(overlay=overlay)
            if frame:
                break
            time.sleep(0.03)
        if not frame:
            self._send_json(503, {"detail": "Live frame is not ready"})
            return

        self.send_response(200)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(frame)))
        self.end_headers()
        self.wfile.write(frame)

    def _serve_live_embedding(self, path: str) -> None:
        match = re.match(r"^/cameras/(\d+)/embedding\.json$", path)
        if not match:
            self._send_json(404, {"detail": "Not found"})
            return
        camera_id = int(match.group(1))
        worker = self.media_server.service.workers.get(camera_id)
        if worker is None:
            self._send_json(404, {"detail": "Camera worker not found"})
            return

        item = worker.get_live_embedding()
        if item is None:
            self._send_json(404, {"detail": "No recent live face embedding"})
            return

        embedding = np.asarray(item["embedding"], dtype=np.float32)
        box = item.get("box")
        person_id = item.get("person_id")
        similarity = item.get("similarity")
        age_seconds = item.get("age_seconds")
        self._send_json(
            200,
            {
                "embedding_b64": base64.b64encode(embedding.tobytes()).decode("ascii"),
                "embedding_len": int(embedding.size),
                "box": [int(round(float(value))) for value in box]
                if isinstance(box, tuple)
                else box,
                "person_id": int(person_id) if person_id is not None else None,
                "similarity": float(similarity) if similarity is not None else None,
                "recognized": bool(item.get("recognized")),
                "label": item.get("label"),
                "age_seconds": float(age_seconds) if age_seconds is not None else None,
            },
        )

    def _serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(path)

        mime, _ = mimetypes.guess_type(path.name)
        if not mime:
            mime = "application/octet-stream"
        size = path.stat().st_size
        range_header = self.headers.get("Range") or self.headers.get("range")

        if range_header:
            match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
                end = min(end, size - 1)
                if start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Type", mime)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                with path.open("rb") as f:
                    f.seek(start)
                    remaining = end - start + 1
                    while remaining > 0:
                        chunk = f.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        self.wfile.write(chunk)
                return

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _serve_recording_snapshot(self, path: Path, ts: float | None, max_width: int = 640, quality: int = 72) -> None:
        if not path.exists():
            raise FileNotFoundError(path)
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            self._send_json(503, {"detail": "Cannot open recording"})
            return
        try:
            if ts is not None:
                cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
            else:
                frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                if frames and frames > 0:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frames / 2)
            ok, frame = cap.read()
            if not ok or frame is None:
                self._send_json(503, {"detail": "Cannot read frame"})
                return
            frame = _resize_for_max_width(frame, max_width)
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
            if not ok:
                self._send_json(503, {"detail": "Encode failed"})
                return
            payload = buf.tobytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        finally:
            cap.release()

    def _serve_recording_mjpeg(self, path: Path, query: str = "") -> None:
        if not path.exists():
            raise FileNotFoundError(path)
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            self._send_json(503, {"detail": "Cannot open recording"})
            return

        qs = parse_qs(query or "")
        requested_fps = _parse_float(qs.get("fps", ["8"])[0], default=8.0)
        max_width = _parse_int(qs.get("max_width", ["960"])[0], default=960, minimum=320, maximum=1920)
        quality = _parse_int(qs.get("quality", ["72"])[0], default=72, minimum=40, maximum=95)

        self.send_response(200)
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        try:
            src_fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
            target_fps = min(max(float(requested_fps), 1.0), max(float(src_fps or 8.0), 1.0), 15.0)
            delay = 1.0 / max(target_fps, 1.0)
            frame_step = max(1, round(float(src_fps or target_fps) / target_fps))
            encode_opts = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
            frame_index = 0
            while not self.media_server.stop_event.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                frame_index += 1
                if frame_step > 1 and frame_index % frame_step != 1:
                    continue
                frame = _resize_for_max_width(frame, max_width)
                ok, buf = cv2.imencode(".jpg", frame, encode_opts)
                if not ok:
                    continue
                chunk = buf.tobytes()
                header = (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(chunk)}\r\n\r\n".encode("ascii")
                )
                self.wfile.write(header)
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                time.sleep(delay)
        finally:
            cap.release()


class ProcessorMediaServer:
    def __init__(
        self,
        service: "ProcessorService",
        host: str,
        port: int,
        media_token: str,
        *,
        max_connections: int = 64,
        socket_timeout: float = 15.0,
    ):
        self.service = service
        self.host = host
        self.port = port
        self.media_token = media_token
        self.max_connections = max(1, int(max_connections))
        self.socket_timeout = max(1.0, float(socket_timeout))
        self.stop_event = threading.Event()
        self.embedding_service = EmbeddingService()
        self.auth_failure_limiter = _AuthFailureLimiter(
            limit=MEDIA_AUTH_FAILURE_LIMIT,
            window_seconds=MEDIA_AUTH_FAILURE_WINDOW_SECONDS,
        )
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        ensure_media_dirs()
        self.stop_event.clear()
        self.embedding_service.start()
        self._server = _BoundedThreadingHTTPServer(
            (self.host, self.port),
            _MediaRequestHandler,
            max_connections=self.max_connections,
            socket_timeout=self.socket_timeout,
        )
        self._server.media_server = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        log.info("Processor media server listening on http://%s:%s", self.host, self.port)

    def stop(self) -> None:
        self.stop_event.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        self.embedding_service.stop()


def _parse_float(value: str | None, default: float | None) -> float | None:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _parse_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _resize_for_max_width(frame: np.ndarray, max_width: int) -> np.ndarray:
    height, width = frame.shape[:2]
    if width <= max_width:
        return frame
    scale = max_width / float(width)
    return cv2.resize(
        frame,
        (max_width, max(1, int(height * scale))),
        interpolation=cv2.INTER_AREA,
    )
