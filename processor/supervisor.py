"""Resident supervisor for starting and stopping Processor Runtime."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

from processor.client import BackendClient
from processor.runtime import (
    apply_env_overrides,
    base_dir,
    configure_headless_logging,
    ensure_connected,
    export_env,
    load_config,
    save_config,
)


logger = logging.getLogger(__name__)


class RuntimeSupervisor:
    """Small resident process that can launch Runtime on backend command."""

    def __init__(self) -> None:
        self.config = apply_env_overrides(load_config())
        self.process: subprocess.Popen[bytes] | None = None
        self.running = True

    @property
    def processor_id(self) -> int:
        return int(self.config["processor_id"])

    async def run(self) -> None:
        self.config = ensure_connected(self.config)
        save_config(self.config)
        export_env(self.config)
        client = BackendClient(
            base_url=str(self.config["backend_url"]),
            api_key=str(self.config["api_key"]),
        )
        try:
            while self.running:
                await self._heartbeat(client)
                await self._poll_commands(client)
                await asyncio.sleep(int(self.config.get("poll_interval", 3)))
        finally:
            await client.close()

    async def _heartbeat(self, client: BackendClient) -> None:
        try:
            await client.heartbeat(
                self.processor_id,
                status="supervisor_online",
                stats={"runtime_running": self._runtime_running()},
            )
        except Exception:
            logger.exception("Supervisor heartbeat failed")

    async def _poll_commands(self, client: BackendClient) -> None:
        try:
            commands = await client.get_pending_commands(
                self.processor_id,
                runner="supervisor",
            )
        except Exception:
            logger.exception("Supervisor command poll failed")
            return
        for command in commands:
            await self._execute_command(client, command)

    async def _execute_command(self, client: BackendClient, command: dict) -> None:
        command_id = int(command["command_id"])
        command_type = str(command["command_type"])
        try:
            if command_type == "start_runtime":
                started = self._start_runtime()
                result = {
                    "message": "Runtime start requested",
                    "started": started,
                    "running": self._runtime_running(),
                }
            elif command_type == "stop_runtime":
                stopped = self._stop_runtime()
                result = {
                    "message": "Runtime stop requested",
                    "stopped": stopped,
                    "running": self._runtime_running(),
                }
            elif command_type == "restart_runtime":
                stopped = self._stop_runtime()
                started = self._start_runtime()
                result = {
                    "message": "Runtime restart requested",
                    "stopped": stopped,
                    "started": started,
                    "running": self._runtime_running(),
                }
            else:
                raise ValueError(f"Unsupported supervisor command: {command_type}")
            await client.complete_command(
                self.processor_id,
                command_id,
                "succeeded",
                result=result,
            )
        except Exception as exc:
            logger.exception("Supervisor command %s failed", command_type)
            await client.complete_command(
                self.processor_id,
                command_id,
                "failed",
                error_message=str(exc),
            )

    def _runtime_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _start_runtime(self) -> bool:
        if self._runtime_running():
            return False
        command = self._runtime_command()
        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        self.process = subprocess.Popen(
            command,
            cwd=str(base_dir()),
            creationflags=creationflags,
        )
        logger.info("Started Processor Runtime pid=%s", self.process.pid)
        return True

    def _stop_runtime(self) -> bool:
        if not self._runtime_running():
            self.process = None
            return False
        assert self.process is not None
        self.process.terminate()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        logger.info("Stopped Processor Runtime")
        self.process = None
        return True

    def _runtime_command(self) -> list[str]:
        root = base_dir()
        if os.name == "nt":
            candidate = root / "CCTV-Processor-Runtime.exe"
            if candidate.exists():
                return [str(candidate), "--headless"]
        else:
            candidate = root / "CCTV-Processor-Runtime"
            if candidate.exists():
                return [str(candidate), "--headless"]
        return [sys.executable, "-m", "processor.run_runtime", "--headless"]

    async def stop(self) -> None:
        self.running = False


def run_supervisor() -> None:
    configure_headless_logging()
    supervisor = RuntimeSupervisor()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(supervisor.stop()))
        except NotImplementedError:
            pass
    loop.run_until_complete(supervisor.run())


if __name__ == "__main__":
    run_supervisor()

