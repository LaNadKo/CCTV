"""Lightweight HTTP server exposing processor-owned media."""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np

from processor.paths import RECORDINGS_DIR, SNAPSHOTS_DIR, ensure_media_dirs

if TYPE_CHECKING:
    from processor.main import ProcessorService


log = logging.getLogger(__name__)


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
                self._send_json(403, {"detail": "Forbidden"})
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
                self._serve_recording_mjpeg(_safe_join(RECORDINGS_DIR, rel))
                return

            if path.startswith("/media/recordings-snapshot/"):
                rel = path[len("/media/recordings-snapshot/") :]
                qs = parse_qs(parsed.query or "")
                ts_raw = qs.get("ts", [None])[0]
                ts = float(ts_raw) if ts_raw not in (None, "") else None
                self._serve_recording_snapshot(_safe_join(RECORDINGS_DIR, rel), ts)
                return

            if path.startswith("/media/recordings/"):
                rel = path[len("/media/recordings/") :]
                self._serve_file(_safe_join(RECORDINGS_DIR, rel))
                return

            self._send_json(404, {"detail": "Not found"})
        except FileNotFoundError:
            self._send_json(404, {"detail": "File missing"})
        except BrokenPipeError:
            pass
        except ConnectionResetError:
            pass
        except Exception as exc:
            log.exception("Processor media server request failed")
            self._send_json(500, {"detail": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path

            if not self._authorized():
                self._send_json(403, {"detail": "Forbidden"})
                return

            if path == "/embeddings/extract":
                self._extract_embedding()
                return

            self._send_json(404, {"detail": "Not found"})
        except BrokenPipeError:
            pass
        except ConnectionResetError:
            pass
        except Exception as exc:
            log.exception("Processor media server POST failed")
            self._send_json(500, {"detail": str(exc)})

    def _authorized(self) -> bool:
        expected = self.media_server.media_token
        if not expected:
            return True
        actual = self.headers.get("X-Processor-Media-Token", "")
        return actual == expected

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _extract_embedding(self) -> None:
        from processor.vision import detect_faces

        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            self._send_json(400, {"detail": "Empty request body"})
            return

        payload = self.rfile.read(length)
        image_arr = np.frombuffer(payload, np.uint8)
        image = cv2.imdecode(image_arr, cv2.IMREAD_COLOR)
        if image is None:
            self._send_json(400, {"detail": "Invalid image"})
            return

        faces = detect_faces(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
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

        self.send_response(200)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        while not self.media_server.stop_event.is_set():
            frame = worker.get_stream_frame(overlay=overlay)
            if frame:
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            time.sleep(1 / 12)

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

    def _serve_recording_snapshot(self, path: Path, ts: float | None) -> None:
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
            ok, buf = cv2.imencode(".jpg", frame)
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

    def _serve_recording_mjpeg(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(path)
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            self._send_json(503, {"detail": "Cannot open recording"})
            return

        self.send_response(200)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
            delay = 1.0 / max(fps, 1.0)
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                ok, buf = cv2.imencode(".jpg", frame)
                if not ok:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                self.wfile.write(buf.tobytes())
                self.wfile.write(b"\r\n")
                time.sleep(delay)
        finally:
            cap.release()


class ProcessorMediaServer:
    def __init__(self, service: "ProcessorService", host: str, port: int, media_token: str):
        self.service = service
        self.host = host
        self.port = port
        self.media_token = media_token
        self.stop_event = threading.Event()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            return
        ensure_media_dirs()
        self.stop_event.clear()
        self._server = ThreadingHTTPServer((self.host, self.port), _MediaRequestHandler)
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
