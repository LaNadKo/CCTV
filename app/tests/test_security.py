from __future__ import annotations

import unittest

from app.config import settings
from app.security import encrypt_secret, generate_totp_secret, hash_api_key, verify_api_key, verify_totp_counter


class SecurityTests(unittest.TestCase):
    def test_api_key_hash_is_deterministic_and_verifiable(self) -> None:
        value = hash_api_key("test-api-key")
        self.assertTrue(value.startswith("sha256:"))
        self.assertEqual(value, hash_api_key("test-api-key"))
        self.assertTrue(verify_api_key("test-api-key", value))
        self.assertFalse(verify_api_key("wrong-api-key", value))

    def test_secret_encryption_fails_closed_without_key(self) -> None:
        previous = settings.totp_encryption_key
        settings.totp_encryption_key = None
        try:
            with self.assertRaises(RuntimeError):
                encrypt_secret("camera-password")
        finally:
            settings.totp_encryption_key = previous

    def test_totp_verification_returns_replay_counter(self) -> None:
        secret = generate_totp_secret()
        code = __import__("pyotp").TOTP(secret).now()

        counter = verify_totp_counter(code, secret)

        self.assertIsInstance(counter, int)
        self.assertGreater(counter, 0)


if __name__ == "__main__":
    unittest.main()
