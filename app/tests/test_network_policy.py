from __future__ import annotations

import unittest
import socket
from unittest.mock import patch

from app.network_policy import validate_camera_host, validate_camera_stream_source


class NetworkPolicyTests(unittest.TestCase):
    def test_lan_camera_sources_are_allowed(self) -> None:
        self.assertEqual(validate_camera_host("192.168.88.242"), "192.168.88.242")
        resolved = [(None, None, None, "", ("192.168.88.242", 0))]
        with patch("app.network_policy.socket.getaddrinfo", return_value=resolved):
            self.assertEqual(validate_camera_host("C200"), "C200")

    def test_blocked_literal_hosts_are_rejected(self) -> None:
        for host in ("localhost", "127.0.0.1", "::1", "169.254.169.254"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    validate_camera_host(host)

    def test_hostname_resolving_to_blocked_address_is_rejected(self) -> None:
        resolved = [(None, None, None, "", ("127.0.0.1", 0))]
        with patch("app.network_policy.socket.getaddrinfo", return_value=resolved):
            with self.assertRaises(ValueError):
                validate_camera_stream_source("rtsp://camera.local:554/stream1")

    def test_hostname_source_is_pinned_to_resolved_safe_ip(self) -> None:
        resolved = [(None, None, None, "", ("192.168.88.242", 0))]
        with patch("app.network_policy.socket.getaddrinfo", return_value=resolved):
            self.assertEqual(
                validate_camera_stream_source("rtsp://user:pass@camera.lan:554/stream1"),
                "rtsp://user:pass@192.168.88.242:554/stream1",
            )

    def test_unresolved_hostname_is_rejected(self) -> None:
        with patch("app.network_policy.socket.getaddrinfo", side_effect=socket.gaierror()):
            with self.assertRaises(ValueError):
                validate_camera_stream_source("rtsp://missing-camera.lan:554/stream1")


if __name__ == "__main__":
    unittest.main()
