from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import settings
from app.schemas.ruview import RuViewBridgeStatus, RuViewNodeStatus

CSI_MAGIC = 0xC5110001
VITALS_MAGIC = 0xC5110002
RF_LINK_MAGIC = 0xC5110101
RF_HEALTH_MAGIC = 0xC5110102

logger = logging.getLogger(__name__)


@dataclass
class _NodeAggregate:
    node_id: int
    label: str
    source_ip: str | None = None
    source_port: int | None = None
    packet_count: int = 0
    last_seen: datetime | None = None
    last_packet_type: str | None = None
    last_sequence: int | None = None
    last_rssi: int | None = None
    channel: int | None = None
    payload_bytes: int | None = None
    packet_times: deque[float] = field(default_factory=lambda: deque(maxlen=240))


class RuViewBridge:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._forward_socket: socket.socket | None = None
        self._started_at: datetime | None = None
        self._last_packet_at: datetime | None = None
        self._last_csi_packet_at: datetime | None = None
        self._last_error: str | None = None
        self._last_upstream_error: str | None = None
        self._last_upstream_forward_at: datetime | None = None
        self._last_forward_monotonic = 0.0
        self._packet_count = 0
        self._csi_packet_count = 0
        self._vitals_packet_count = 0
        self._health_packet_count = 0
        self._unknown_packet_count = 0
        self._dropped_csi_packet_count = 0
        self._upstream_forward_count = 0
        self._nodes: dict[int, _NodeAggregate] = {}
        self._ip_node_ids: dict[str, int] = {}
        self._last_csi_accept_by_node: dict[int, float] = {}

    def start(self) -> None:
        if not settings.ruview_bridge_enabled:
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="ruview-udp-bridge", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        sock = self._socket
        self._socket = None
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        forward_sock = self._forward_socket
        self._forward_socket = None
        if forward_sock:
            try:
                forward_sock.close()
            except OSError:
                pass
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.5)

    def reset(self) -> None:
        with self._lock:
            self._last_packet_at = None
            self._last_csi_packet_at = None
            self._last_error = None
            self._last_upstream_error = None
            self._last_upstream_forward_at = None
            self._last_forward_monotonic = 0.0
            self._packet_count = 0
            self._csi_packet_count = 0
            self._vitals_packet_count = 0
            self._health_packet_count = 0
            self._unknown_packet_count = 0
            self._dropped_csi_packet_count = 0
            self._upstream_forward_count = 0
            self._nodes.clear()
            self._ip_node_ids.clear()
            self._last_csi_accept_by_node.clear()

    def status(self) -> RuViewBridgeStatus:
        now = datetime.now(timezone.utc)
        stale_after = max(1.0, float(settings.ruview_stale_after_seconds))
        with self._lock:
            nodes = [
                RuViewNodeStatus(
                    node_id=node.node_id,
                    label=node.label,
                    source_ip=node.source_ip,
                    source_port=node.source_port,
                    online=not _is_stale(now, node.last_seen, stale_after),
                    last_seen=node.last_seen,
                    packet_count=node.packet_count,
                    packet_rate_hz=_packet_rate(node.packet_times),
                    last_packet_type=node.last_packet_type,
                    last_sequence=node.last_sequence,
                    last_rssi=node.last_rssi,
                    channel=node.channel,
                    payload_bytes=node.payload_bytes,
                )
                for node in sorted(self._nodes.values(), key=lambda item: item.node_id)
            ]
            return RuViewBridgeStatus(
                enabled=settings.ruview_bridge_enabled,
                listening=bool(self._thread and self._thread.is_alive()),
                bind=settings.ruview_udp_bind,
                port=settings.ruview_udp_port,
                started_at=self._started_at,
                last_packet_at=self._last_packet_at,
                last_csi_packet_at=self._last_csi_packet_at,
                live_csi=not _is_stale(now, self._last_csi_packet_at, stale_after),
                packet_count=self._packet_count,
                csi_packet_count=self._csi_packet_count,
                vitals_packet_count=self._vitals_packet_count,
                health_packet_count=self._health_packet_count,
                unknown_packet_count=self._unknown_packet_count,
                dropped_csi_packet_count=self._dropped_csi_packet_count,
                upstream_forward_enabled=settings.ruview_upstream_forward_enabled,
                upstream_forward_host=settings.ruview_upstream_udp_host,
                upstream_forward_port=settings.ruview_upstream_udp_port,
                upstream_forward_count=self._upstream_forward_count,
                last_upstream_forward_at=self._last_upstream_forward_at,
                last_upstream_error=self._last_upstream_error,
                last_error=self._last_error,
                nodes=nodes,
            )

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)
        try:
            sock.bind((settings.ruview_udp_bind, int(settings.ruview_udp_port)))
        except OSError as exc:
            with self._lock:
                self._last_error = str(exc)
            logger.exception("Failed to bind RuView UDP bridge")
            return

        with self._lock:
            self._socket = sock
            self._started_at = datetime.now(timezone.utc)
            self._last_error = None
        logger.info("RuView UDP bridge listening on %s:%s", settings.ruview_udp_bind, settings.ruview_udp_port)

        while not self._stop_event.is_set():
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            self._handle_packet(data, addr)

    def _handle_packet(self, data: bytes, addr: tuple[str, int]) -> None:
        now = datetime.now(timezone.utc)
        packet_monotonic = time.monotonic()
        packet_type, node_id, sequence, rssi, channel, payload_bytes = _parse_packet(data)
        with self._lock:
            resolved_id = self._resolve_node_id(addr[0], node_id)
            if not self._accept_packet_locked(packet_type, resolved_id, packet_monotonic):
                return
            self._packet_count += 1
            self._last_packet_at = now
            if packet_type == "csi":
                self._csi_packet_count += 1
                self._last_csi_packet_at = now
            elif packet_type == "vitals":
                self._vitals_packet_count += 1
            elif packet_type == "health":
                self._health_packet_count += 1
            else:
                self._unknown_packet_count += 1

            node = self._nodes.get(resolved_id)
            if node is None:
                node = _NodeAggregate(node_id=resolved_id, label=f"ESP32-{resolved_id}")
                self._nodes[resolved_id] = node
            node.source_ip = addr[0]
            node.source_port = addr[1]
            node.packet_count += 1
            node.last_seen = now
            node.last_packet_type = packet_type
            node.last_sequence = sequence
            node.last_rssi = rssi
            node.channel = channel
            node.payload_bytes = payload_bytes
            node.packet_times.append(packet_monotonic)

        try:
            from app.services.ruview_calibration import record_csi_packet

            record_csi_packet(
                packet_type=packet_type,
                node_id=resolved_id,
                source_ip=addr[0],
                source_port=addr[1],
                sequence=sequence,
                rssi=rssi,
                channel=channel,
                payload_bytes=payload_bytes,
                raw=data,
                received_at=now,
            )
        except Exception:
            logger.exception("Failed to write RuView calibration CSI sample")

        self._forward_to_upstream(data, packet_monotonic)

    def _accept_packet_locked(self, packet_type: str, node_id: int, now: float) -> bool:
        if packet_type != "csi":
            return True
        min_interval = max(0.0, float(settings.ruview_csi_min_interval_seconds))
        if min_interval <= 0:
            return True
        last_accept = self._last_csi_accept_by_node.get(node_id, 0.0)
        if now - last_accept < min_interval:
            self._dropped_csi_packet_count += 1
            return False
        self._last_csi_accept_by_node[node_id] = now
        return True

    def _resolve_node_id(self, source_ip: str, raw_node_id: int | None) -> int:
        configured = _configured_node_ips()
        if source_ip in configured:
            return configured[source_ip]
        if raw_node_id and raw_node_id > 0:
            return int(raw_node_id)
        if source_ip not in self._ip_node_ids:
            used = set(self._ip_node_ids.values()) | set(configured.values()) | set(self._nodes.keys())
            node_id = 1
            while node_id in used:
                node_id += 1
            self._ip_node_ids[source_ip] = node_id
        return self._ip_node_ids[source_ip]

    def _forward_to_upstream(self, data: bytes, now: float) -> None:
        if not settings.ruview_upstream_forward_enabled:
            return
        min_interval = max(0.0, float(settings.ruview_upstream_forward_min_interval_seconds))
        with self._lock:
            if min_interval and now - self._last_forward_monotonic < min_interval:
                return
            self._last_forward_monotonic = now
        try:
            if self._forward_socket is None:
                self._forward_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._forward_socket.sendto(
                data,
                (settings.ruview_upstream_udp_host, int(settings.ruview_upstream_udp_port)),
            )
            with self._lock:
                self._upstream_forward_count += 1
                self._last_upstream_forward_at = datetime.now(timezone.utc)
                self._last_upstream_error = None
        except OSError as exc:
            with self._lock:
                self._last_upstream_error = str(exc)


def _parse_packet(data: bytes) -> tuple[str, int | None, int | None, int | None, int | None, int | None]:
    if len(data) < 4:
        return "unknown", None, None, None, None, len(data)
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic == CSI_MAGIC and len(data) >= 20:
        node_id = data[4]
        sequence = struct.unpack_from("<I", data, 12)[0]
        rssi = struct.unpack_from("<b", data, 16)[0]
        channel = None
        payload_bytes = max(0, len(data) - 20)
        return "csi", node_id, sequence, rssi, channel, payload_bytes
    if magic == VITALS_MAGIC and len(data) >= 28:
        node_id = data[4]
        rssi = struct.unpack_from("<b", data, 12)[0]
        return "vitals", node_id, None, rssi, None, max(0, len(data) - 28)
    if magic == RF_LINK_MAGIC and len(data) >= 24:
        rx_node_id = data[5]
        sequence = struct.unpack_from("<I", data, 8)[0]
        rssi = struct.unpack_from("<b", data, 16)[0]
        channel = data[18]
        payload_len = struct.unpack_from("<H", data, 20)[0]
        return "csi", rx_node_id, sequence, rssi, channel, payload_len
    if magic == RF_HEALTH_MAGIC and len(data) >= 20:
        node_id = data[5]
        sequence = struct.unpack_from("<I", data, 8)[0]
        rssi = struct.unpack_from("<b", data, 16)[0]
        channel = data[17]
        return "health", node_id, sequence, rssi, channel, max(0, len(data) - 20)
    return "unknown", None, None, None, None, len(data)


def _configured_node_ips() -> dict[str, int]:
    result: dict[str, int] = {}
    next_id = 1
    for raw_part in settings.ruview_node_ips.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "=" in part:
            raw_id, ip = part.split("=", 1)
            try:
                node_id = int(raw_id.strip())
            except ValueError:
                node_id = next_id
            result[ip.strip()] = node_id
            next_id = max(next_id, node_id + 1)
        else:
            result[part] = next_id
            next_id += 1
    return result


def _packet_rate(times: deque[float]) -> float:
    if len(times) < 2:
        return 0.0
    now = time.monotonic()
    recent = [value for value in times if now - value <= 5.0]
    if len(recent) < 2:
        return 0.0
    duration = max(0.001, recent[-1] - recent[0])
    return round((len(recent) - 1) / duration, 2)


def _is_stale(now: datetime, last_seen: datetime | None, stale_after: float) -> bool:
    if last_seen is None:
        return True
    return (now - last_seen).total_seconds() > stale_after


_bridge = RuViewBridge()


def start_ruview_bridge() -> None:
    _bridge.start()


def stop_ruview_bridge() -> None:
    _bridge.stop()


def reset_ruview_bridge() -> None:
    _bridge.reset()


def get_ruview_bridge_status() -> RuViewBridgeStatus:
    return _bridge.status()


def has_recent_ruview_csi() -> bool:
    status = _bridge.status()
    return status.live_csi
