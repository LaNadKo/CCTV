from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DLL_DIR_HANDLES: list[object] = []
_REGISTERED_DLL_DIRS: list[Path] = []

_ACCEL_ALIASES = {
    "": "auto",
    "auto": "auto",
    "gpu": "auto",
    "cpu": "cpu",
    "nvidia": "nvidia",
    "cuda": "nvidia",
    "tensorrt": "nvidia",
    "trt": "nvidia",
    "intel": "intel",
    "openvino": "intel",
    "amd": "amd",
    "rocm": "amd",
    "migraphx": "amd",
    "directml": "directml",
    "dml": "directml",
}

_PROVIDER_DEVICE = {
    "CUDAExecutionProvider": "cuda",
    "OpenVINOExecutionProvider": "openvino",
    "DmlExecutionProvider": "directml",
    "MIGraphXExecutionProvider": "rocm",
    "ROCMExecutionProvider": "rocm",
    "CPUExecutionProvider": "cpu",
}

_PROVIDER_PRIORITY = {
    "auto": (
        "CUDAExecutionProvider",
        "OpenVINOExecutionProvider",
        "DmlExecutionProvider",
        "MIGraphXExecutionProvider",
        "ROCMExecutionProvider",
        "CPUExecutionProvider",
    ),
    "nvidia": ("CUDAExecutionProvider", "CPUExecutionProvider"),
    "intel": ("OpenVINOExecutionProvider", "CPUExecutionProvider"),
    "amd": ("MIGraphXExecutionProvider", "ROCMExecutionProvider", "CPUExecutionProvider"),
    "directml": ("DmlExecutionProvider", "CPUExecutionProvider"),
    "cpu": ("CPUExecutionProvider",),
}


def _dedupe(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        key = str(resolved)
        if key in seen or not resolved.exists():
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def _bundle_roots() -> list[Path]:
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    try:
        roots.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass
    roots.append(Path(__file__).resolve().parents[1])
    for entry in sys.path:
        if not entry:
            continue
        try:
            roots.append(Path(entry))
        except Exception:
            continue
    return _dedupe(roots)


def _candidate_package_dirs(*parts: str) -> list[Path]:
    candidates = [root.joinpath(*parts) for root in _bundle_roots()]
    return _dedupe(candidates)


def _module_dir(module_name: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(module_name)
    except Exception:
        return None
    if spec is None:
        return None
    if spec.submodule_search_locations:
        return Path(next(iter(spec.submodule_search_locations))).resolve()
    if spec.origin is None:
        return None
    return Path(spec.origin).resolve().parent


def _find_onnxruntime_capi_dir() -> Path | None:
    module_dir = _module_dir("onnxruntime")
    candidates: list[Path] = []
    if module_dir is not None:
        candidates.append(module_dir / "capi")
    candidates.extend(_candidate_package_dirs("onnxruntime", "capi"))
    for candidate in _dedupe(candidates):
        if (candidate / "onnxruntime_providers_shared.dll").exists():
            return candidate
    return None


def _find_mmdeploy_runtime_dir() -> Path | None:
    module_dir = _module_dir("mmdeploy_runtime")
    candidates: list[Path] = []
    if module_dir is not None:
        candidates.append(module_dir)
    candidates.extend(_candidate_package_dirs("mmdeploy_runtime"))
    for candidate in _dedupe(candidates):
        if candidate.is_dir():
            return candidate
    return None


def _find_torch_lib_dir() -> Path | None:
    for candidate in _candidate_package_dirs("torch", "lib"):
        if candidate.is_dir():
            return candidate
    return None


def _iter_nvidia_bin_dirs() -> list[Path]:
    dirs: list[Path] = []
    for pkg_root in _candidate_package_dirs("nvidia"):
        if not pkg_root.is_dir():
            continue
        for child in pkg_root.iterdir():
            bin_dir = child / "bin"
            if bin_dir.is_dir():
                dirs.append(bin_dir)
    return _dedupe(dirs)


def _valid_cuda_root(path: Path | None) -> Path | None:
    if path is None:
        return None
    bin_dir = path / "bin"
    if not bin_dir.is_dir():
        return None
    return path


def _find_cuda_runtime_root() -> Path | None:
    for env_name in ("CCTV_CUDA_PATH", "CUDA_PATH", "CUDA_HOME"):
        env_root = os.environ.get(env_name)
        if not env_root:
            continue
        valid = _valid_cuda_root(Path(env_root))
        if valid is not None:
            return valid

    for candidate in _candidate_package_dirs("nvidia", "cuda_runtime"):
        valid = _valid_cuda_root(candidate)
        if valid is not None:
            return valid

    for root in _bundle_roots():
        for relative in (
            ("cuda_runtime",),
            ("cuda11",),
            ("runtime", "cuda_runtime"),
        ):
            valid = _valid_cuda_root(root.joinpath(*relative))
            if valid is not None:
                return valid

    for env_name in ("ProgramFiles", "ProgramW6432"):
        program_files = os.environ.get(env_name)
        if not program_files:
            continue
        cuda_dir = Path(program_files) / "NVIDIA GPU Computing Toolkit" / "CUDA"
        if not cuda_dir.is_dir():
            continue
        for candidate in sorted(cuda_dir.glob("v*"), reverse=True):
            valid = _valid_cuda_root(candidate)
            if valid is not None:
                return valid
    return None


def register_dll_dirs(paths: list[Path]) -> list[Path]:
    registered: list[Path] = []
    for path in _dedupe(paths):
        if not path.is_dir():
            continue
        path_str = str(path)
        if hasattr(os, "add_dll_directory"):
            try:
                _DLL_DIR_HANDLES.append(os.add_dll_directory(path_str))
            except OSError:
                logger.debug("Failed to add DLL directory: %s", path_str, exc_info=True)
                continue
        current_path = os.environ.get("PATH", "")
        parts = current_path.split(os.pathsep) if current_path else []
        if path_str not in parts:
            os.environ["PATH"] = path_str + os.pathsep + current_path if current_path else path_str
        if path not in _REGISTERED_DLL_DIRS:
            _REGISTERED_DLL_DIRS.append(path)
        registered.append(path)
    return registered


def normalize_acceleration_preference(raw: str | None = None) -> str:
    value = (raw if raw is not None else os.environ.get("PROCESSOR_ACCEL", "auto")).strip().lower()
    normalized = _ACCEL_ALIASES.get(value)
    if normalized is None:
        logger.warning("Unknown PROCESSOR_ACCEL=%s; using auto", value)
        return "auto"
    return normalized


def prepare_acceleration_env(preference: str | None = None) -> dict[str, Any]:
    target = normalize_acceleration_preference(preference)
    cuda_root = None
    ort_cuda_env: dict[str, Any] = {}
    if target in {"auto", "nvidia"}:
        ort_cuda_env = prepare_onnxruntime_cuda_env()
        cuda_root = prepare_mmdeploy_cuda_env()
    return {
        "preference": target,
        "cuda_root": cuda_root,
        "onnxruntime_capi": ort_cuda_env.get("onnxruntime_capi"),
        "torch_lib": ort_cuda_env.get("torch_lib"),
        "nvidia_bins": ort_cuda_env.get("nvidia_bins") or [],
        "registered_dll_dirs": list(_REGISTERED_DLL_DIRS),
    }


def available_onnx_providers(preference: str | None = None) -> list[str]:
    prepare_acceleration_env(preference)
    try:
        import onnxruntime as ort
    except Exception:
        logger.debug("onnxruntime import failed while reading providers", exc_info=True)
        return []
    try:
        return list(ort.get_available_providers())
    except Exception:
        logger.debug("onnxruntime provider query failed", exc_info=True)
        return []


def select_onnx_execution_providers(prefer_gpu: bool = True, preference: str | None = None) -> tuple[list[str], str, str]:
    target = normalize_acceleration_preference(preference)
    if not prefer_gpu:
        target = "cpu"
    available = set(available_onnx_providers(target))
    for provider in _PROVIDER_PRIORITY[target]:
        if provider in available:
            providers = [provider]
            if provider != "CPUExecutionProvider" and "CPUExecutionProvider" in available:
                providers.append("CPUExecutionProvider")
            return providers, _PROVIDER_DEVICE.get(provider, "cpu"), provider
    return ["CPUExecutionProvider"], "cpu", "CPUExecutionProvider"


def select_mmdeploy_device(preference: str | None = None) -> tuple[str, dict[str, Any]]:
    target = normalize_acceleration_preference(preference)
    env_info = prepare_acceleration_env(target)
    providers = set(available_onnx_providers(target))
    if target not in {"cpu", "intel", "amd", "directml"} and "CUDAExecutionProvider" in providers:
        return "cuda", env_info
    return "cpu", env_info


def acceleration_report(preference: str | None = None) -> dict[str, Any]:
    target = normalize_acceleration_preference(preference)
    env_info = prepare_acceleration_env(target)
    providers = available_onnx_providers(target)
    selected_providers, selected_device, selected_provider = select_onnx_execution_providers(
        prefer_gpu=target != "cpu",
        preference=target,
    )
    report: dict[str, Any] = {
        "preference": target,
        "onnxruntime_providers": providers,
        "selected_provider": selected_provider,
        "selected_providers": selected_providers,
        "selected_device": selected_device,
        "nvidia_smi": shutil.which("nvidia-smi"),
        "cuda_path": os.environ.get("CUDA_PATH"),
        "cctv_cuda_path": os.environ.get("CCTV_CUDA_PATH"),
        "cuda_root": str(env_info.get("cuda_root")) if env_info.get("cuda_root") else None,
        "onnxruntime_capi": str(env_info.get("onnxruntime_capi")) if env_info.get("onnxruntime_capi") else None,
        "torch_lib": str(env_info.get("torch_lib")) if env_info.get("torch_lib") else None,
        "nvidia_bins": [str(path) for path in env_info.get("nvidia_bins", [])],
        "registered_dll_dirs": [str(path) for path in _REGISTERED_DLL_DIRS],
    }
    if os.name == "posix":
        report["dev_dri"] = Path("/dev/dri").exists()
        report["dev_kfd"] = Path("/dev/kfd").exists()
    return report


def log_acceleration_report(target_logger: logging.Logger | None = None, preference: str | None = None) -> dict[str, Any]:
    report = acceleration_report(preference)
    out = target_logger or logger
    out.info(
        "Acceleration preference=%s selected=%s provider=%s available=%s cuda_root=%s nvidia_smi=%s",
        report["preference"],
        report["selected_device"],
        report["selected_provider"],
        ",".join(report["onnxruntime_providers"]) or "none",
        report.get("cuda_root") or report.get("cuda_path") or "not-found",
        report.get("nvidia_smi") or "not-found",
    )
    if report.get("selected_device") == "cpu" and report.get("preference") != "cpu":
        out.warning(
            "GPU acceleration is not active; fallback to CPU. registered_dll_dirs=%s",
            ";".join(report.get("registered_dll_dirs") or []) or "none",
        )
    return report


def prepare_onnxruntime_cuda_env() -> dict[str, Path | list[Path] | None]:
    torch_lib = _find_torch_lib_dir()
    ort_capi = _find_onnxruntime_capi_dir()
    nvidia_bins = _iter_nvidia_bin_dirs()
    dll_dirs: list[Path] = []
    if ort_capi is not None:
        dll_dirs.append(ort_capi)
    dll_dirs.extend(nvidia_bins)
    if torch_lib is not None:
        dll_dirs.append(torch_lib)
    register_dll_dirs(dll_dirs)
    return {
        "torch_lib": torch_lib,
        "onnxruntime_capi": ort_capi,
        "nvidia_bins": nvidia_bins,
    }


def _copy_onnxruntime_provider_dlls() -> None:
    ort_capi = _find_onnxruntime_capi_dir()
    mmdeploy_dir = _find_mmdeploy_runtime_dir()
    if ort_capi is None or mmdeploy_dir is None:
        return
    for dll_name in ("onnxruntime_providers_shared.dll", "onnxruntime_providers_cuda.dll"):
        src = ort_capi / dll_name
        dst = mmdeploy_dir / dll_name
        if not src.exists():
            continue
        try:
            if not dst.exists() or src.stat().st_size != dst.stat().st_size:
                shutil.copy2(src, dst)
        except OSError:
            logger.debug("Failed to stage %s for MMDeploy runtime", dll_name, exc_info=True)


def prepare_mmdeploy_cuda_env() -> Path | None:
    cuda_root = _find_cuda_runtime_root()
    ort_capi = _find_onnxruntime_capi_dir()
    mmdeploy_dir = _find_mmdeploy_runtime_dir()
    torch_lib = _find_torch_lib_dir()
    dll_dirs = _iter_nvidia_bin_dirs()
    if cuda_root is not None:
        os.environ["CUDA_PATH"] = str(cuda_root)
        dll_dirs.insert(0, cuda_root / "bin")
    if ort_capi is not None:
        dll_dirs.insert(0, ort_capi)
    if mmdeploy_dir is not None:
        dll_dirs.insert(0, mmdeploy_dir)
    if torch_lib is not None:
        dll_dirs.append(torch_lib)
    _copy_onnxruntime_provider_dlls()
    register_dll_dirs(dll_dirs)
    return cuda_root
