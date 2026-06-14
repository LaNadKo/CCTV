from __future__ import annotations

import base64
import unittest
from types import SimpleNamespace

from fastapi import HTTPException, status

from app.routers import processors
from app.schemas.processors import ProcessorHeartbeat


class ProcessorPayloadTests(unittest.IsolatedAsyncioTestCase):
    def test_connection_code_has_sufficient_entropy_and_fits_schema(self) -> None:
        code = processors._new_processor_connection_code()

        self.assertGreaterEqual(len(code), 16)
        self.assertLessEqual(len(code), 20)

    def test_heartbeat_metadata_size_and_depth_are_bounded(self) -> None:
        with self.assertRaises(ValueError):
            ProcessorHeartbeat(stats={"value": "x" * (70 * 1024)})
        with self.assertRaises(ValueError):
            ProcessorHeartbeat(stats={"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": 1}}}}}}}}})

    def test_decode_snapshot_accepts_valid_base64(self) -> None:
        payload = base64.b64encode(b"jpeg-bytes").decode("ascii")

        self.assertEqual(processors._decode_snapshot_b64(payload), b"jpeg-bytes")

    def test_decode_snapshot_ignores_invalid_base64(self) -> None:
        self.assertIsNone(processors._decode_snapshot_b64("not valid base64"))

    def test_decode_snapshot_rejects_large_payload_before_decode(self) -> None:
        payload = "A" * (processors._MAX_EVENT_SNAPSHOT_B64_CHARS + 1)

        with self.assertRaises(HTTPException) as ctx:
            processors._decode_snapshot_b64(payload)

        self.assertEqual(ctx.exception.status_code, status.HTTP_413_CONTENT_TOO_LARGE)

    def test_command_result_rejects_large_text(self) -> None:
        payload = "A" * (processors._MAX_COMMAND_RESULT_CHARS + 1)

        with self.assertRaises(HTTPException) as ctx:
            processors._limited_command_text(payload, field_name="Command result")

        self.assertEqual(ctx.exception.status_code, status.HTTP_413_CONTENT_TOO_LARGE)

    async def test_command_result_body_limit_does_not_require_content_length(self) -> None:
        async def stream():
            yield b'{"status":"succeeded","result":"'
            yield b"A" * processors._MAX_PROCESSOR_COMMAND_RESULT_BODY_BYTES

        request = SimpleNamespace(stream=stream)

        with self.assertRaises(HTTPException) as ctx:
            await processors._read_command_result_payload(request)

        self.assertEqual(ctx.exception.status_code, status.HTTP_413_CONTENT_TOO_LARGE)


if __name__ == "__main__":
    unittest.main()
