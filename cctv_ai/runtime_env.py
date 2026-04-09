from __future__ import annotations

import logging
import os
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
    env_root = os.environ.get("CUDA_PATH")
    if env_root:
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
    nvidia_bins = _iter_nvidia_bin_dirs()
    dll_dirs: list[Path] = []
    dll_dirs.extend(nvidia_bins)
    if torch_lib is not None:
        dll_dirs.append(torch_lib)
    register_dll_dirs(dll_dirs)
    return {
        "torch_lib": torch_lib,
        "nvidia_bins": nvidia_bins,
    }


def prepare_mmdeploy_cuda_env() -> Path | None:
    cuda_root = _find_cuda_runtime_root()
    dll_dirs = _iter_nvidia_bin_dirs()
    if cuda_root is not None:
        os.environ["CUDA_PATH"] = str(cuda_root)
        dll_dirs.insert(0, cuda_root / "bin")
    register_dll_dirs(dll_dirs)
    return cuda_root
