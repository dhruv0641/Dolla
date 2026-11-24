import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flowx_os.local_runtime import LocalRuntimeConfigurationError, read_file_secret


class LocalRuntimeTests(unittest.TestCase):
    def test_file_secret_rejects_non_reference_and_path_escape(self):
        for value in (None, "plain-secret", "secretref://os-store/local/key",
                      "secretref://file/etc/passwd", "secretref://file/run/secrets/../key"):
            with self.subTest(value=value), self.assertRaises(LocalRuntimeConfigurationError):
                read_file_secret(value)

    def test_file_secret_reads_bounded_regular_file_under_secret_root(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "runtime_password"
            secret.write_text("a" * 32, encoding="utf-8")
            reference = "secretref://file/run/secrets/runtime_password"
            original_is_file = Path.is_file
            original_is_symlink = Path.is_symlink
            original_read_text = Path.read_text

            def is_secret_path(path):
                return str(path).replace("\\", "/") == "/run/secrets/runtime_password"

            def is_file(path):
                return original_is_file(secret) if is_secret_path(path) else original_is_file(path)

            def is_symlink(path):
                return original_is_symlink(secret) if is_secret_path(path) else original_is_symlink(path)

            def read_text(path, *args, **kwargs):
                return original_read_text(secret, *args, **kwargs) if is_secret_path(path) else original_read_text(path, *args, **kwargs)

            with patch.object(Path, "is_file", is_file), patch.object(Path, "is_symlink", is_symlink), patch.object(Path, "read_text", read_text):
                self.assertEqual(read_file_secret(reference), "a" * 32)

    def test_external_capabilities_are_disabled_in_compose(self):
        compose = (Path(__file__).resolve().parents[1] / "compose.yaml").read_text(encoding="utf-8")
        for key in (
            "FLOWX_YOUTUBE_PUBLISHING_ENABLED", "FLOWX_INSTAGRAM_PUBLISHING_ENABLED",
            "FLOWX_FACEBOOK_PUBLISHING_ENABLED", "FLOWX_PLATFORM_RECONCILIATION_ENABLED",
            "FLOWX_PUBLICATION_SCHEDULING_ENABLED", "FLOWX_PLATFORM_ANALYTICS_ENABLED",
            "FLOWX_COMMENT_INGESTION_ENABLED", "FLOWX_COMMUNITY_ANALYSIS_ENABLED",
            "FLOWX_COMMUNITY_REPLY_DRAFTING_ENABLED", "FLOWX_COMMUNITY_OFFICIAL_RESPONSES_ENABLED",
            "FLOWX_COMMUNITY_INSIGHTS_ENABLED",
        ):
            self.assertIn(f'{key}: "false"', compose)
        self.assertEqual(compose.count("internal: true"), 2)

    def test_runtime_services_receive_only_required_secret_volumes(self):
        compose = (Path(__file__).resolve().parents[1] / "compose.yaml").read_text(encoding="utf-8")
        api = compose.split("\n  api:", 1)[1].split("\n  worker:", 1)[0]
        worker = compose.split("\n  worker:", 1)[1].split("\n  web:", 1)[0]
        database = compose.split("\n  db:", 1)[1].split("\n  migrate:", 1)[0]
        self.assertIn("postgres_runtime_secret", api)
        self.assertIn("auth_signing_secret", api)
        self.assertIn("dashboard_service_secret", api)
        self.assertNotIn("postgres_admin_secret", api)
        self.assertIn("postgres_runtime_secret", worker)
        self.assertNotIn("postgres_admin_secret", worker)
        self.assertNotIn("auth_signing_secret", worker)
        self.assertNotIn("dashboard_service_secret", worker)
        self.assertIn("postgres_admin_secret", database)
        self.assertNotIn("postgres_runtime_secret", database)
        self.assertNotIn("auth_signing_secret", database)
        self.assertNotIn("dashboard_service_secret", database)

    def test_only_secretless_gateway_publishes_host_ports(self):
        compose = (Path(__file__).resolve().parents[1] / "compose.yaml").read_text(encoding="utf-8")
        api = compose.split("\n  api:", 1)[1].split("\n  worker:", 1)[0]
        web = compose.split("\n  web:", 1)[1].split("\n  loopback-gateway:", 1)[0]
        gateway = compose.split("\n  loopback-gateway:", 1)[1].split("\n  smoke:", 1)[0]
        self.assertNotIn("ports:", api)
        self.assertNotIn("ports:", web)
        self.assertIn("ports:", gateway)
        self.assertIn('networks: ["frontend", "edge"]', gateway)
        self.assertNotIn("/run/secrets", gateway)


if __name__ == "__main__":
    unittest.main()
