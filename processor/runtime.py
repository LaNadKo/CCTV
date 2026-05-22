"""Shared runtime helpers for GUI and headless processor modes."""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import secrets
import socket
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
            divisor = max(1, int(round(float(legacy_interval) * _PROCESSING_BASE_FPS)))
        except (TypeError, ValueError):
            divisor = 8
    normalized["face_scan_divisor"] = _sanitize_frame_divisor(divisor, 8)
    normalized["overlay_frame_divisor"] = _sanitize_frame_divisor(
        normalized.get("overlay_frame_divisor", 1),
        1,
    )
    normalized["face_scan_interval"] = _frame_divisor_to_interval(normalized["face_scan_divisor"])
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
        "face_scan_divisor": 8,
        "overlay_frame_divisor": 1,
        "face_scan_interval": 0.35,
        "theme_primary_color": "#49C8E8",
        "theme_secondary_color": "#4C6FFF",
        "recording_segment_seconds": 60,
        "recordings_dir": str(base_dir() / "media" / "recordings"),
        "snapshots_dir": str(base_dir() / "media" / "snapshots"),
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
        "RECORDING_SEGMENT_SECONDS": ("recording_segment_seconds", "int"),
        "RECORDINGS_DIR": ("recordings_dir", "str"),
        "SNAPSHOTS_DIR": ("snapshots_dir", "str"),
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
    os.environ["FACE_SCAN_DIVISOR"] = str(normalized.get("face_scan_divisor", 8))
    os.environ["OVERLAY_FRAME_DIVISOR"] = str(normalized.get("overlay_frame_divisor", 1))
    os.environ["FACE_SCAN_INTERVAL"] = str(normalized.get("face_scan_interval", 0.35))
    os.environ["RECORDING_SEGMENT_SECONDS"] = str(normalized.get("recording_segment_seconds", 60))
    os.environ["RECORDINGS_DIR"] = str(config.get("recordings_dir", base_dir() / "media" / "recordings"))
    os.environ["SNAPSHOTS_DIR"] = str(config.get("snapshots_dir", base_dir() / "media" / "snapshots"))
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
        with urllib.request.urlopen(request, timeout=15) as response:
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
