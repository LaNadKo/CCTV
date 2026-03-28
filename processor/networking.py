"""Networking helpers for processor reachability."""
from __future__ import annotations

import ipaddress
import os
import socket
from typing import Iterable


_VIRTUAL_IFACE_MARKERS = (
    "docker",
    "wsl",
    "hyper-v",
    "vethernet",
    "virtual",
    "vmware",
    "vbox",
    "loopback",
    "teredo",
    "tunnel",
    "hiddify",
)


def _is_candidate_ipv4(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if ip.version != 4:
        return False
    if ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return False
    return True


def _rank_ip(value: str) -> int:
    ip = ipaddress.ip_address(value)
    if ip.is_private:
        text = str(ip)
        if text.startswith("192.168."):
            return 0
        if text.startswith("10."):
            return 1
        if text.startswith("172."):
            return 2
        return 3
    return 10


def _iter_interface_ipv4() -> Iterable[str]:
    try:
        import psutil
    except Exception:
        psutil = None

    if not psutil:
        return []

    results: list[tuple[int, str]] = []
    for iface_name, addrs in psutil.net_if_addrs().items():
        lowered = iface_name.lower()
        if any(marker in lowered for marker in _VIRTUAL_IFACE_MARKERS):
            continue
        for addr in addrs:
            value = getattr(addr, "address", None)
            if not value or not _is_candidate_ipv4(value):
                continue
            results.append((_rank_ip(value), value))

    results.sort(key=lambda item: (item[0], item[1]))
    return [value for _, value in results]


def detect_advertised_ip(preferred: str | None = None, backend_url: str | None = None) -> str | None:
    """Return the best host IP for backend -> processor media callbacks."""
    explicit = preferred or os.environ.get("PROCESSOR_ADVERTISED_IP", "")
    explicit = explicit.strip()
    if explicit and _is_candidate_ipv4(explicit):
        return explicit

    iface_candidates = list(_iter_interface_ipv4())
    if iface_candidates:
        return iface_candidates[0]

    target_host = None
    if backend_url:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(backend_url)
            if parsed.hostname and parsed.hostname not in {"127.0.0.1", "localhost"}:
                target_host = parsed.hostname
        except Exception:
            target_host = None

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((target_host or "8.8.8.8", 80))
        candidate = sock.getsockname()[0]
        if _is_candidate_ipv4(candidate):
            return candidate
    except Exception:
        pass
    finally:
        sock.close()

    try:
        for _, _, _, _, sockaddr in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidate = sockaddr[0]
            if _is_candidate_ipv4(candidate):
                return candidate
    except Exception:
        pass

    return None
