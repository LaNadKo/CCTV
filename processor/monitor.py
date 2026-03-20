"""System metrics collector for processor dashboard."""
from __future__ import annotations

import platform
import time
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class Metrics:
    cpu_percent: float = 0.0
    ram_total_gb: float = 0.0
    ram_used_gb: float = 0.0
    ram_percent: float = 0.0
    gpu_name: str | None = None
    gpu_util_percent: float | None = None
    gpu_mem_used_mb: float | None = None
    gpu_mem_total_mb: float | None = None
    gpu_temp_c: float | None = None
    net_sent_mbps: float = 0.0
    net_recv_mbps: float = 0.0
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    active_cameras: int = 0
    uptime_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class SystemMonitor:
    def __init__(self):
        self._start_time = time.time()
        self._last_net_io = None
        self._last_net_time = None
        self._psutil = None
        try:
            import psutil
            self._psutil = psutil
        except ImportError:
            pass

    def collect(self, active_cameras: int = 0) -> Metrics:
        m = Metrics(
            active_cameras=active_cameras,
            uptime_seconds=time.time() - self._start_time,
        )
        self._collect_cpu_ram(m)
        self._collect_gpu(m)
        self._collect_network(m)
        self._collect_disk(m)
        return m

    def _collect_cpu_ram(self, m: Metrics):
        if not self._psutil:
            return
        m.cpu_percent = self._psutil.cpu_percent(interval=0.1)
        vm = self._psutil.virtual_memory()
        m.ram_total_gb = round(vm.total / (1024 ** 3), 2)
        m.ram_used_gb = round(vm.used / (1024 ** 3), 2)
        m.ram_percent = vm.percent

    def _collect_gpu(self, m: Metrics):
        # Try NVIDIA via pynvml
        try:
            import pynvml
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            m.gpu_name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(m.gpu_name, bytes):
                m.gpu_name = m.gpu_name.decode()
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            m.gpu_util_percent = util.gpu
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            m.gpu_mem_used_mb = round(mem.used / (1024 ** 2), 1)
            m.gpu_mem_total_mb = round(mem.total / (1024 ** 2), 1)
            try:
                m.gpu_temp_c = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:
                pass
            pynvml.nvmlShutdown()
            return
        except Exception:
            pass
        # Fallback: try torch
        try:
            import torch
            if torch.cuda.is_available():
                m.gpu_name = torch.cuda.get_device_name(0)
                m.gpu_mem_used_mb = round(torch.cuda.memory_allocated(0) / (1024 ** 2), 1)
                m.gpu_mem_total_mb = round(torch.cuda.get_device_properties(0).total_mem / (1024 ** 2), 1)
        except Exception:
            pass

    def _collect_network(self, m: Metrics):
        if not self._psutil:
            return
        now = time.time()
        counters = self._psutil.net_io_counters()
        if self._last_net_io and self._last_net_time:
            dt = now - self._last_net_time
            if dt > 0:
                m.net_sent_mbps = round((counters.bytes_sent - self._last_net_io.bytes_sent) * 8 / dt / 1_000_000, 2)
                m.net_recv_mbps = round((counters.bytes_recv - self._last_net_io.bytes_recv) * 8 / dt / 1_000_000, 2)
        self._last_net_io = counters
        self._last_net_time = now

    def _collect_disk(self, m: Metrics):
        if not self._psutil:
            return
        try:
            usage = self._psutil.disk_usage("/")
        except Exception:
            try:
                usage = self._psutil.disk_usage("C:\\")
            except Exception:
                return
        m.disk_total_gb = round(usage.total / (1024 ** 3), 2)
        m.disk_used_gb = round(usage.used / (1024 ** 3), 2)


def get_system_info() -> dict:
    """One-time system info for registration."""
    system = platform.system()
    release = platform.release()
    version = platform.version()
    pretty_os = f"{system} {release}"
    if system == "Windows":
        try:
            build = int(version.split(".")[-1])
        except Exception:
            build = 0
        if release == "10" and build >= 22000:
            pretty_os = "Windows 11"

    info = {
        "os": pretty_os,
        "arch": platform.machine(),
        "python": platform.python_version(),
        "hostname": platform.node(),
        "platform_version": version,
    }
    try:
        import psutil
        info["cpu_count"] = psutil.cpu_count(logical=True)
        info["ram_gb"] = round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except ImportError:
        pass
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        gpu_name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(gpu_name, bytes):
            gpu_name = gpu_name.decode()
        info["gpu"] = gpu_name
        pynvml.nvmlShutdown()
    except Exception:
        pass
    torch_available = False
    try:
        import torch
        torch_available = True
        info["torch"] = torch.__version__
        if torch.cuda.is_available():
            info["gpu"] = torch.cuda.get_device_name(0)
            info["cuda"] = torch.version.cuda
            info["inference_device"] = "cuda"
        else:
            info["inference_device"] = "cpu"
    except ImportError:
        pass
    if not torch_available:
        info["inference_device"] = "cpu"
    if "inference_device" not in info:
        info["inference_device"] = "cpu"
    return info
