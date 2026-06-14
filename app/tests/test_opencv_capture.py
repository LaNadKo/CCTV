import os
import unittest
from unittest.mock import MagicMock, patch

from cctv_ai.opencv_capture import open_video_capture


class OpenVideoCaptureTests(unittest.TestCase):
    def test_rtsp_timeouts_are_passed_during_open_and_environment_is_restored(self) -> None:
        capture = MagicMock()
        with (
            patch.dict(
                os.environ,
                {"OPENCV_FFMPEG_CAPTURE_OPTIONS": "existing-options"},
                clear=False,
            ),
            patch("cctv_ai.opencv_capture.cv2.VideoCapture", return_value=capture) as constructor,
        ):
            result = open_video_capture(
                "rtsp://camera.example/stream",
                open_timeout_ms=2500,
                read_timeout_ms=1500,
            )

            self.assertIs(result, capture)
            args = constructor.call_args.args
            self.assertEqual(args[0], "rtsp://camera.example/stream")
            self.assertEqual(args[2], [53, 2500, 54, 1500])
            self.assertEqual(os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"], "existing-options")

    def test_non_rtsp_source_uses_default_backend(self) -> None:
        capture = MagicMock()
        with patch("cctv_ai.opencv_capture.cv2.VideoCapture", return_value=capture) as constructor:
            result = open_video_capture(0)

        self.assertIs(result, capture)
        constructor.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
