from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from processor.camera_utils import redact_source
from processor.cli import _redact_payload
from processor.detection import CameraWorker, _recording_has_free_space, _resize_capture_frame
from processor.media_server import (
    MAX_EMBEDDING_IMAGE_PIXELS,
    _AuthFailureLimiter,
    _decode_embedding_image,
    _embedding_image_pixel_count,
    _media_token_matches,
)
from cctv_ai.media_auth import issue_scoped_media_token, verify_scoped_media_token


class ProcessorSecurityHelpersTests(unittest.TestCase):
    def test_stream_wait_uses_frame_notification_instead_of_polling(self) -> None:
        worker = CameraWorker.__new__(CameraWorker)
        worker._frame_lock = threading.Lock()
        worker._frame_ready = threading.Condition(worker._frame_lock)
        worker._latest_raw_jpeg = None
        worker._latest_overlay_jpeg = None
        worker._stream_frame_sequence = 0
        worker._raw_frame_sequence = 0
        worker._overlay_frame_sequence = 0

        def publish() -> None:
            time.sleep(0.02)
            with worker._frame_ready:
                worker._latest_raw_jpeg = b"jpeg"
                worker._stream_frame_sequence += 1
                worker._raw_frame_sequence = worker._stream_frame_sequence
                worker._frame_ready.notify_all()

        publisher = threading.Thread(target=publish)
        publisher.start()
        sequence, frame = worker.wait_for_stream_frame(
            overlay=False,
            after_sequence=0,
            timeout=0.5,
        )
        publisher.join(timeout=1)

        self.assertEqual(sequence, 1)
        self.assertEqual(frame, b"jpeg")

    def test_redact_source_masks_userinfo_and_sensitive_query(self) -> None:
        value = redact_source(
            "rtsp://camera-user:camera-password@192.168.88.242:554/stream1?token=secret&mode=live"
        )
        self.assertEqual(
            value,
            "rtsp://***:***@192.168.88.242:554/stream1?token=%2A%2A%2A&mode=live",
        )
        self.assertNotIn("camera-password", str(value))
        self.assertNotIn("secret", str(value))

    def test_cli_redact_payload_masks_assignment_endpoints(self) -> None:
        payload = {
            "camera_id": 1,
            "name": "C200",
            "stream_url": "rtsp://user:pass@192.168.88.242:554/stream1?token=secret",
            "endpoints": [
                {
                    "endpoint_url": "rtsp://192.168.88.242:554/stream1",
                    "username": "user",
                    "password_secret": "pass",
                }
            ],
        }

        redacted = _redact_payload(payload)

        self.assertNotIn("user:pass", str(redacted))
        self.assertNotIn("token=secret", str(redacted))
        self.assertNotIn("user:pass", str(redacted))
        self.assertEqual(redacted["endpoints"][0]["username"], "***")
        self.assertEqual(redacted["endpoints"][0]["password_secret"], "***")

    def test_embedding_image_pixel_count_enforces_decoded_size(self) -> None:
        image = SimpleNamespace(ndim=3, shape=(MAX_EMBEDDING_IMAGE_PIXELS + 1, 1, 3))

        self.assertGreater(_embedding_image_pixel_count(image), MAX_EMBEDDING_IMAGE_PIXELS)

    def test_oversized_encoded_image_is_rejected_before_opencv_decode(self) -> None:
        with (
            patch(
                "processor.media_server._encoded_image_pixel_count",
                return_value=MAX_EMBEDDING_IMAGE_PIXELS + 1,
            ),
            patch("processor.media_server.cv2.imdecode") as imdecode,
        ):
            with self.assertRaises(OverflowError):
                _decode_embedding_image(b"image")

        imdecode.assert_not_called()

    def test_media_token_comparison_and_failure_limiter(self) -> None:
        self.assertTrue(_media_token_matches("expected", "expected"))
        self.assertFalse(_media_token_matches("expected", "wrong"))

        limiter = _AuthFailureLimiter(limit=2, window_seconds=60)
        self.assertFalse(limiter.record_failure("192.0.2.1", now=1.0))
        self.assertTrue(limiter.record_failure("192.0.2.1", now=2.0))
        self.assertTrue(limiter.is_blocked("192.0.2.1", now=3.0))
        limiter.clear("192.0.2.1")
        self.assertFalse(limiter.is_blocked("192.0.2.1", now=3.0))

    def test_large_capture_frame_is_downscaled_before_pipeline_queues(self) -> None:
        frame = __import__("numpy").zeros((1200, 1600, 3), dtype="uint8")

        resized = _resize_capture_frame(frame, 500_000)

        self.assertLessEqual(resized.shape[0] * resized.shape[1], 500_000)
        self.assertEqual(resized.shape[2], 3)

    def test_scoped_media_token_is_path_bound_and_expires(self) -> None:
        token = issue_scoped_media_token(
            "secret",
            "/cameras/1/stream.mjpeg",
            ttl_seconds=60,
            now=1000,
        )

        self.assertTrue(
            verify_scoped_media_token(
                "secret",
                token,
                "/cameras/1/stream.mjpeg",
                now=1030,
            )
        )
        self.assertFalse(
            verify_scoped_media_token(
                "secret",
                token,
                "/metrics",
                now=1030,
            )
        )
        self.assertFalse(
            verify_scoped_media_token(
                "secret",
                token,
                "/cameras/1/stream.mjpeg",
                now=1061,
            )
        )

    def test_recording_stops_before_disk_is_exhausted(self) -> None:
        with patch(
            "processor.detection.shutil.disk_usage",
            return_value=SimpleNamespace(free=100),
        ):
            self.assertFalse(_recording_has_free_space(__import__("pathlib").Path("."), 101))


if __name__ == "__main__":
    unittest.main()
