from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.routers import detections


class DetectionHelperTests(unittest.TestCase):
    def test_decoded_snapshot_pixel_count_is_limited(self) -> None:
        image = SimpleNamespace(ndim=3, shape=(detections._MAX_EVENT_SNAPSHOT_PIXELS + 1, 1, 3))

        self.assertGreater(detections._decoded_image_pixel_count(image), detections._MAX_EVENT_SNAPSHOT_PIXELS)


if __name__ == "__main__":
    unittest.main()
