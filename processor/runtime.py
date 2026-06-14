"""Shared runtime helpers for GUI and headless processor modes."""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from processor.monitor import get_system_info


def base_dir() -> Path:
    runtime_dir = os.environ.get("PROCESSOR_RUNTIME_DIR", "").strip()
    if runtime_dir:
        return Path(runtime_dir)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


CONFIG_FILE = base_dir() / "processor_config.json"
LOG_FILE = base_dir() / "processor.log"
_PROCESSING_BASE_FPS = 24.0
_MAX_FRAME_INTERVAL_SECONDS = 5.0
_FRAME_DIVISOR_CHOICES = (1, 2, 4, 8, 16, 32, 64, 120)
_MIN_FACE_SCAN_DIVISOR = 2


def _sanitize_frame_divisor(value: Any, default: int) -> int:
    try:
        raw = int(value)
    except (TypeError, ValueError):
        raw = default
    if raw <= 0:
        raw = default
    for candidate in _FRAME_DIVISOR_CHOICES:
        if raw <= candidate:
            return candidate
    return _FRAME_DIVISOR_CHOICES[-1]


def _sanitize_face_scan_divisor(value: Any, default: int) -> int:
    divisor = _sanitize_frame_divisor(value, default)
    return max(_MIN_FACE_SCAN_DIVISOR, divisor)


def _frame_divisor_to_interval(divisor: int) -> float:
    return round(min(_MAX_FRAME_INTERVAL_SECONDS, divisor / _PROCESSING_BASE_FPS), 3)


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    try:
        normalized["recording_segment_seconds"] = min(
            60,
            max(10, int(normalized.get("recording_segment_seconds", 60))),
        )
    except (TypeError, ValueError):
        normalized["recording_segment_seconds"] = 60
    divisor = normalized.get("face_scan_divisor")
    if divisor in (None, ""):
        legacy_interval = normalized.get("face_scan_interval", 0.35)
        try:
            divisor = max(_MIN_FACE_SCAN_DIVISOR, int(round(float(legacy_interval) * _PROCESSING_BASE_FPS)))
        except (TypeError, ValueError):
            divisor = 4
    normalized["face_scan_divisor"] = _sanitize_face_scan_divisor(divisor, 4)
    normalized["overlay_frame_divisor"] = _sanitize_frame_divisor(
        normalized.get("overlay_frame_divisor", 1),
        1,
    )
    normalized["face_scan_interval"] = _frame_divisor_to_interval(normalized["face_scan_divisor"])
    try:
        normalized["antispoof_pending_timeout_seconds"] = min(
            8.0,
            max(0.8, float(normalized.get("antispoof_pending_timeout_seconds", 2.8))),
        )
    except (TypeError, ValueError):
        normalized["antispoof_pending_timeout_seconds"] = 2.8
    media_bind = str(normalized.get("media_bind") or "").strip()
    normalized["media_bind"] = media_bind or "0.0.0.0"
    try:
        normalized["recording_upload_concurrency"] = min(
            8,
            max(1, int(normalized.get("recording_upload_concurrency", 2))),
        )
    except (TypeError, ValueError):
        normalized["recording_upload_concurrency"] = 2
    try:
        normalized["recording_upload_queue_size"] = min(
            512,
            max(8, int(normalized.get("recording_upload_queue_size", 128))),
        )
    except (TypeError, ValueError):
        normalized["recording_upload_queue_size"] = 128
    try:
        normalized["recording_retention_days"] = min(
            3650,
            max(0, int(normalized.get("recording_retention_days", 0))),
        )
    except (TypeError, ValueError):
        normalized["recording_retention_days"] = 0
    try:
        normalized["recording_retention_max_bytes"] = max(
            0,
            int(normalized.get("recording_retention_max_bytes", 0)),
        )
    except (TypeError, ValueError):
        normalized["recording_retention_max_bytes"] = 0
    try:
        normalized["recording_min_free_bytes"] = min(
            100 * 1024**3,
            max(64 * 1024**2, int(normalized.get("recording_min_free_bytes", 536_870_912))),
        )
    except (TypeError, ValueError):
        normalized["recording_min_free_bytes"] = 536_870_912
    try:
        normalized["max_capture_pixels"] = min(
            33_177_600,
            max(307_200, int(normalized.get("max_capture_pixels", 8_294_400))),
        )
    except (TypeError, ValueError):
        normalized["max_capture_pixels"] = 8_294_400
    return normalized


def default_config() -> dict[str, Any]:
    return normalize_config(
        {
        "backend_url": "",
        "api_key": "",
        "processor_id": None,
        "processor_name": socket.gethostname(),
        "processor_node_uid": uuid.uuid4().hex,
        "advertised_ip": "",
        "poll_interval": 1,
        "heartbeat_interval": 10,
        "max_workers": 4,
        "processor_accel": "auto",
        "motion_threshold": 25.0,
        "face_scan_divisor": 4,
        "overlay_frame_divisor": 1,
        "face_scan_interval": 0.35,
        "antispoof_model_enabled": True,
        "antispoof_model_path": "",
        "antispoof_model_real_threshold": 0.72,
        "antispoof_model_fake_threshold": 0.72,
        "antispoof_pending_timeout_seconds": 2.8,
        "theme_primary_color": "#49C8E8",
        "theme_secondary_color": "#4C6FFF",
        "recording_segment_seconds": 60,
        "recording_upload_concurrency": 2,
        "recording_upload_queue_size": 128,
        "recording_retention_days": 0,
        "recording_retention_max_bytes": 0,
        "recording_min_free_bytes": 536_870_912,
        "max_capture_pixels": 8_294_400,
        "recordings_dir": str(base_dir() / "media" / "recordings"),
        "snapshots_dir": str(base_dir() / "media" / "snapshots"),
        "media_bind": "0.0.0.0",
        "media_port": 8777,
        "media_token": secrets.token_urlsafe(24),
        }
    )


def load_config() -> dict[str, Any]:
    defaults = default_config()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
                return normalize_config({**defaults, **json.load(handle)})
        except Exception:
            pass
    return defaults


def save_config(config: dict[str, Any]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, ensure_ascii=False)
    _restrict_config_permissions(CONFIG_FILE)


def _restrict_config_permissions(path: Path) -> None:
    try:
        if os.name != "nt":
            path.chmod(0o600)
            return
        user = os.environ.get("USERNAME", "").strip()
        domain = os.environ.get("USERDOMAIN", "").strip()
        if not user:
            return
        account = f"{domain}\\{user}" if domain else user
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{account}:(R,W)",
                "*S-1-5-18:(F)",
                "*S-1-5-32-544:(F)",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        logging.getLogger(__name__).debug("Failed to restrict processor config permissions", exc_info=True)


def _coerce_env_value(raw: str, kind: str) -> Any:
    if kind == "bool":
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    return raw


def apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    mapping: dict[str, tuple[str, str]] = {
        "BACKEND_URL": ("backend_url", "str"),
        "API_KEY": ("api_key", "str"),
        "PROCESSOR_ID": ("processor_id", "int"),
        "PROCESSOR_NAME": ("processor_name", "str"),
        "PROCESSOR_NODE_UID": ("processor_node_uid", "str"),
        "PROCESSOR_ADVERTISED_IP": ("advertised_ip", "str"),
        "POLL_INTERVAL": ("poll_interval", "int"),
        "HEARTBEAT_INTERVAL": ("heartbeat_interval", "int"),
        "MAX_WORKERS": ("max_workers", "int"),
        "PROCESSOR_ACCEL": ("processor_accel", "str"),
        "MOTION_THRESHOLD": ("motion_threshold", "float"),
        "FACE_SCAN_DIVISOR": ("face_scan_divisor", "int"),
        "OVERLAY_FRAME_DIVISOR": ("overlay_frame_divisor", "int"),
        "FACE_SCAN_INTERVAL": ("face_scan_interval", "float"),
        "ANTISPOOF_MODEL_ENABLED": ("antispoof_model_enabled", "bool"),
        "ANTISPOOF_MODEL_PATH": ("antispoof_model_path", "str"),
        "ANTISPOOF_MODEL_REAL_THRESHOLD": ("antispoof_model_real_threshold", "float"),
        "ANTISPOOF_MODEL_FAKE_THRESHOLD": ("antispoof_model_fake_threshold", "float"),
        "ANTISPOOF_PENDING_TIMEOUT_SECONDS": ("antispoof_pending_timeout_seconds", "float"),
        "RECORDING_SEGMENT_SECONDS": ("recording_segment_seconds", "int"),
        "RECORDING_UPLOAD_CONCURRENCY": ("recording_upload_concurrency", "int"),
        "RECORDING_UPLOAD_QUEUE_SIZE": ("recording_upload_queue_size", "int"),
        "RECORDING_RETENTION_DAYS": ("recording_retention_days", "int"),
        "RECORDING_RETENTION_MAX_BYTES": ("recording_retention_max_bytes", "int"),
        "RECORDING_MIN_FREE_BYTES": ("recording_min_free_bytes", "int"),
        "MAX_CAPTURE_PIXELS": ("max_capture_pixels", "int"),
        "RECORDINGS_DIR": ("recordings_dir", "str"),
        "SNAPSHOTS_DIR": ("snapshots_dir", "str"),
        "MEDIA_BIND": ("media_bind", "str"),
        "MEDIA_PORT": ("media_port", "int"),
        "MEDIA_TOKEN": ("media_token", "str"),
    }
    merged = dict(config)
    for env_name, (config_key, kind) in mapping.items():
        raw_value = os.environ.get(env_name)
        if raw_value is None or raw_value == "":
            continue
        merged[config_key] = _coerce_env_value(raw_value, kind)
    if not merged.get("media_token"):
        merged["media_token"] = secrets.token_urlsafe(24)
    if not merged.get("processor_node_uid"):
        merged["processor_node_uid"] = uuid.uuid4().hex
    return normalize_config(merged)


def export_env(config: dict[str, Any]) -> None:
    normalized = normalize_config(config)
    os.environ["BACKEND_URL"] = str(config.get("backend_url") or "")
    os.environ["API_KEY"] = str(config.get("api_key") or "")
    os.environ["PROCESSOR_ID"] = "" if config.get("processor_id") in (None, "") else str(config["processor_id"])
    os.environ["PROCESSOR_NAME"] = str(config.get("processor_name") or socket.gethostname())
    os.environ["PROCESSOR_NODE_UID"] = str(config.get("processor_node_uid") or "")
    os.environ["PROCESSOR_ADVERTISED_IP"] = str(config.get("advertised_ip") or "")
    os.environ["POLL_INTERVAL"] = str(config.get("poll_interval", 1))
    os.environ["HEARTBEAT_INTERVAL"] = str(config.get("heartbeat_interval", 10))
    os.environ["MAX_WORKERS"] = str(config.get("max_workers", 4))
    os.environ["PROCESSOR_ACCEL"] = str(config.get("processor_accel") or "auto")
    os.environ["MOTION_THRESHOLD"] = str(config.get("motion_threshold", 25.0))
    os.environ["FACE_SCAN_DIVISOR"] = str(normalized.get("face_scan_divisor", 4))
    os.environ["OVERLAY_FRAME_DIVISOR"] = str(normalized.get("overlay_frame_divisor", 1))
    os.environ["FACE_SCAN_INTERVAL"] = str(normalized.get("face_scan_interval", 0.35))
    os.environ["ANTISPOOF_MODEL_ENABLED"] = "1" if normalized.get("antispoof_model_enabled", True) else "0"
    os.environ["ANTISPOOF_MODEL_PATH"] = str(config.get("antispoof_model_path") or "")
    os.environ["ANTISPOOF_MODEL_REAL_THRESHOLD"] = str(normalized.get("antispoof_model_real_threshold", 0.72))
    os.environ["ANTISPOOF_MODEL_FAKE_THRESHOLD"] = str(normalized.get("antispoof_model_fake_threshold", 0.72))
    os.environ["ANTISPOOF_PENDING_TIMEOUT_SECONDS"] = str(normalized.get("antispoof_pending_timeout_seconds", 2.8))
    os.environ["RECORDING_SEGMENT_SECONDS"] = str(normalized.get("recording_segment_seconds", 60))
    os.environ["RECORDING_UPLOAD_CONCURRENCY"] = str(normalized.get("recording_upload_concurrency", 2))
    os.environ["RECORDING_UPLOAD_QUEUE_SIZE"] = str(normalized.get("recording_upload_queue_size", 128))
    os.environ["RECORDING_RETENTION_DAYS"] = str(normalized.get("recording_retention_days", 0))
    os.environ["RECORDING_RETENTION_MAX_BYTES"] = str(normalized.get("recording_retention_max_bytes", 0))
    os.environ["RECORDING_MIN_FREE_BYTES"] = str(normalized.get("recording_min_free_bytes", 536_870_912))
    os.environ["MAX_CAPTURE_PIXELS"] = str(normalized.get("max_capture_pixels", 8_294_400))
    os.environ["RECORDINGS_DIR"] = str(config.get("recordings_dir", base_dir() / "media" / "recordings"))
    os.environ["SNAPSHOTS_DIR"] = str(config.get("snapshots_dir", base_dir() / "media" / "snapshots"))
    os.environ["MEDIA_BIND"] = str(config.get("media_bind") or "0.0.0.0")
    os.environ["MEDIA_PORT"] = str(config.get("media_port", 8777))
    os.environ["MEDIA_TOKEN"] = str(config.get("media_token") or secrets.token_urlsafe(24))


def connect_with_code(config: dict[str, Any], code: str) -> dict[str, Any]:
    config = normalize_config(config)
    backend_url = str(config.get("backend_url") or "").strip().rstrip("/")
    if not backend_url:
        raise RuntimeError("BACKEND_URL is required for headless processor connection")
    if not code:
        raise RuntimeError("Connection code is required")

    from processor.networking import detect_advertised_ip

    advertised_ip = detect_advertised_ip(str(config.get("advertised_ip") or "").strip(), backend_url=backend_url)
    system_info = get_system_info()
    payload = json.dumps(
        {
            "code": code,
            "name": config.get("processor_name") or socket.gethostname(),
            "node_uid": config.get("processor_node_uid"),
            "ip_address": advertised_ip,
            "hostname": system_info.get("hostname"),
            "os_info": system_info.get("os"),
            "version": "1.0.0",
            "capabilities": {
                **system_info,
                "advertised_ip": advertised_ip,
                "media_port": int(config.get("media_port", 8777)),
                "media_token": config.get("media_token"),
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{backend_url}/processors/connect",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.reason
        try:
            body = exc.read().decode("utf-8", "replace")
            payload = json.loads(body)
            detail = payload.get("detail", detail)
        except Exception:
            pass
        raise RuntimeError(f"Processor connection failed: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"Processor connection failed: {exc}") from exc

    connected = dict(config)
    connected["backend_url"] = backend_url
    connected["api_key"] = data["api_key"]
    connected["processor_id"] = data["processor_id"]
    connected["processor_name"] = data["name"]
    if not connected.get("processor_node_uid"):
        connected["processor_node_uid"] = uuid.uuid4().hex
    if advertised_ip:
        connected["advertised_ip"] = advertised_ip
    save_config(connected)
    return connected


def ensure_connected(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("api_key") and config.get("processor_id"):
        return config
    connect_code = os.environ.get("PROCESSOR_CONNECT_CODE", "").strip()
    if not connect_code:
        if config.get("api_key"):
            return config
        raise RuntimeError("Processor is not configured. Set PROCESSOR_CONNECT_CODE or connect once through the GUI.")
    return connect_with_code(config, connect_code)


class RuntimeLock:
    def __init__(self, name: str = "processor.lock") -> None:
        self.path = base_dir() / name
        self.global_path = Path(tempfile.gettempdir()) / "cctv-processor-global.lock"
        self._handle = None
        self._global_handle = None

    def _lock_handle(self, handle) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_handle(self, handle) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def acquire(self) -> None:
        self.global_path.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        global_handle = open(self.global_path, "a+", encoding="utf-8")
        handle = open(self.path, "a+", encoding="utf-8")
        try:
            self._lock_handle(global_handle)
            self._lock_handle(handle)
        except OSError as exc:
            handle.close()
            global_handle.close()
            raise RuntimeError("Another local Processor instance is already running on this machine") from exc
        except Exception:
            handle.close()
            global_handle.close()
            raise
        global_handle.seek(0)
        global_handle.truncate()
        global_handle.write(f"{os.getpid()} {base_dir()}")
        global_handle.flush()
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._global_handle = global_handle
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        global_handle = self._global_handle
        for current in (handle, global_handle):
            if current is None:
                continue
            try:
                try:
                    self._unlock_handle(current)
                except OSError:
                    pass
            finally:
                current.close()
        self._handle = None
        self._global_handle = None


def configure_headless_logging() -> None:
    root_logger = logging.getLogger()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root_logger.setLevel(logging.INFO)
    log_path = str(LOG_FILE.resolve())

    has_file_handler = any(
        isinstance(handler, logging.FileHandler)
        and str(Path(getattr(handler, "baseFilename", "")).resolve()) == log_path
        for handler in root_logger.handlers
    )
    if not has_file_handler:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    if not getattr(sys, "frozen", False):
        has_stream_handler = any(
            isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
            for handler in root_logger.handlers
        )
        if not has_stream_handler:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            root_logger.addHandler(stream_handler)


def run_headless() -> None:
    config = apply_env_overrides(load_config())
    save_config(config)
    config = ensure_connected(config)
    save_config(config)
    export_env(config)
    configure_headless_logging()

    from processor import config as processor_config

    importlib.reload(processor_config)

    from processor.main import main as processor_main

    asyncio.run(processor_main())


if __name__ == "__main__":
    run_headless()
