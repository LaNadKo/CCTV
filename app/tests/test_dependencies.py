from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi import HTTPException, status
from starlette.requests import Request

from app.dependencies import _enforce_password_rotation


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


class PasswordRotationTests(unittest.TestCase):
    def test_password_rotation_blocks_regular_api(self) -> None:
        user = SimpleNamespace(must_change_password=True)

        with self.assertRaises(HTTPException) as ctx:
            _enforce_password_rotation(user, _request("/admin/users"))

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)

    def test_password_rotation_allows_me_and_change_password(self) -> None:
        user = SimpleNamespace(must_change_password=True)

        _enforce_password_rotation(user, _request("/auth/me"))
        _enforce_password_rotation(user, _request("/auth/change-password"))


if __name__ == "__main__":
    unittest.main()
