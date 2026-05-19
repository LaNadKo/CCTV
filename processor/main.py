"""Processor service entry point."""
from __future__ import annotations
import asyncio
import logging
import signal
from processor.config import settings
from processor.client import BackendClient
from processor.camera_utils import resolve_source
from processor.detection import CameraWorker
from processor.media_server import ProcessorMediaServer
from processor.monitor import SystemMonitor, get_system_info
from processor.networking import detect_advertised_ip
from processor.paths import ensure_media_dirs
from processor.runtime import RuntimeLock
from cctv_ai.runtime_env import log_acceleration_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


class ProcessorService:
    def __init__(self):
        self.client = BackendClient()
        self.processor_id: int | None = None
        self.workers: dict[int, CameraWorker] = {}
        self._running = False
        self._prewarm_task: asyncio.Task | None = None
        self._monitor = SystemMonitor()
        self._runtime_lock = RuntimeLock()
        self._assignment_lock = asyncio.Lock()
        self._assignment_refresh_event = asyncio.Event()
        self._workers_paused = False
        self._system_info = get_system_info()
        self._acceleration_report = log_acceleration_report(logger, settings.processor_accel)
        self._system_info["acceleration"] = {
            "preference": self._acceleration_report.get("preference"),
            "selected_device": self._acceleration_report.get("selected_device"),
            "selected_provider": self._acceleration_report.get("selected_provider"),
            "onnxruntime_providers": self._acceleration_report.get("onnxruntime_providers"),
            "cuda_root": self._acceleration_report.get("cuda_root"),
            "nvidia_smi_available": bool(self._acceleration_report.get("nvidia_smi")),
        }
        self._system_info["inference_device"] = self._acceleration_report.get("selected_device") or self._system_info.get("inference_device", "cpu")
        self._advertised_ip = detect_advertised_ip(settings.advertised_ip, backend_url=settings.backend_url)
        if self._advertised_ip:
            self._system_info["advertised_ip"] = self._advertised_ip
        self._gallery: list[dict] = []
        self._gallery_loaded_at = 0.0
        self._gallery_refresh_seconds = 180.0
        self._media_server = ProcessorMediaServer(
            service=self,
            host="0.0.0.0",
            port=settings.media_port,
            media_token=settings.media_token,
        )

    async def start(self):
        self._runtime_lock.acquire()
        try:
            self._running = True
            ensure_media_dirs()
            self._media_server.start()
            if settings.processor_id:
                self.processor_id = settings.processor_id
                logger.info("Using existing processor id=%d for %s", self.processor_id, settings.processor_name)
            else:
                result = await self.client.register(
                    settings.processor_name,
                    {
                        **self._system_info,
                        "max_workers": settings.max_workers,
                        "media_port": settings.media_port,
                        "media_token": settings.media_token,
                    },
                    node_uid=settings.processor_node_uid,
                    hostname=self._system_info.get("hostname"),
                    ip_address=self._advertised_ip,
                    os_info=self._system_info.get("os"),
                    version="1.0.0",
                )
                self.processor_id = result["processor_id"]
                logger.info("Registered as processor %s (id=%d)", settings.processor_name, self.processor_id)
            self._prewarm_task = asyncio.create_task(asyncio.to_thread(self._prewarm_models))
            await asyncio.gather(self._heartbeat_loop(), self._assignment_loop(), self._command_loop())
        except Exception:
            self._running = False
            self._media_server.stop()
            await self.client.close()
            self._runtime_lock.release()
            raise

    async def stop(self):
        self._running = False
        self._assignment_refresh_event.set()
        if self._prewarm_task and not self._prewarm_task.done():
            self._prewarm_task.cancel()
        for w in self.workers.values():
            w.stop()
        self._media_server.stop()
        if self.processor_id is not None:
            try:
                await self.client.heartbeat(
                    self.processor_id,
                    "offline",
                    stats={"active_cameras": 0},
                    ip_address=self._advertised_ip,
                    hostname=self._system_info.get("hostname"),
                    os_info=self._system_info.get("os"),
                    version="1.0.0",
                    capabilities=self._system_info,
                    media_port=settings.media_port,
                    media_token=settings.media_token,
                )
            except Exception:
                logger.exception("Failed to publish offline heartbeat")
        await self.client.close()
        self._runtime_lock.release()

    def _prewarm_models(self) -> None:
        face_device = "unavailable"
        body_device = "unavailable"
        try:
            from processor.vision import prewarm_models

            face_device = prewarm_models()
        except Exception:
            logger.exception("Face model prewarm failed")
        try:
            from processor.body_detector import prewarm_model

            body_device = prewarm_model()
        except Exception:
            logger.exception("Body model prewarm failed")
        logger.info("Model prewarm completed face=%s body=%s", face_device, body_device)

    async def _heartbeat_loop(self):
        while self._running:
            try:
                metrics = self._monitor.collect(len(self.workers))
                await self.client.heartbeat(
                    self.processor_id,
                    "online",
                    stats={"active_cameras": len(self.workers)},
                    metrics=metrics.to_dict(),
                    ip_address=self._advertised_ip,
                    hostname=self._system_info.get("hostname"),
                    os_info=self._system_info.get("os"),
                    version="1.0.0",
                    capabilities=self._system_info,
                    media_port=settings.media_port,
                    media_token=settings.media_token,
                )
            except Exception:
                logger.exception("Heartbeat failed")
            await asyncio.sleep(settings.heartbeat_interval)

    async def _sync_assignments(self):
        async with self._assignment_lock:
            assignments = await self.client.get_assignments(self.processor_id)
            assigned_ids = {a["camera_id"] for a in assignments}
            for cid in list(self.workers.keys()):
                if cid not in assigned_ids:
                    self.workers[cid].stop()
                    del self.workers[cid]
                    logger.info("Stopped worker for camera %d", cid)
            if self._workers_paused:
                logger.info("Camera workers are paused; assignments synced without starting workers")
                return
            now = asyncio.get_running_loop().time()
            if self._gallery_loaded_at <= 0.0 or (now - self._gallery_loaded_at) >= self._gallery_refresh_seconds:
                self._gallery = await self.client.get_gallery(self.processor_id)
                self._gallery_loaded_at = now
            for a in assignments:
                cid = a["camera_id"]
                source = resolve_source(a)
                if source is None:
                    logger.warning("No source for camera %d", cid)
                    continue
                worker = self.workers.get(cid)
                if worker is None:
                    worker = CameraWorker(a, self.client, source)
                    await worker.set_gallery(self._gallery)
                    self.workers[cid] = worker
                    asyncio.create_task(worker.start(self.processor_id))
                    logger.info("Started worker for camera %d", cid)
                    continue

                if worker.source != source:
                    worker.stop()
                    replacement = CameraWorker(a, self.client, source)
                    await replacement.set_gallery(self._gallery)
                    self.workers[cid] = replacement
                    asyncio.create_task(replacement.start(self.processor_id))
                    logger.info("Restarted worker for camera %d after source update", cid)
                    continue

                await worker.update_assignment(a)
                await worker.set_gallery(self._gallery)

    async def _assignment_loop(self):
        while self._running:
            try:
                await self._sync_assignments()
            except Exception:
                logger.exception("Assignment poll failed")
            self._assignment_refresh_event.clear()
            try:
                await asyncio.wait_for(self._assignment_refresh_event.wait(), timeout=settings.poll_interval)
            except asyncio.TimeoutError:
                pass

    async def _command_loop(self):
        while self._running:
            try:
                commands = await self.client.get_pending_commands(self.processor_id)
                for command in commands:
                    await self._execute_command(command)
            except Exception:
                logger.exception("Command poll failed")
            await asyncio.sleep(settings.poll_interval)

    async def _execute_command(self, command: dict):
        command_id = int(command["command_id"])
        command_type = str(command["command_type"])
        try:
            if command_type == "reload_assignments":
                await self._sync_assignments()
                result = {"message": "Assignments reloaded", "active_cameras": len(self.workers)}
            elif command_type == "restart_workers":
                await self._restart_workers()
                await self._sync_assignments()
                result = {"message": "Workers restarted", "active_cameras": len(self.workers)}
            elif command_type == "stop_all_cameras":
                self._workers_paused = True
                await self._stop_all_workers()
                result = {"message": "All camera workers stopped", "active_cameras": len(self.workers)}
            elif command_type == "resume_cameras":
                self._workers_paused = False
                await self._sync_assignments()
                result = {"message": "Camera workers resumed", "active_cameras": len(self.workers)}
            elif command_type == "refresh_gallery":
                self._gallery = await self.client.get_gallery(self.processor_id)
                self._gallery_loaded_at = asyncio.get_running_loop().time()
                for worker in self.workers.values():
                    await worker.set_gallery(self._gallery)
                result = {"message": "Gallery refreshed", "entries": len(self._gallery)}
            elif command_type == "shutdown":
                result = {"message": "Processor shutdown requested"}
                await self.client.complete_command(self.processor_id, command_id, "succeeded", result=result)
                await self.stop()
                return
            else:
                raise ValueError(f"Unsupported command: {command_type}")
            await self.client.complete_command(self.processor_id, command_id, "succeeded", result=result)
        except Exception as exc:
            logger.exception("Processor command %s failed", command_type)
            await self.client.complete_command(self.processor_id, command_id, "failed", error_message=str(exc))

    async def _stop_all_workers(self):
        for worker in self.workers.values():
            worker.stop()
        self.workers.clear()

    async def _restart_workers(self):
        await self._stop_all_workers()
        self._gallery_loaded_at = 0.0


async def main():
    svc = ProcessorService()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(svc.stop()))
        except NotImplementedError:
            pass
    await svc.start()


if __name__ == "__main__":
    asyncio.run(main())
