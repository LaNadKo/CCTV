"""Processor service entry point."""
from __future__ import annotations
import asyncio
import logging
import signal
from processor.config import settings
from processor.client import BackendClient
from processor.camera_utils import resolve_source
from processor.detection import CameraWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


class ProcessorService:
    def __init__(self):
        self.client = BackendClient()
        self.processor_id: int | None = None
        self.workers: dict[int, CameraWorker] = {}
        self._running = False

    async def start(self):
        self._running = True
        result = await self.client.register(settings.processor_name, {"max_workers": settings.max_workers})
        self.processor_id = result["processor_id"]
        logger.info("Registered as processor %s (id=%d)", settings.processor_name, self.processor_id)
        await asyncio.gather(self._heartbeat_loop(), self._assignment_loop())

    async def stop(self):
        self._running = False
        for w in self.workers.values():
            w.stop()
        await self.client.close()

    async def _heartbeat_loop(self):
        while self._running:
            try:
                await self.client.heartbeat(self.processor_id, "online", {"active_cameras": len(self.workers)})
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
                gallery = await self.client.get_gallery(self.processor_id)
                for a in assignments:
                    cid = a["camera_id"]
                    if cid not in self.workers:
                        source = resolve_source(a)
                        if source is None:
                            logger.warning("No source for camera %d", cid)
                            continue
                        worker = CameraWorker(a, self.client, source)
                        await worker.set_gallery(gallery)
                        self.workers[cid] = worker
                        asyncio.create_task(worker.start(self.processor_id))
                        logger.info("Started worker for camera %d", cid)
                    else:
                        await self.workers[cid].set_gallery(gallery)
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
