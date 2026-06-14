from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import settings
from app.recording_storage import recording_local_path


class RecordingStorageTests(unittest.TestCase):
    def test_local_recording_must_be_inside_recordings_root(self) -> None:
        previous = settings.recordings_path
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "recordings"
            root.mkdir()
            inside = root / "inside.mp4"
            outside = Path(temp_dir) / "outside.mp4"
            inside.write_bytes(b"inside")
            outside.write_bytes(b"outside")
            settings.recordings_path = str(root)
            try:
                self.assertEqual(recording_local_path(str(inside)), inside.resolve())
                self.assertIsNone(recording_local_path(str(outside)))
            finally:
                settings.recordings_path = previous


if __name__ == "__main__":
    unittest.main()
