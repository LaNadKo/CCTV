"""ONVIF PTZ runtime helpers for processor-side auto-tracking."""
from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlparse

from onvif import ONVIFClient

logger = logging.getLogger(__name__)


class PIDController:
    def __init__(self, kp: float = 0.45, kd: float = 0.08, deadzone: float = 0.06):
        self.kp = kp
        self.kd = kd
        self.deadzone = deadzone
        self._prev_error = 0.0
        self._prev_time = time.monotonic()

    def reset(self) -> None:
        self._prev_error = 0.0
        self._prev_time = time.monotonic()

    def compute(self, error: float) -> float:
        if abs(error) < self.deadzone:
            return 0.0
        now = time.monotonic()
        dt = max(now - self._prev_time, 1e-6)
        derivative = (error - self._prev_error) / dt
        output = self.kp * error + self.kd * derivative
        self._prev_error = error
        self._prev_time = now
        return max(-1.0, min(1.0, output))


def _preferred_onvif_endpoint(assignment: dict) -> dict | None:
    endpoints = assignment.get("endpoints") or []
    onvif_endpoints = [item for item in endpoints if item.get("endpoint_kind") == "onvif" and item.get("endpoint_url")]
    if not onvif_endpoints:
        return None
    onvif_endpoints.sort(key=lambda item: (not bool(item.get("is_primary")), item.get("endpoint_url", "")))
    return onvif_endpoints[0]


class OnvifController:
    def __init__(self, assignment: dict):
        self.assignment = assignment
        self._lock = threading.Lock()
        self._client: ONVIFClient | None = None
        self._client_key: tuple[str, int, str, str, bool, str | None] | None = None

    def refresh_assignment(self, assignment: dict) -> None:
        with self._lock:
            self.assignment = assignment
            self._client = None
            self._client_key = None

    def available(self) -> bool:
        endpoint = _preferred_onvif_endpoint(self.assignment)
        return bool(endpoint and self.assignment.get("onvif_profile_token"))

    def _connection_tuple(self) -> tuple[str, int, str, str, bool, str | None]:
        endpoint = _preferred_onvif_endpoint(self.assignment)
        if not endpoint:
            raise RuntimeError("ONVIF endpoint is not configured")
        parsed = urlparse(endpoint["endpoint_url"])
        host = parsed.hostname or self.assignment.get("ip_address") or ""
        if not host:
            raise RuntimeError("Cannot determine ONVIF host")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        username = endpoint.get("username") or ""
        password = endpoint.get("password_secret") or ""
        use_https = parsed.scheme == "https"
        profile_token = self.assignment.get("onvif_profile_token")
        return host, port, username, password, use_https, profile_token

    def _get_client(self) -> tuple[ONVIFClient, str]:
        host, port, username, password, use_https, profile_token = self._connection_tuple()
        if not profile_token:
            raise RuntimeError("ONVIF profile token is not configured")
        key = (host, port, username, password, use_https, profile_token)
        with self._lock:
            if self._client is None or self._client_key != key:
                self._client = ONVIFClient(
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    use_https=use_https,
                    timeout=5,
                )
                self._client_key = key
        return self._client, profile_token

    def continuous_move(self, pan: float = 0.0, tilt: float = 0.0, zoom: float = 0.0, timeout_seconds: float = 0.35) -> bool:
        client, profile_token = self._get_client()
        velocity = {"PanTilt": {"x": float(pan), "y": float(tilt)}, "Zoom": {"x": float(zoom)}}
        client.ptz().ContinuousMove(ProfileToken=profile_token, Velocity=velocity, Timeout=f"PT{max(timeout_seconds, 0.1):.1f}S")
        return True

    def stop(self) -> bool:
        client, profile_token = self._get_client()
        client.ptz().Stop(ProfileToken=profile_token, PanTilt=True, Zoom=True)
        return True

    def goto_preset(self, preset_token: str) -> bool:
        client, profile_token = self._get_client()
        client.ptz().GotoPreset(ProfileToken=profile_token, PresetToken=preset_token)
        return True


class AutoTracker:
    def __init__(self, controller: OnvifController, command_interval: float = 0.35, idle_stop_after: float = 1.0):
        self.controller = controller
        self.command_interval = max(command_interval, 0.1)
        self.idle_stop_after = max(idle_stop_after, 0.5)
        self.pan_pid = PIDController()
        self.tilt_pid = PIDController()
        self._last_command_at = 0.0
        self._last_target_at = 0.0
        self._moving = False

    def refresh_assignment(self, assignment: dict) -> None:
        self.controller.refresh_assignment(assignment)
        self.pan_pid.reset()
        self.tilt_pid.reset()
        self._last_command_at = 0.0
        self._last_target_at = 0.0
        self._moving = False

    def track(self, bbox: tuple[int, int, int, int], frame_w: int, frame_h: int) -> bool:
        if not self.controller.available():
            return False
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        err_x = (cx - frame_w / 2) / max(frame_w / 2, 1)
        err_y = (cy - frame_h / 2) / max(frame_h / 2, 1)
        pan = self.pan_pid.compute(-err_x)
        tilt = self.tilt_pid.compute(-err_y)
        now = time.monotonic()
        self._last_target_at = now

        if abs(pan) < 0.01 and abs(tilt) < 0.01:
            return self.stop(force=False)
        if now - self._last_command_at < self.command_interval:
            return False
        try:
            logger.debug("PTZ auto-track camera=%s pan=%.3f tilt=%.3f", self.controller.assignment.get("camera_id"), pan, tilt)
            self.controller.continuous_move(pan=pan, tilt=tilt, zoom=0.0, timeout_seconds=self.command_interval)
            self._last_command_at = now
            self._moving = True
            return True
        except Exception:
            logger.exception("Auto-tracking PTZ move failed for camera %s", self.controller.assignment.get("camera_id"))
            return False

    def stop(self, force: bool = False) -> bool:
        now = time.monotonic()
        if not self._moving and not force:
            return False
        if not force and (now - self._last_target_at) < self.idle_stop_after:
            return False
        try:
            self.controller.stop()
            self._moving = False
            self.pan_pid.reset()
            self.tilt_pid.reset()
            return True
        except Exception:
            logger.exception("Auto-tracking PTZ stop failed for camera %s", self.controller.assignment.get("camera_id"))
            return False


class PatrolMode:
    def __init__(self, controller: OnvifController, presets: list[dict], dwell_seconds: float = 10.0):
        self.controller = controller
        self.dwell = max(dwell_seconds, 2.0)
        self._idx = 0
        self._interrupted = False
        self._next_move_at = 0.0
        self.refresh_presets(presets)

    def refresh_assignment(self, assignment: dict) -> None:
        self.controller.refresh_assignment(assignment)

    def refresh_presets(self, presets: list[dict]) -> None:
        self.presets = [dict(item) for item in presets if item.get("preset_token")]
        self.presets.sort(key=lambda item: (int(item.get("order_index", 0)), int(item.get("camera_preset_id", 0))))
        self._idx = 0
        self._next_move_at = 0.0

    def interrupt(self) -> None:
        self._interrupted = True

    def resume(self) -> None:
        self._interrupted = False

    def step(self, now: float | None = None) -> bool:
        if not self.controller.available() or not self.presets or self._interrupted:
            return False
        current = time.monotonic() if now is None else now
        if current < self._next_move_at:
            return False
        preset = self.presets[self._idx % len(self.presets)]
        try:
            logger.info("Patrol: camera=%s goto preset %s", self.controller.assignment.get("camera_id"), preset.get("name", self._idx))
            self.controller.goto_preset(str(preset["preset_token"]))
            dwell = float(preset.get("dwell_seconds") or self.dwell)
            self._next_move_at = current + max(dwell, 2.0)
            self._idx = (self._idx + 1) % len(self.presets)
            return True
        except Exception:
            logger.exception("Patrol preset move failed for camera %s", self.controller.assignment.get("camera_id"))
            self._next_move_at = current + self.dwell
            return False
