from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_DLL_DIR_HANDLES: list[object] = []


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
        registered.append(path)
    return registered


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
