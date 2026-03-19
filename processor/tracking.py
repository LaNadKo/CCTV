"""ONVIF PTZ auto-tracking."""
from __future__ import annotations
import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class PIDController:
    def __init__(self, kp: float = 0.5, kd: float = 0.1, deadzone: float = 0.05):
        self.kp = kp
        self.kd = kd
        self.deadzone = deadzone
        self._prev_error = 0.0
        self._prev_time = time.monotonic()

    def compute(self, error: float) -> float:
        if abs(error) < self.deadzone:
            return 0.0
        now = time.monotonic()
        dt = now - self._prev_time
        if dt < 1e-6:
            dt = 1e-6
        derivative = (error - self._prev_error) / dt
        output = self.kp * error + self.kd * derivative
        self._prev_error = error
        self._prev_time = now
        return max(-1.0, min(1.0, output))


class AutoTracker:
    def __init__(self, client, camera_id: int):
        self.client = client
        self.camera_id = camera_id
        self.pan_pid = PIDController()
        self.tilt_pid = PIDController()

    async def track(self, bbox: list[float], frame_w: int, frame_h: int):
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        err_x = (cx - frame_w / 2) / (frame_w / 2)
        err_y = (cy - frame_h / 2) / (frame_h / 2)
        pan = self.pan_pid.compute(-err_x)
        tilt = self.tilt_pid.compute(-err_y)
        if abs(pan) > 0 or abs(tilt) > 0:
            logger.debug("PTZ move: pan=%.3f tilt=%.3f", pan, tilt)


class PatrolMode:
    def __init__(self, presets: list[dict], dwell_seconds: float = 10.0):
        self.presets = presets
        self.dwell = dwell_seconds
        self._idx = 0
        self._interrupted = False

    def interrupt(self):
        self._interrupted = True

    def resume(self):
        self._interrupted = False

    async def run_cycle(self):
        if not self.presets or self._interrupted:
            return
        preset = self.presets[self._idx % len(self.presets)]
        logger.info("Patrol: moving to preset %s", preset.get("name", self._idx))
        await asyncio.sleep(self.dwell)
        self._idx = (self._idx + 1) % len(self.presets)
