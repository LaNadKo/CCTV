"""Build Processor runtime artifacts used by the Flutter GUI."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

try:
    from processor.reproducible_build import (
        RUNTIME_BUILD_TIMESTAMP,
        SUPERVISOR_BUILD_TIMESTAMP,
        normalize_supervisor_exe,
    )
except ImportError:  # pragma: no cover - allows running this file from processor/.
    from reproducible_build import (
        RUNTIME_BUILD_TIMESTAMP,
        SUPERVISOR_BUILD_TIMESTAMP,
        normalize_supervisor_exe,
    )


HERE = Path(__file__).resolve().parent
ASSETS_DIR = HERE / "assets"
EXCLUDED_MODULES = [
    "aiohappyeyeballs",
    "aiohttp",
    "aiosignal",
    "brotli",
    "frozenlist",
    "multidict",
    "propcache",
    "yarl",
]


def _run(cmd: list[str], *, source_date_epoch: int | None = None) -> None:
    print("Running:", " ".join(cmd))
    env = os.environ.copy()
    if source_date_epoch is not None:
        env["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    subprocess.run(cmd, cwd=str(HERE.parent), env=env, check=True)


def _with_excludes(cmd: list[str]) -> list[str]:
    result = list(cmd)
    for module in EXCLUDED_MODULES:
        result.extend(["--exclude-module", module])
    return result


def _runtime_cmd() -> list[str]:
    return _with_excludes([
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--specpath",
        str(HERE),
        "--workpath",
        str(HERE / "build"),
        "--distpath",
        str(HERE / "dist"),
        "--name",
        "CCTV-Processor-Runtime",
        "--icon",
        str(ASSETS_DIR / "icon.ico"),
        "--add-data",
        f"{ASSETS_DIR};processor/assets",
        "--hidden-import",
        "processor",
        "--hidden-import",
        "processor.main",
        "--hidden-import",
        "processor.client",
        "--hidden-import",
        "processor.config",
        "--hidden-import",
        "processor.detection",
        "--hidden-import",
        "processor.vision",
        "--hidden-import",
        "processor.camera_utils",
        "--hidden-import",
        "processor.monitor",
        "--hidden-import",
        "processor.media_server",
        "--hidden-import",
        "processor.cli",
        "--hidden-import",
        "processor.runtime",
        "--hidden-import",
        "processor.supervisor",
        "--hidden-import",
        "processor.embedding_service",
        "--hidden-import",
        "processor.latest_queue",
        "--hidden-import",
        "processor.paths",
        "--hidden-import",
        "processor.tracker",
        "--hidden-import",
        "processor.tracking",
        "--hidden-import",
        "processor.body_detector",
        "--hidden-import",
        "processor.antispoof",
        "--hidden-import",
        "cctv_ai",
        "--hidden-import",
        "cctv_ai.face_onnx",
        "--hidden-import",
        "mmdeploy_runtime",
        "--hidden-import",
        "pydantic_settings",
        "--hidden-import",
        "pynvml",
        "--hidden-import",
        "psutil",
        "--collect-binaries",
        "onnxruntime",
        "--collect-data",
        "onnxruntime",
        "--collect-binaries",
        "mmdeploy_runtime",
        "--collect-data",
        "mmdeploy_runtime",
        "--collect-binaries",
        "nvidia",
        "--collect-data",
        "nvidia",
        "--collect-submodules",
        "onvif",
        "--collect-submodules",
        "zeep",
        "--collect-data",
        "onvif",
        str(HERE / "run_runtime.py"),
    ])


def _cli_cmd() -> list[str]:
    return _with_excludes([
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onedir",
        "--console",
        "--specpath",
        str(HERE),
        "--workpath",
        str(HERE / "build" / "cli"),
        "--distpath",
        str(HERE / "dist"),
        "--name",
        "CCTV-Processor-CLI",
        "--icon",
        str(ASSETS_DIR / "icon.ico"),
        "--add-data",
        f"{ASSETS_DIR};processor/assets",
        "--hidden-import",
        "processor",
        "--hidden-import",
        "processor.cli",
        "--hidden-import",
        "processor.runtime",
        "--hidden-import",
        "processor.client",
        "--hidden-import",
        "processor.config",
        "--hidden-import",
        "processor.camera_utils",
        "--hidden-import",
        "processor.monitor",
        "--hidden-import",
        "processor.vision",
        "--hidden-import",
        "processor.body_detector",
        "--hidden-import",
        "cctv_ai.face_onnx",
        "--hidden-import",
        "mmdeploy_runtime",
        "--hidden-import",
        "cv2",
        "--hidden-import",
        "pydantic_settings",
        "--collect-binaries",
        "onnxruntime",
        "--collect-data",
        "onnxruntime",
        "--collect-binaries",
        "mmdeploy_runtime",
        "--collect-data",
        "mmdeploy_runtime",
        "--collect-binaries",
        "nvidia",
        "--collect-data",
        "nvidia",
        str(HERE / "cli.py"),
    ])


def _supervisor_cmd() -> list[str]:
    return _with_excludes([
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--specpath",
        str(HERE),
        "--workpath",
        str(HERE / "build" / "supervisor"),
        "--distpath",
        str(HERE / "dist"),
        "--name",
        "CCTV-Processor-Supervisor",
        "--icon",
        str(ASSETS_DIR / "icon.ico"),
        "--add-data",
        f"{ASSETS_DIR};processor/assets",
        "--hidden-import",
        "processor",
        "--hidden-import",
        "processor.client",
        "--hidden-import",
        "processor.config",
        "--hidden-import",
        "processor.runtime",
        "--hidden-import",
        "processor.supervisor",
        "--hidden-import",
        "processor.embedding_service",
        "--hidden-import",
        "processor.latest_queue",
        "--hidden-import",
        "processor.paths",
        "--hidden-import",
        "pydantic_settings",
        "--hidden-import",
        "psutil",
        str(HERE / "run_supervisor.py"),
    ])


def build() -> None:
    _run(_runtime_cmd(), source_date_epoch=RUNTIME_BUILD_TIMESTAMP)
    _run(_supervisor_cmd(), source_date_epoch=SUPERVISOR_BUILD_TIMESTAMP)
    normalize_supervisor_exe(HERE / "dist" / "CCTV-Processor-Supervisor.exe")
    skip_cli = os.environ.get("SKIP_PROCESSOR_CLI", "").strip().lower() in {"1", "true", "yes"}
    if not skip_cli:
        _run(_cli_cmd(), source_date_epoch=RUNTIME_BUILD_TIMESTAMP)
    print(f"\nBuild complete: {HERE / 'dist' / 'CCTV-Processor-Runtime'}")
    print(f"Supervisor complete: {HERE / 'dist' / 'CCTV-Processor-Supervisor.exe'}")


if __name__ == "__main__":
    build()
