"""Shared filesystem paths for the processor runtime."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


DEFAULT_MEDIA_ROOT = base_dir() / "media"


def _resolve_dir(env_name: str, default_path: Path) -> Path:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default_path.resolve()
    return Path(raw).expanduser().resolve()


MEDIA_ROOT = _resolve_dir("MEDIA_ROOT", DEFAULT_MEDIA_ROOT)
RECORDINGS_DIR = _resolve_dir("RECORDINGS_DIR", MEDIA_ROOT / "recordings")
SNAPSHOTS_DIR = _resolve_dir("SNAPSHOTS_DIR", MEDIA_ROOT / "snapshots")


def ensure_media_dirs() -> None:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
