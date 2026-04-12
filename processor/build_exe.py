"""Build processor desktop app as a standalone .exe using PyInstaller."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ASSETS_DIR = HERE / "assets"


def _has_nvidia_gpu() -> bool:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _allow_cpu_build() -> bool:
    return os.environ.get("ALLOW_CPU_PROCESSOR_BUILD", "").strip().lower() in {"1", "true", "yes"}


def _prepare_gpu_runtime() -> None:
    try:
        import onnxruntime as ort

        providers = set(ort.get_available_providers())
        if "CUDAExecutionProvider" not in providers:
            if _has_nvidia_gpu() and not _allow_cpu_build():
                raise RuntimeError(
                    "NVIDIA GPU detected, but CUDAExecutionProvider is not available. "
                    "Install GPU runtime packages first or set ALLOW_CPU_PROCESSOR_BUILD=1 "
                    "to intentionally build a CPU-only processor."
                )
            print("Skipping GPU runtime preparation; CUDAExecutionProvider not available")
            return
        from prepare_gpu_runtime import main as prepare_main

        prepare_main()
    except Exception as exc:
        if _has_nvidia_gpu() and not _allow_cpu_build():
            raise
        print(f"GPU runtime preparation skipped: {exc}")


def _run(cmd: list[str]) -> None:
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(HERE.parent), check=True)


def _gui_cmd() -> list[str]:
    return [
        sys.executable,
        "-m",
        "PyInstaller",
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
        "CCTV-Processor",
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
        "processor.gui",
        "--hidden-import",
        "processor.gui.app",
        "--hidden-import",
        "customtkinter",
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
        "--collect-data",
        "customtkinter",
        str(HERE / "run_gui.py"),
    ]


def _cli_cmd() -> list[str]:
    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
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
        "cctv_ai.face_onnx",
        "--hidden-import",
        "cv2",
        "--collect-binaries",
        "onnxruntime",
        "--collect-data",
        "onnxruntime",
        "--collect-binaries",
        "nvidia",
        "--collect-data",
        "nvidia",
        str(HERE / "cli.py"),
    ]


def build() -> None:
    _prepare_gpu_runtime()
    _run(_gui_cmd())
    skip_cli = os.environ.get("SKIP_PROCESSOR_CLI", "").strip().lower() in {"1", "true", "yes"}
    if not skip_cli:
        _run(_cli_cmd())
    print(f"\nBuild complete: {HERE / 'dist' / 'CCTV-Processor'}")


if __name__ == "__main__":
    build()
