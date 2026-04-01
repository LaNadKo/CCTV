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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


class ProcessorService:
    def __init__(self):
        self.client = BackendClient()
        self.processor_id: int | None = None
        self.workers: dict[int, CameraWorker] = {}
        self._running = False
        self._monitor = SystemMonitor()
        self._system_info = get_system_info()
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
                    "max_workers": settings.max_workers,
                    "media_port": settings.media_port,
                    "media_token": settings.media_token,
                },
            )
            self.processor_id = result["processor_id"]
            logger.info("Registered as processor %s (id=%d)", settings.processor_name, self.processor_id)
        await asyncio.gather(self._heartbeat_loop(), self._assignment_loop())

    async def stop(self):
        self._running = False
        for w in self.workers.values():
            w.stop()
        self._media_server.stop()
        await self.client.close()

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

    async def _assignment_loop(self):
        while self._running:
            try:
                assignments = await self.client.get_assignments(self.processor_id)
                assigned_ids = {a["camera_id"] for a in assignments}
                for cid in list(self.workers.keys()):
                    if cid not in assigned_ids:
                        self.workers[cid].stop()
                        del self.workers[cid]
                        logger.info("Stopped worker for camera %d", cid)
                now = asyncio.get_running_loop().time()
                if not self._gallery or (now - self._gallery_loaded_at) >= self._gallery_refresh_seconds:
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
            except Exception:
                logger.exception("Assignment poll failed")
            await asyncio.sleep(settings.poll_interval)


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
