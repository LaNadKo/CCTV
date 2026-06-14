import unittest

from app.config import Settings


class SettingsParsingTests(unittest.TestCase):
    def test_string_lists_accept_json_arrays_written_by_setup_script(self) -> None:
        settings = Settings(
            _env_file=None,
            CORS_ORIGINS='["https://console.example", "http://127.0.0.1:8000"]',
            ALLOWED_HOSTS='["console.example", "127.0.0.1"]',
        )

        self.assertEqual(
            settings.cors_origins,
            ["https://console.example", "http://127.0.0.1:8000"],
        )
        self.assertEqual(settings.allowed_hosts, ["console.example", "127.0.0.1"])

    def test_string_lists_remain_compatible_with_csv(self) -> None:
        settings = Settings(
            _env_file=None,
            TRUSTED_PROXY_NETWORKS="127.0.0.0/8, ::1/128",
        )

        self.assertEqual(settings.trusted_proxy_networks, ["127.0.0.0/8", "::1/128"])


if __name__ == "__main__":
    unittest.main()
