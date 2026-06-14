from __future__ import annotations

import unittest

from fastapi import HTTPException, status

from app.routers import recordings


class RecordingHelperTests(unittest.TestCase):
    def test_stitch_limits_reject_excessive_size_duration_and_files(self) -> None:
        cases = (
            {
                "file_count": recordings._MAX_STITCH_FILES + 1,
                "total_bytes": 0,
                "total_duration": 0,
            },
            {
                "file_count": 1,
                "total_bytes": recordings._MAX_STITCH_TOTAL_BYTES + 1,
                "total_duration": 0,
            },
            {
                "file_count": 1,
                "total_bytes": 0,
                "total_duration": recordings._MAX_STITCH_DURATION_SECONDS + 1,
            },
        )
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(HTTPException) as ctx:
                    recordings._enforce_stitch_limits(**values)
                self.assertEqual(
                    ctx.exception.status_code,
                    status.HTTP_413_CONTENT_TOO_LARGE,
                )


if __name__ == "__main__":
    unittest.main()
