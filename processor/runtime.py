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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from processor.monitor import get_system_info


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


CONFIG_FILE = base_dir() / "processor_config.json"
LOG_FILE = base_dir() / "processor.log"


def default_config() -> dict[str, Any]:
    return {
        "backend_url": "",
        "api_key": "",
        "processor_id": None,
        "processor_name": socket.gethostname(),
        "max_workers": 4,
        "motion_threshold": 25.0,
        "face_scan_interval": 0.7,
        "recording_segment_seconds": 300,
        "recordings_dir": str(base_dir() / "media" / "recordings"),
        "snapshots_dir": str(base_dir() / "media" / "snapshots"),
        "media_port": 8777,
        "media_token": secrets.token_urlsafe(24),
    }


def load_config() -> dict[str, Any]:
    defaults = default_config()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
                return {**defaults, **json.load(handle)}
        except Exception:
            pass
    return defaults


def save_config(config: dict[str, Any]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, ensure_ascii=False)


def _coerce_env_value(raw: str, kind: str) -> Any:
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
        "MAX_WORKERS": ("max_workers", "int"),
        "MOTION_THRESHOLD": ("motion_threshold", "float"),
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
    return merged


def export_env(config: dict[str, Any]) -> None:
    os.environ["BACKEND_URL"] = str(config.get("backend_url") or "")
    os.environ["API_KEY"] = str(config.get("api_key") or "")
    os.environ["PROCESSOR_ID"] = "" if config.get("processor_id") in (None, "") else str(config["processor_id"])
    os.environ["PROCESSOR_NAME"] = str(config.get("processor_name") or socket.gethostname())
    os.environ["MAX_WORKERS"] = str(config.get("max_workers", 4))
    os.environ["MOTION_THRESHOLD"] = str(config.get("motion_threshold", 25.0))
    os.environ["FACE_SCAN_INTERVAL"] = str(config.get("face_scan_interval", 0.7))
    os.environ["RECORDING_SEGMENT_SECONDS"] = str(config.get("recording_segment_seconds", 300))
    os.environ["RECORDINGS_DIR"] = str(config.get("recordings_dir", base_dir() / "media" / "recordings"))
    os.environ["SNAPSHOTS_DIR"] = str(config.get("snapshots_dir", base_dir() / "media" / "snapshots"))
    os.environ["MEDIA_PORT"] = str(config.get("media_port", 8777))
    os.environ["MEDIA_TOKEN"] = str(config.get("media_token") or secrets.token_urlsafe(24))


def connect_with_code(config: dict[str, Any], code: str) -> dict[str, Any]:
    backend_url = str(config.get("backend_url") or "").strip().rstrip("/")
    if not backend_url:
        raise RuntimeError("BACKEND_URL is required for headless processor connection")
    if not code:
        raise RuntimeError("Connection code is required")

    system_info = get_system_info()
    payload = json.dumps(
        {
            "code": code,
            "name": config.get("processor_name") or socket.gethostname(),
            "hostname": system_info.get("hostname"),
            "os_info": system_info.get("os"),
            "version": "1.0.0",
            "capabilities": {
                **system_info,
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
    save_config(connected)
    return connected


def ensure_connected(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("api_key"):
        return config
    connect_code = os.environ.get("PROCESSOR_CONNECT_CODE", "").strip()
    if not connect_code:
        raise RuntimeError(
            "Processor is not configured. Set PROCESSOR_CONNECT_CODE or connect once through the GUI."
        )
    return connect_with_code(config, connect_code)


def configure_headless_logging() -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    if not getattr(sys, "frozen", False):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)


def run_headless() -> None:
    config = apply_env_overrides(load_config())
    config = ensure_connected(config)
    export_env(config)
    configure_headless_logging()

    from processor import config as processor_config

    importlib.reload(processor_config)

    from processor.main import main as processor_main

    asyncio.run(processor_main())
