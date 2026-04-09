from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path


def _package_dir(module_name: str) -> Path:
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        raise RuntimeError(f"Module not found: {module_name}")
    if spec.submodule_search_locations:
        return Path(next(iter(spec.submodule_search_locations))).resolve()
    if spec.origin is None:
        raise RuntimeError(f"Cannot resolve module path: {module_name}")
    return Path(spec.origin).resolve().parent


def main() -> int:
    ort_dir = _package_dir("onnxruntime") / "capi"
    mmdeploy_dir = _package_dir("mmdeploy_runtime")

    copied = []
    for dll_name in ("onnxruntime_providers_shared.dll", "onnxruntime_providers_cuda.dll"):
        src = ort_dir / dll_name
        dst = mmdeploy_dir / dll_name
        if not src.exists():
            raise FileNotFoundError(f"Missing ONNX Runtime GPU provider DLL: {src}")
        if not dst.exists() or src.stat().st_size != dst.stat().st_size:
            shutil.copy2(src, dst)
            copied.append(dst.name)

    if copied:
        print("Prepared GPU runtime:", ", ".join(copied))
    else:
        print("GPU runtime already prepared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
