"""UDP bridge for RuView ESP32-S3 CSI firmware."""
from __future__ import annotations

import http.client
import socket
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import sqrt

from app.config import settings
from app.schemas.ruview import (
    RuViewBridgeStatus,
    RuViewCsiLinkState,
    RuViewCsiNodeState,
    RuViewRfNodeHealthState,
    RuViewTrackedPerson,
    RuViewVitalsNodeState,
)
from app.services.rf_room import load_rf_room_layout

CSI_MAGIC = 0xC5110001
VITALS_MAGIC = 0xC5110002
RF_LINK_MAGIC = 0xC5110101
RF_HEALTH_MAGIC = 0xC5110102
RF_FLAG_ESPNOW = 1 << 1
RF_FLAG_UNKNOWN_PEER = 1 << 3
RF_FLAG_INFERRED_TX = 1 << 4


@dataclass
class _CsiNode:
    node_id: int
    raw_node_id: int
    physical_label: str | None
    layout_node_id: str | None
    source_ip: str
    source_port: int
    packet_count: int = 0
    bytes_total: int = 0
    last_seen_at: datetime | None = None
    last_sequence: int | None = None
    frequency_mhz: int | None = None
    antennas: int | None = None
    subcarriers: int | None = None
    rssi: int | None = None
    noise_floor: int | None = None
    last_payload_bytes: int | None = None
    power_window: deque[tuple[datetime, float, float, int]] = field(default_factory=lambda: deque(maxlen=600))


@dataclass
class _VitalsNode:
    node_id: int
    raw_node_id: int
    physical_label: str | None
    layout_node_id: str | None
    source_ip: str
    source_port: int
    packet_count: int = 0
    last_seen_at: datetime | None = None
    presence: bool = False
    fall: bool = False
    motion: bool = False
    breathing_bpm: float | None = None
    heart_bpm: float | None = None
    rssi: int | None = None
    detected_persons: int | None = None
    motion_energy: float | None = None
    presence_score: float | None = None
    device_uptime_ms: int | None = None


@dataclass
class _CsiLink:
    rx_node_id: int
    tx_node_id: int
    rx_physical_label: str | None
    tx_physical_label: str | None
    rx_layout_node_id: str | None
    tx_layout_node_id: str | None
    tx_mac: str | None
    source_ip: str
    source_port: int
    packet_count: int = 0
    bytes_total: int = 0
    last_seen_at: datetime | None = None
    last_sequence: int | None = None
    channel: int | None = None
    rssi: int | None = None
    noise_floor: int | None = None
    flags: int = 0
    last_payload_bytes: int | None = None
    power_window: deque[tuple[datetime, float, float, int]] = field(default_factory=lambda: deque(maxlen=600))


@dataclass
class _RfNodeHealth:
    node_id: int
    physical_label: str | None
    layout_node_id: str | None
    source_ip: str
    source_port: int
    packet_count: int = 0
    last_seen_at: datetime | None = None
    last_sequence: int | None = None
    uptime_ms: int | None = None
    rssi: int | None = None
    channel: int | None = None
    tdm_slot: int | None = None
    tdm_total: int | None = None
    peer_count: int | None = None
    dropped_csi_samples: int | None = None


class RuViewBridge:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stimulator_thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._started_at: datetime | None = None
        self._last_packet_at: datetime | None = None
        self._packet_count = 0
        self._csi_packet_count = 0
        self._vitals_packet_count = 0
        self._unknown_packet_count = 0
        self._last_error: str | None = None
        self._stimulus_count = 0
        self._last_stimulus_at: datetime | None = None
        self._last_stimulus_error: str | None = None
        self._stimulus_source_ip: str | None = None
        self._stimulus_source_deadline = 0.0
        self._upstream_socket: socket.socket | None = None
        self._upstream_forward_count = 0
        self._last_upstream_forward_at: datetime | None = None
        self._last_upstream_forward_error: str | None = None
        self._last_upstream_forward_monotonic = 0.0
        self._csi_nodes: dict[int, _CsiNode] = {}
        self._csi_links: dict[tuple[int, int], _CsiLink] = {}
        self._rf_health_nodes: dict[int, _RfNodeHealth] = {}
        self._vitals_nodes: dict[int, _VitalsNode] = {}

    def start(self) -> None:
        if not settings.ruview_bridge_enabled:
            return
        self._stop.clear()
        if not self._thread or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="ruview-udp-bridge", daemon=True)
            self._thread.start()
        self._start_stimulator()

    def stop(self) -> None:
        self._stop.set()
        sock = self._socket
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        upstream_socket = self._upstream_socket
        if upstream_socket is not None:
            try:
                upstream_socket.close()
            except OSError:
                pass
            self._upstream_socket = None
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        stimulator_thread = self._stimulator_thread
        if stimulator_thread and stimulator_thread.is_alive():
            stimulator_thread.join(timeout=2.0)

    def reset(self) -> None:
        with self._lock:
            self._last_packet_at = None
            self._packet_count = 0
            self._csi_packet_count = 0
            self._vitals_packet_count = 0
            self._unknown_packet_count = 0
            self._last_error = None
            self._stimulus_count = 0
            self._last_stimulus_at = None
            self._last_stimulus_error = None
            self._stimulus_source_ip = None
            self._stimulus_source_deadline = 0.0
            self._upstream_forward_count = 0
            self._last_upstream_forward_at = None
            self._last_upstream_forward_error = None
            self._last_upstream_forward_monotonic = 0.0
            self._csi_nodes.clear()
            self._csi_links.clear()
            self._rf_health_nodes.clear()
            self._vitals_nodes.clear()

    def status(self) -> RuViewBridgeStatus:
        now = datetime.now(timezone.utc)
        stale_after = settings.ruview_stale_after_seconds
        with self._lock:
            csi_nodes = [
                RuViewCsiNodeState(
                    node_id=node.node_id,
                    physical_label=node.physical_label,
                    layout_node_id=node.layout_node_id,
                    raw_node_id=node.raw_node_id,
                    source_ip=node.source_ip,
                    source_port=node.source_port,
                    packet_count=node.packet_count,
                    bytes_total=node.bytes_total,
                    last_seen_at=node.last_seen_at,
                    stale=_is_stale(now, node.last_seen_at, stale_after),
                    last_sequence=node.last_sequence,
                    frequency_mhz=node.frequency_mhz,
                    antennas=node.antennas,
                    subcarriers=node.subcarriers,
                    rssi=node.rssi,
                    noise_floor=node.noise_floor,
                    last_payload_bytes=node.last_payload_bytes,
                    window_packet_count=len(node.power_window),
                    packet_rate_hz=_packet_rate_hz(node.power_window),
                    mean_rssi=_mean([item[3] for item in node.power_window]),
                    mean_power=_mean([item[1] for item in node.power_window]),
                    power_std=_mean([item[2] for item in node.power_window]),
                    last_mean_power=node.power_window[-1][1] if node.power_window else None,
                )
                for node in sorted(self._csi_nodes.values(), key=lambda item: item.node_id)
            ]
            vitals_nodes = [
                RuViewVitalsNodeState(
                    node_id=node.node_id,
                    physical_label=node.physical_label,
                    layout_node_id=node.layout_node_id,
                    raw_node_id=node.raw_node_id,
                    source_ip=node.source_ip,
                    source_port=node.source_port,
                    packet_count=node.packet_count,
                    last_seen_at=node.last_seen_at,
                    stale=_is_stale(now, node.last_seen_at, stale_after),
                    presence=node.presence,
                    fall=node.fall,
                    motion=node.motion,
                    breathing_bpm=node.breathing_bpm,
                    heart_bpm=node.heart_bpm,
                    rssi=node.rssi,
                    detected_persons=node.detected_persons,
                    motion_energy=node.motion_energy,
                    presence_score=node.presence_score,
                    device_uptime_ms=node.device_uptime_ms,
                )
                for node in sorted(self._vitals_nodes.values(), key=lambda item: item.node_id)
            ]
            csi_links = [
                RuViewCsiLinkState(
                    rx_node_id=link.rx_node_id,
                    tx_node_id=link.tx_node_id,
                    rx_physical_label=link.rx_physical_label,
                    tx_physical_label=link.tx_physical_label,
                    rx_layout_node_id=link.rx_layout_node_id,
                    tx_layout_node_id=link.tx_layout_node_id,
                    tx_mac=link.tx_mac,
                    source_ip=link.source_ip,
                    source_port=link.source_port,
                    packet_count=link.packet_count,
                    bytes_total=link.bytes_total,
                    last_seen_at=link.last_seen_at,
                    stale=_is_stale(now, link.last_seen_at, stale_after),
                    last_sequence=link.last_sequence,
                    channel=link.channel,
                    rssi=link.rssi,
                    noise_floor=link.noise_floor,
                    flags=link.flags,
                    pairwise=_is_pairwise_link(link),
                    inferred=bool(link.flags & RF_FLAG_INFERRED_TX),
                    unknown_peer=bool(link.flags & RF_FLAG_UNKNOWN_PEER) or link.tx_node_id <= 0,
                    link_age_ms=_age_ms(now, link.last_seen_at),
                    quality_score=_link_quality_score(now, link, stale_after),
                    last_payload_bytes=link.last_payload_bytes,
                    window_packet_count=len(link.power_window),
                    packet_rate_hz=_packet_rate_hz(link.power_window),
                    mean_rssi=_mean([item[3] for item in link.power_window]),
                    mean_power=_mean([item[1] for item in link.power_window]),
                    power_std=_mean([item[2] for item in link.power_window]),
                    last_mean_power=link.power_window[-1][1] if link.power_window else None,
                )
                for link in sorted(self._csi_links.values(), key=lambda item: (item.rx_node_id, item.tx_node_id))
            ]
            rf_health = [
                RuViewRfNodeHealthState(
                    node_id=node.node_id,
                    physical_label=node.physical_label,
                    layout_node_id=node.layout_node_id,
                    source_ip=node.source_ip,
                    source_port=node.source_port,
                    packet_count=node.packet_count,
                    last_seen_at=node.last_seen_at,
                    stale=_is_stale(now, node.last_seen_at, stale_after),
                    last_sequence=node.last_sequence,
                    uptime_ms=node.uptime_ms,
                    rssi=node.rssi,
                    channel=node.channel,
                    tdm_slot=node.tdm_slot,
                    tdm_total=node.tdm_total,
                    peer_count=node.peer_count,
                    dropped_csi_samples=node.dropped_csi_samples,
                )
                for node in sorted(self._rf_health_nodes.values(), key=lambda item: item.node_id)
            ]
            return RuViewBridgeStatus(
                enabled=settings.ruview_bridge_enabled,
                listening=bool(self._thread and self._thread.is_alive() and self._socket is not None),
                bind=settings.ruview_udp_bind,
                port=settings.ruview_udp_port,
                stimulator_enabled=settings.ruview_stimulator_enabled,
                stimulator_running=bool(self._stimulator_thread and self._stimulator_thread.is_alive()),
                stimulator_interval_seconds=settings.ruview_stimulator_interval_seconds,
                stimulus_count=self._stimulus_count,
                last_stimulus_at=self._last_stimulus_at,
                last_stimulus_error=self._last_stimulus_error,
                upstream_forward_enabled=settings.ruview_upstream_forward_enabled,
                upstream_forward_host=settings.ruview_upstream_udp_host if settings.ruview_upstream_forward_enabled else None,
                upstream_forward_port=settings.ruview_upstream_udp_port if settings.ruview_upstream_forward_enabled else None,
                upstream_forward_count=self._upstream_forward_count,
                last_upstream_forward_at=self._last_upstream_forward_at,
                last_upstream_forward_error=self._last_upstream_forward_error,
                started_at=self._started_at,
                last_packet_at=self._last_packet_at,
                packet_count=self._packet_count,
                csi_packet_count=self._csi_packet_count,
                vitals_packet_count=self._vitals_packet_count,
                unknown_packet_count=self._unknown_packet_count,
                last_error=self._last_error,
                nodes=csi_nodes,
                links=csi_links,
                rf_health=rf_health,
                vitals=vitals_nodes,
                tracked_persons=_tracked_persons_from_vitals(vitals_nodes),
            )

    def _run(self) -> None:
        self._started_at = datetime.now(timezone.utc)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((settings.ruview_udp_bind, settings.ruview_udp_port))
            sock.settimeout(0.5)
            self._socket = sock
            with self._lock:
                self._last_error = None

            while not self._stop.is_set():
                try:
                    data, addr = sock.recvfrom(8192)
                except socket.timeout:
                    continue
                except OSError as exc:
                    if not self._stop.is_set():
                        with self._lock:
                            self._last_error = str(exc)
                    break
                self._handle_packet(data, addr)
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
        finally:
            self._socket = None

    def _start_stimulator(self) -> None:
        if not settings.ruview_stimulator_enabled:
            return
        if self._stimulator_thread and self._stimulator_thread.is_alive():
            return
        self._stimulator_thread = threading.Thread(target=self._run_stimulator, name="ruview-stimulator", daemon=True)
        self._stimulator_thread.start()

    def _run_stimulator(self) -> None:
        while not self._stop.is_set():
            cycle_started = time.monotonic()
            try:
                nodes = list(load_rf_room_layout().nodes)
            except Exception as exc:
                with self._lock:
                    self._last_stimulus_error = str(exc)
                self._wait_next_stimulus(cycle_started)
                continue

            success_count = 0
            errors: list[str] = []
            for node in nodes:
                if self._stop.is_set():
                    break
                if not node.ip:
                    continue
                self._mark_stimulus_source(node.ip)
                ok, error = _stimulate_node(node.ip, settings.ruview_stimulator_timeout_seconds)
                if ok:
                    success_count += 1
                elif error:
                    errors.append(error)
                self._stop.wait(0.01)

            with self._lock:
                self._stimulus_count += success_count
                self._last_stimulus_at = datetime.now(timezone.utc)
                self._last_stimulus_error = _compact_errors(errors)

            self._wait_next_stimulus(cycle_started)

    def _mark_stimulus_source(self, ip: str) -> None:
        ttl = max(settings.ruview_stimulator_timeout_seconds * 2.0, 0.45)
        with self._lock:
            self._stimulus_source_ip = ip
            self._stimulus_source_deadline = time.monotonic() + ttl

    def _wait_next_stimulus(self, cycle_started: float) -> None:
        interval = max(settings.ruview_stimulator_interval_seconds, 0.05)
        elapsed = time.monotonic() - cycle_started
        self._stop.wait(max(0.0, interval - elapsed))

    def _handle_packet(self, data: bytes, addr: tuple[str, int]) -> None:
        now = datetime.now(timezone.utc)
        if len(data) < 4:
            with self._lock:
                self._unknown_packet_count += 1
            return

        magic = struct.unpack_from("<I", data, 0)[0]
        with self._lock:
            self._packet_count += 1
            self._last_packet_at = now
            if magic == CSI_MAGIC:
                self._csi_packet_count += 1
                self._parse_csi(data, addr, now)
                self._forward_csi_to_upstream(data, addr, now)
            elif magic == VITALS_MAGIC:
                self._vitals_packet_count += 1
                self._parse_vitals(data, addr, now)
                self._forward_raw_to_upstream(data, now)
            elif magic == RF_LINK_MAGIC:
                self._csi_packet_count += 1
                self._parse_rf_link(data, addr, now)
                self._forward_rf_link_to_upstream(data, addr, now)
            elif magic == RF_HEALTH_MAGIC:
                self._parse_rf_health(data, addr, now)
            else:
                self._unknown_packet_count += 1

    def _forward_rf_link_to_upstream(self, data: bytes, addr: tuple[str, int], now: datetime) -> None:
        if len(data) < 24:
            return

        rx_node_id = data[5]
        sequence = struct.unpack_from("<I", data, 8)[0]
        rssi = struct.unpack_from("<b", data, 16)[0]
        noise_floor = struct.unpack_from("<b", data, 17)[0]
        channel = data[18]
        payload_len = struct.unpack_from("<H", data, 20)[0]
        header_len = 24
        if data[4] >= 2 and len(data) >= 32:
            configured_header_len = struct.unpack_from("<H", data, 22)[0]
            header_len = configured_header_len if configured_header_len >= 32 else 32

        payload = data[header_len : min(len(data), header_len + payload_len)]
        if len(payload) < 2:
            return

        resolved, _identity_source_ip = self._resolve_packet_identity_locked(addr[0], rx_node_id)
        frequency_mhz = _frequency_mhz_for_channel(channel)
        packet = _build_ruview_adr018_packet(
            node_id=resolved[0] or rx_node_id or 1,
            sequence=sequence,
            frequency_mhz=frequency_mhz,
            rssi=rssi,
            noise_floor=noise_floor,
            payload=payload,
        )
        if packet is not None:
            self._forward_raw_to_upstream(packet, now)

    def _forward_csi_to_upstream(self, data: bytes, addr: tuple[str, int], now: datetime) -> None:
        if len(data) < 22:
            return

        raw_node_id = data[4]
        resolved, _identity_source_ip = self._resolve_packet_identity_locked(addr[0], raw_node_id)
        subcarriers = struct.unpack_from("<H", data, 6)[0]
        frequency_mhz = struct.unpack_from("<I", data, 8)[0]
        sequence = struct.unpack_from("<I", data, 12)[0]
        rssi = struct.unpack_from("<b", data, 16)[0]
        noise_floor = struct.unpack_from("<b", data, 17)[0]
        payload_len = max(0, min(len(data) - 20, subcarriers * 2))
        payload = data[20 : 20 + payload_len]
        packet = _build_ruview_adr018_packet(
            node_id=resolved[0] or raw_node_id or 1,
            sequence=sequence,
            frequency_mhz=frequency_mhz,
            rssi=rssi,
            noise_floor=noise_floor,
            payload=payload,
        )
        if packet is not None:
            self._forward_raw_to_upstream(packet, now)

    def _forward_raw_to_upstream(self, data: bytes, now: datetime) -> None:
        if not settings.ruview_upstream_forward_enabled:
            return

        current = time.monotonic()
        min_interval = max(float(settings.ruview_upstream_forward_min_interval_seconds), 0.0)
        if min_interval and current - self._last_upstream_forward_monotonic < min_interval:
            return

        try:
            if self._upstream_socket is None:
                self._upstream_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._upstream_socket.sendto(
                data,
                (settings.ruview_upstream_udp_host, int(settings.ruview_upstream_udp_port)),
            )
            self._upstream_forward_count += 1
            self._last_upstream_forward_at = now
            self._last_upstream_forward_error = None
            self._last_upstream_forward_monotonic = current
        except OSError as exc:
            self._last_upstream_forward_error = f"{settings.ruview_upstream_udp_host}:{settings.ruview_upstream_udp_port}: {exc}"

    def _parse_rf_link(self, data: bytes, addr: tuple[str, int], now: datetime) -> None:
        if len(data) < 24:
            self._unknown_packet_count += 1
            return

        rx_node_id = data[5]
        tx_node_id = data[6]
        flags = data[7]
        sequence = struct.unpack_from("<I", data, 8)[0]
        rssi = struct.unpack_from("<b", data, 16)[0]
        noise_floor = struct.unpack_from("<b", data, 17)[0]
        channel = data[18]
        payload_len = struct.unpack_from("<H", data, 20)[0]
        header_len = 24
        tx_mac = None
        if data[4] >= 2 and len(data) >= 32:
            configured_header_len = struct.unpack_from("<H", data, 22)[0]
            header_len = configured_header_len if configured_header_len >= 32 else 32
            tx_mac = _format_mac(data[24:30])
        payload = data[header_len : min(len(data), header_len + payload_len)]

        rx_resolved, identity_source_ip = self._resolve_packet_identity_locked(addr[0], rx_node_id)
        tx_resolved = _resolve_node_identity_by_id(tx_node_id)
        if tx_resolved[1] is None and tx_mac is not None:
            tx_resolved = _resolve_node_identity_by_mac(tx_mac)
        mean_power, power_std = _payload_power_stats(payload)

        self._upsert_node_aggregate(
            node_id=rx_resolved[0],
            raw_node_id=rx_node_id,
            physical_label=rx_resolved[1],
            layout_node_id=rx_resolved[2],
            source_ip=identity_source_ip,
            source_port=addr[1],
            now=now,
            sequence=sequence,
            frequency_mhz=2407 + channel * 5 if channel else None,
            antennas=None,
            subcarriers=payload_len // 2 if payload_len else None,
            rssi=rssi,
            noise_floor=noise_floor,
            payload_len=len(payload),
            mean_power=mean_power,
            power_std=power_std,
            bytes_total=len(data),
        )

        key = (rx_resolved[0], tx_resolved[0])
        link = self._csi_links.get(key)
        if link is None:
            link = _CsiLink(
                rx_node_id=rx_resolved[0],
                tx_node_id=tx_resolved[0],
                rx_physical_label=rx_resolved[1],
                tx_physical_label=tx_resolved[1],
                rx_layout_node_id=rx_resolved[2],
                tx_layout_node_id=tx_resolved[2],
                tx_mac=tx_mac,
                source_ip=identity_source_ip,
                source_port=addr[1],
            )
            self._csi_links[key] = link

        link.rx_physical_label = rx_resolved[1]
        link.tx_physical_label = tx_resolved[1]
        link.rx_layout_node_id = rx_resolved[2]
        link.tx_layout_node_id = tx_resolved[2]
        link.tx_mac = tx_mac or link.tx_mac
        link.source_ip = identity_source_ip
        link.source_port = addr[1]
        link.packet_count += 1
        link.bytes_total += len(data)
        link.last_seen_at = now
        link.last_sequence = sequence
        link.channel = channel
        link.rssi = rssi
        link.noise_floor = noise_floor
        link.flags = flags
        link.last_payload_bytes = len(payload)
        if mean_power is not None and power_std is not None:
            link.power_window.append((now, mean_power, power_std, rssi))

    def _parse_rf_health(self, data: bytes, addr: tuple[str, int], now: datetime) -> None:
        if len(data) < 20:
            self._unknown_packet_count += 1
            return

        node_id = data[5]
        tdm_slot = data[6]
        tdm_total = data[7]
        sequence = struct.unpack_from("<I", data, 8)[0]
        uptime_ms = struct.unpack_from("<I", data, 12)[0]
        rssi = struct.unpack_from("<b", data, 16)[0]
        channel = data[17]
        peer_count = data[18]
        dropped = data[19]
        resolved, identity_source_ip = self._resolve_packet_identity_locked(addr[0], node_id)
        health = self._rf_health_nodes.get(resolved[0])
        if health is None:
            health = _RfNodeHealth(
                node_id=resolved[0],
                physical_label=resolved[1],
                layout_node_id=resolved[2],
                source_ip=identity_source_ip,
                source_port=addr[1],
            )
            self._rf_health_nodes[resolved[0]] = health

        health.physical_label = resolved[1]
        health.layout_node_id = resolved[2]
        health.source_ip = identity_source_ip
        health.source_port = addr[1]
        health.packet_count += 1
        health.last_seen_at = now
        health.last_sequence = sequence
        health.uptime_ms = uptime_ms
        health.rssi = rssi
        health.channel = channel
        health.tdm_slot = tdm_slot
        health.tdm_total = tdm_total
        health.peer_count = peer_count
        health.dropped_csi_samples = dropped

    def _parse_csi(self, data: bytes, addr: tuple[str, int], now: datetime) -> None:
        if len(data) < 20:
            self._unknown_packet_count += 1
            return
        node_id = data[4]
        resolved, identity_source_ip = self._resolve_packet_identity_locked(addr[0], node_id)
        antennas = data[5]
        subcarriers = struct.unpack_from("<H", data, 6)[0]
        frequency_mhz = struct.unpack_from("<I", data, 8)[0]
        sequence = struct.unpack_from("<I", data, 12)[0]
        rssi = struct.unpack_from("<b", data, 16)[0]
        noise_floor = struct.unpack_from("<b", data, 17)[0]
        node = self._csi_nodes.get(resolved[0])
        if node is None:
            node = _CsiNode(
                node_id=resolved[0],
                raw_node_id=node_id,
                physical_label=resolved[1],
                layout_node_id=resolved[2],
                source_ip=identity_source_ip,
                source_port=addr[1],
            )
            self._csi_nodes[resolved[0]] = node

        node.source_ip = identity_source_ip
        node.source_port = addr[1]
        node.raw_node_id = node_id
        node.physical_label = resolved[1]
        node.layout_node_id = resolved[2]
        node.packet_count += 1
        node.bytes_total += len(data)
        node.last_seen_at = now
        node.last_sequence = sequence
        node.frequency_mhz = frequency_mhz
        node.antennas = antennas
        node.subcarriers = subcarriers
        node.rssi = rssi
        node.noise_floor = noise_floor
        node.last_payload_bytes = max(0, len(data) - 20)
        mean_power, power_std = _payload_power_stats(data[20:])
        if mean_power is not None and power_std is not None:
            node.power_window.append((now, mean_power, power_std, rssi))

    def _upsert_node_aggregate(
        self,
        *,
        node_id: int,
        raw_node_id: int,
        physical_label: str | None,
        layout_node_id: str | None,
        source_ip: str,
        source_port: int,
        now: datetime,
        sequence: int,
        frequency_mhz: int | None,
        antennas: int | None,
        subcarriers: int | None,
        rssi: int,
        noise_floor: int,
        payload_len: int,
        mean_power: float | None,
        power_std: float | None,
        bytes_total: int,
    ) -> None:
        node = self._csi_nodes.get(node_id)
        if node is None:
            node = _CsiNode(
                node_id=node_id,
                raw_node_id=raw_node_id,
                physical_label=physical_label,
                layout_node_id=layout_node_id,
                source_ip=source_ip,
                source_port=source_port,
            )
            self._csi_nodes[node_id] = node

        node.source_ip = source_ip
        node.source_port = source_port
        node.raw_node_id = raw_node_id
        node.physical_label = physical_label
        node.layout_node_id = layout_node_id
        node.packet_count += 1
        node.bytes_total += bytes_total
        node.last_seen_at = now
        node.last_sequence = sequence
        node.frequency_mhz = frequency_mhz
        node.antennas = antennas
        node.subcarriers = subcarriers
        node.rssi = rssi
        node.noise_floor = noise_floor
        node.last_payload_bytes = payload_len
        if mean_power is not None and power_std is not None:
            node.power_window.append((now, mean_power, power_std, rssi))

    def _parse_vitals(self, data: bytes, addr: tuple[str, int], now: datetime) -> None:
        if len(data) < 28:
            self._unknown_packet_count += 1
            return
        node_id = data[4]
        resolved, identity_source_ip = self._resolve_packet_identity_locked(addr[0], node_id)
        flags = data[5]
        breathing_bpm = struct.unpack_from("<H", data, 6)[0] / 100.0
        heart_bpm = struct.unpack_from("<I", data, 8)[0] / 10000.0
        rssi = struct.unpack_from("<b", data, 12)[0]
        detected_persons = data[13]
        motion_energy = struct.unpack_from("<f", data, 16)[0]
        presence_score = struct.unpack_from("<f", data, 20)[0]
        device_uptime_ms = struct.unpack_from("<I", data, 24)[0]
        node = self._vitals_nodes.get(resolved[0])
        if node is None:
            node = _VitalsNode(
                node_id=resolved[0],
                raw_node_id=node_id,
                physical_label=resolved[1],
                layout_node_id=resolved[2],
                source_ip=identity_source_ip,
                source_port=addr[1],
            )
            self._vitals_nodes[resolved[0]] = node

        node.source_ip = identity_source_ip
        node.source_port = addr[1]
        node.raw_node_id = node_id
        node.physical_label = resolved[1]
        node.layout_node_id = resolved[2]
        node.packet_count += 1
        node.last_seen_at = now
        node.presence = bool(flags & 0x01)
        node.fall = bool(flags & 0x02)
        node.motion = bool(flags & 0x04)
        node.breathing_bpm = breathing_bpm if breathing_bpm > 0 else None
        node.heart_bpm = heart_bpm if heart_bpm > 0 else None
        node.rssi = rssi
        node.detected_persons = detected_persons
        node.motion_energy = motion_energy
        node.presence_score = presence_score
        node.device_uptime_ms = device_uptime_ms

    def _resolve_packet_identity_locked(self, source_ip: str, raw_node_id: int) -> tuple[tuple[int, str | None, str | None], str]:
        resolved = _resolve_node_identity(source_ip, raw_node_id)
        if resolved[1] is not None:
            return resolved, _layout_ip_by_node_id(resolved[2]) or source_ip
        if self._stimulus_source_ip and time.monotonic() <= self._stimulus_source_deadline:
            stimulus_resolved = _resolve_node_identity(self._stimulus_source_ip, raw_node_id)
            if stimulus_resolved[1] is not None:
                return stimulus_resolved, self._stimulus_source_ip
        return resolved, source_ip


def _is_stale(now: datetime, last_seen_at: datetime | None, stale_after: float) -> bool:
    if last_seen_at is None:
        return True
    return (now - last_seen_at).total_seconds() > stale_after


def _age_ms(now: datetime, last_seen_at: datetime | None) -> int | None:
    if last_seen_at is None:
        return None
    return max(0, int((now - last_seen_at).total_seconds() * 1000))


def _is_pairwise_link(link: _CsiLink) -> bool:
    return link.tx_node_id > 0 and link.rx_node_id > 0 and link.tx_node_id != link.rx_node_id and bool(link.flags & RF_FLAG_ESPNOW)


def _link_quality_score(now: datetime, link: _CsiLink, stale_after: float) -> float:
    if not _is_pairwise_link(link) or _is_stale(now, link.last_seen_at, stale_after):
        return 0.0
    rate = _packet_rate_hz(link.power_window) or 0.0
    rate_score = min(1.0, rate / 3.0)
    rssi_score = 0.5
    if link.rssi is not None:
        # ESP32 CSI is still useful below -70 dBm, but confidence should decay.
        rssi_score = min(1.0, max(0.0, (link.rssi + 82) / 34))
    sample_score = min(1.0, len(link.power_window) / 30)
    age = _age_ms(now, link.last_seen_at)
    freshness_score = 0.0 if age is None else max(0.0, 1.0 - age / max(stale_after * 1000, 1.0))
    score = 0.36 * rate_score + 0.28 * rssi_score + 0.22 * sample_score + 0.14 * freshness_score
    return round(max(0.0, min(1.0, score)), 3)


def _stimulate_node(ip: str, timeout: float) -> tuple[bool, str | None]:
    connection: http.client.HTTPConnection | None = None
    try:
        connection = http.client.HTTPConnection(ip, 8032, timeout=max(timeout, 0.1))
        connection.request("GET", "/ota/status", headers={"Connection": "close"})
        response = connection.getresponse()
        response.read(256)
        return True, None
    except Exception as exc:
        return False, f"{ip}: {exc}"
    finally:
        if connection is not None:
            connection.close()


def _compact_errors(errors: list[str]) -> str | None:
    if not errors:
        return None
    unique_errors = list(dict.fromkeys(errors))
    suffix = "; ..." if len(unique_errors) > 3 else ""
    return "; ".join(unique_errors[:3]) + suffix


def _frequency_mhz_for_channel(channel: int) -> int:
    if 1 <= channel <= 13:
        return 2412 + (channel - 1) * 5
    if channel == 14:
        return 2484
    if 36 <= channel <= 177:
        return 5000 + channel * 5
    return 2437


def _build_ruview_adr018_packet(
    *,
    node_id: int,
    sequence: int,
    frequency_mhz: int,
    rssi: int,
    noise_floor: int,
    payload: bytes,
) -> bytes | None:
    pair_count = min(len(payload) // 2, 255)
    if pair_count <= 0:
        return None

    payload = payload[: pair_count * 2]
    packet = bytearray(20 + len(payload))
    struct.pack_into("<I", packet, 0, CSI_MAGIC)
    packet[4] = max(0, min(int(node_id), 255))
    packet[5] = 1
    struct.pack_into("<H", packet, 6, pair_count)
    struct.pack_into("<I", packet, 8, max(0, min(int(frequency_mhz), 0xFFFFFFFF)))
    struct.pack_into("<I", packet, 12, int(sequence) & 0xFFFFFFFF)

    # The current RuView image reads RSSI/noise at [14..15], while its ADR-018
    # firmware writes them at [16..17]. Duplicating the bytes keeps the adapter
    # compatible with both parser variants; sequence exactness is not used for
    # pose estimation.
    rssi_byte = struct.pack("<b", max(-128, min(int(rssi), 127)))[0]
    noise_byte = struct.pack("<b", max(-128, min(int(noise_floor), 127)))[0]
    packet[14] = rssi_byte
    packet[15] = noise_byte
    packet[16] = rssi_byte
    packet[17] = noise_byte
    packet[18] = 0
    packet[19] = 0
    packet[20:] = payload
    return bytes(packet)


def _payload_power_stats(payload: bytes) -> tuple[float | None, float | None]:
    if len(payload) < 2:
        return None, None
    pair_count = len(payload) // 2
    powers: list[float] = []
    for index in range(pair_count):
        i_value = struct.unpack_from("<b", payload, index * 2)[0]
        q_value = struct.unpack_from("<b", payload, index * 2 + 1)[0]
        powers.append(float(i_value * i_value + q_value * q_value))
    mean_power = sum(powers) / len(powers)
    variance = sum((value - mean_power) ** 2 for value in powers) / len(powers)
    return mean_power, sqrt(variance)


def _mean(values: list[float | int]) -> float | None:
    if not values:
        return None
    return round(sum(float(value) for value in values) / len(values), 3)


def _packet_rate_hz(window: deque[tuple[datetime, float, float, int]]) -> float | None:
    if len(window) < 2:
        return None
    elapsed = (window[-1][0] - window[0][0]).total_seconds()
    if elapsed <= 0:
        return None
    return round((len(window) - 1) / elapsed, 2)


def _format_mac(raw: bytes) -> str:
    return ":".join(f"{byte:02X}" for byte in raw)


def _resolve_node_identity(source_ip: str, raw_node_id: int) -> tuple[int, str | None, str | None]:
    try:
        layout = load_rf_room_layout()
    except Exception:
        return raw_node_id, None, None

    if raw_node_id:
        for node in layout.nodes:
            if node.physical_label.isdigit() and int(node.physical_label) == raw_node_id:
                return raw_node_id, node.physical_label, node.node_id

    for node in layout.nodes:
        if node.ip == source_ip:
            try:
                return int(node.physical_label), node.physical_label, node.node_id
            except ValueError:
                return raw_node_id, node.physical_label, node.node_id
    return raw_node_id, None, None


def _resolve_node_identity_by_id(node_id: int) -> tuple[int, str | None, str | None]:
    if node_id == 0:
        return 0, None, None
    try:
        layout = load_rf_room_layout()
    except Exception:
        return node_id, None, None

    for node in layout.nodes:
        if node.physical_label.isdigit() and int(node.physical_label) == node_id:
            return node_id, node.physical_label, node.node_id
    return node_id, None, None


def _resolve_node_identity_by_mac(mac: str) -> tuple[int, str | None, str | None]:
    normalized = mac.upper()
    try:
        layout = load_rf_room_layout()
    except Exception:
        return 0, None, None

    for node in layout.nodes:
        if node.mac.upper() == normalized:
            try:
                return int(node.physical_label), node.physical_label, node.node_id
            except ValueError:
                return 0, node.physical_label, node.node_id
    return 0, None, None


def _layout_ip_by_node_id(layout_node_id: str | None) -> str | None:
    if not layout_node_id:
        return None
    try:
        layout = load_rf_room_layout()
    except Exception:
        return None
    for node in layout.nodes:
        if node.node_id == layout_node_id:
            return node.ip
    return None


def _tracked_persons_from_vitals(vitals: list[RuViewVitalsNodeState]) -> list[RuViewTrackedPerson]:
    active = [node for node in vitals if not node.stale and node.presence]
    if not active:
        return []
    confidence = min(1.0, max((node.presence_score or 0.35) for node in active))
    count = max(max((node.detected_persons or 1) for node in active), 1)
    return [
        RuViewTrackedPerson(
            person_id=f"ruview-presence-{index + 1}",
            status="presence",
            confidence=confidence,
            source="ruview-vitals",
            note="Presence only. Coordinates require CSI model calibration.",
        )
        for index in range(count)
    ]


_bridge = RuViewBridge()


def start_ruview_bridge() -> None:
    _bridge.start()


def stop_ruview_bridge() -> None:
    _bridge.stop()


def reset_ruview_bridge() -> None:
    _bridge.reset()


def get_ruview_bridge_status() -> RuViewBridgeStatus:
    return _bridge.status()
