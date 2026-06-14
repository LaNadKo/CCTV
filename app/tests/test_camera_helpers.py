from __future__ import annotations

import unittest

from fastapi import HTTPException, status

from app.routers import cameras


class CameraHelperTests(unittest.TestCase):
    def test_processor_snapshot_payload_is_bounded(self) -> None:
        payload = bytearray(b"a" * cameras._MAX_PROCESSOR_SNAPSHOT_BYTES)

        with self.assertRaises(HTTPException) as ctx:
            cameras._append_bounded_bytes(
                payload,
                b"x",
                max_bytes=cameras._MAX_PROCESSOR_SNAPSHOT_BYTES,
            )

        self.assertEqual(ctx.exception.status_code, status.HTTP_413_CONTENT_TOO_LARGE)


if __name__ == "__main__":
    unittest.main()
