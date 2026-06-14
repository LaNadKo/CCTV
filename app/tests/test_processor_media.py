from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.processor_media import (
    build_processor_file_path,
    get_processor_direct_media_headers,
    get_processor_media_base_urls,
    parse_processor_file_path,
    safe_processor_relative_path,
)
from cctv_ai.media_auth import verify_scoped_media_token


class ProcessorMediaTests(unittest.TestCase):
    def test_blocked_advertised_ip_is_not_used_for_proxy_url(self) -> None:
        proc = SimpleNamespace(
            capabilities=json.dumps({"advertised_ip": "127.0.0.1", "media_port": 8777}),
            ip_address="192.168.88.10",
        )
        urls = get_processor_media_base_urls(proc)
        self.assertNotIn("http://127.0.0.1:8777", urls)
        self.assertIn("http://192.168.88.10:8777", urls)

    def test_link_local_processor_ip_is_not_used_for_proxy_url(self) -> None:
        proc = SimpleNamespace(
            capabilities=json.dumps({"advertised_ip": "169.254.169.254", "media_port": 8777}),
            ip_address="169.254.10.20",
        )
        urls = get_processor_media_base_urls(proc)
        self.assertNotIn("http://169.254.169.254:8777", urls)
        self.assertNotIn("http://169.254.10.20:8777", urls)

    def test_processor_media_hostname_is_pinned_to_resolved_ip(self) -> None:
        proc = SimpleNamespace(
            capabilities=json.dumps({"advertised_ip": "processor.lan", "media_port": 8777}),
            ip_address=None,
        )
        resolved = [(None, None, None, "", ("192.168.88.10", 0))]

        with patch("app.network_policy.socket.getaddrinfo", return_value=resolved):
            urls = get_processor_media_base_urls(proc)

        self.assertEqual(urls[0], "http://192.168.88.10:8777")
        self.assertNotIn("http://processor.lan:8777", urls)

    def test_processor_media_path_rejects_traversal_and_absolute_paths(self) -> None:
        for value in ("../secret", "/etc/passwd", r"C:\Windows\win.ini", "a/../../secret"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    safe_processor_relative_path(value)

    def test_processor_media_path_is_bound_to_processor(self) -> None:
        value = build_processor_file_path(12, "camera_1/clip.mp4")
        self.assertEqual(value, "processor://12/camera_1/clip.mp4")
        self.assertEqual(parse_processor_file_path(value), (12, "camera_1/clip.mp4"))
        self.assertIsNone(parse_processor_file_path("processor://12/../secret"))

    def test_direct_media_header_is_short_lived_and_path_scoped(self) -> None:
        proc = SimpleNamespace(
            capabilities=json.dumps({"media_token": "processor-secret"}),
        )
        path = "/cameras/7/stream.mjpeg"

        headers = get_processor_direct_media_headers(proc, path=path)
        token = headers["X-Processor-Media-Token"]

        self.assertNotEqual(token, "processor-secret")
        self.assertTrue(verify_scoped_media_token("processor-secret", token, path))
        self.assertFalse(
            verify_scoped_media_token(
                "processor-secret",
                token,
                "/cameras/8/stream.mjpeg",
            )
        )


if __name__ == "__main__":
    unittest.main()
