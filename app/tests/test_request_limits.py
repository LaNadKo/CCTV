from __future__ import annotations

import unittest

from app.request_limits import ScopedRequestBodyLimitMiddleware


class RequestBodyLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_chunked_processor_metadata_is_rejected_before_app(self) -> None:
        app_called = False

        async def app(scope, receive, send):
            nonlocal app_called
            app_called = True

        middleware = ScopedRequestBodyLimitMiddleware(
            app,
            max_bytes=5,
            path_patterns=(r"/processors/connect",),
        )
        messages = iter(
            [
                {"type": "http.request", "body": b"123", "more_body": True},
                {"type": "http.request", "body": b"456", "more_body": False},
            ]
        )
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        await middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/processors/connect",
                "headers": [],
            },
            receive,
            send,
        )

        self.assertFalse(app_called)
        self.assertEqual(sent[0]["status"], 413)

    async def test_small_processor_metadata_is_replayed_to_app(self) -> None:
        received = []

        async def app(scope, receive, send):
            received.append(await receive())

        middleware = ScopedRequestBodyLimitMiddleware(
            app,
            max_bytes=16,
            path_patterns=(r"/processors/connect",),
        )

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async def send(message):
            return None

        await middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/processors/connect",
                "headers": [],
            },
            receive,
            send,
        )

        self.assertEqual(received[0]["body"], b"{}")


if __name__ == "__main__":
    unittest.main()
