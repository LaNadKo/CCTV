from __future__ import annotations

import unittest

from starlette.requests import Request

from app.config import settings
from app.rate_limit import client_ip


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (peer, 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


class RateLimitTests(unittest.TestCase):
    def test_untrusted_peer_cannot_spoof_forwarded_ip(self) -> None:
        previous = settings.trusted_proxy_networks
        settings.trusted_proxy_networks = ["127.0.0.0/8", "172.16.0.0/12"]
        try:
            self.assertEqual(
                client_ip(_request("192.168.88.50", "203.0.113.10")),
                "192.168.88.50",
            )
        finally:
            settings.trusted_proxy_networks = previous

    def test_trusted_proxy_can_forward_single_client_ip(self) -> None:
        previous = settings.trusted_proxy_networks
        settings.trusted_proxy_networks = ["172.16.0.0/12"]
        try:
            self.assertEqual(
                client_ip(_request("172.20.0.4", "192.168.88.50")),
                "192.168.88.50",
            )
        finally:
            settings.trusted_proxy_networks = previous

    def test_trusted_proxy_uses_first_untrusted_forwarded_hop(self) -> None:
        previous = settings.trusted_proxy_networks
        settings.trusted_proxy_networks = ["172.16.0.0/12"]
        try:
            self.assertEqual(
                client_ip(_request("172.20.0.4", "203.0.113.10, 172.20.0.5")),
                "203.0.113.10",
            )
        finally:
            settings.trusted_proxy_networks = previous


if __name__ == "__main__":
    unittest.main()
