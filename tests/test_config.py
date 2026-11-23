import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flowx_os.config import ConfigurationError, Settings  # noqa: E402


class SettingsTests(unittest.TestCase):
    def test_development_defaults_need_no_credentials(self) -> None:
        settings = Settings.from_env({})
        self.assertEqual(settings.environment, "development")
        self.assertEqual(settings.log_level, "INFO")
        self.assertEqual(settings.storage_root, Path("./data"))
        self.assertIsNone(settings.database_credentials_ref)
        self.assertFalse(settings.youtube_publishing_enabled)
        self.assertFalse(settings.instagram_publishing_enabled)
        self.assertFalse(settings.facebook_publishing_enabled)
        self.assertFalse(settings.platform_reconciliation_enabled)
        self.assertFalse(settings.publication_scheduling_enabled)
        self.assertFalse(settings.platform_analytics_enabled)
        self.assertFalse(settings.comment_ingestion_enabled)
        self.assertFalse(settings.community_analysis_enabled)
        self.assertFalse(settings.community_reply_drafting_enabled)
        self.assertFalse(settings.community_official_responses_enabled)

    def test_secret_references_are_retained_as_references(self) -> None:
        settings = Settings.from_env(
            {
                "FLOWX_DATABASE_CREDENTIALS_REF": "secretref://windows-credential-manager/flowx/dev/db",
                "FLOWX_GEMINI_CREDENTIALS_REF": "secretref://windows-credential-manager/flowx/dev/gemini",
            }
        )
        self.assertEqual(
            settings.database_credentials_ref,
            "secretref://windows-credential-manager/flowx/dev/db",
        )
        self.assertEqual(
            settings.gemini_credentials_ref,
            "secretref://windows-credential-manager/flowx/dev/gemini",
        )

    def test_production_requires_database_reference(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "FLOWX_DATABASE_CREDENTIALS_REF"):
            Settings.from_env({"FLOWX_ENVIRONMENT": "production"})

    def test_raw_credential_is_rejected_without_echoing_value(self) -> None:
        secret = "example-token-do-not-log"
        with self.assertRaises(ConfigurationError) as raised:
            Settings.from_env({"FLOWX_GEMINI_CREDENTIALS_REF": secret})
        self.assertNotIn(secret, str(raised.exception))

    def test_invalid_environment_and_log_level_are_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"FLOWX_ENVIRONMENT": "prod"})
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"FLOWX_LOG_LEVEL": "VERBOSE"})

    def test_youtube_publishing_requires_explicit_boolean_enablement(self) -> None:
        enabled = Settings.from_env({"FLOWX_YOUTUBE_PUBLISHING_ENABLED": "true"})
        self.assertTrue(enabled.youtube_publishing_enabled)
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"FLOWX_YOUTUBE_PUBLISHING_ENABLED": "yes"})

    def test_instagram_publishing_requires_explicit_boolean_enablement(self) -> None:
        enabled = Settings.from_env({"FLOWX_INSTAGRAM_PUBLISHING_ENABLED": "true"})
        self.assertTrue(enabled.instagram_publishing_enabled)
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"FLOWX_INSTAGRAM_PUBLISHING_ENABLED": "yes"})

    def test_facebook_publishing_requires_explicit_boolean_enablement(self) -> None:
        enabled = Settings.from_env({"FLOWX_FACEBOOK_PUBLISHING_ENABLED": "true"})
        self.assertTrue(enabled.facebook_publishing_enabled)
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"FLOWX_FACEBOOK_PUBLISHING_ENABLED": "yes"})

    def test_platform_reconciliation_requires_explicit_boolean_enablement(self) -> None:
        enabled = Settings.from_env({"FLOWX_PLATFORM_RECONCILIATION_ENABLED": "true"})
        self.assertTrue(enabled.platform_reconciliation_enabled)
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"FLOWX_PLATFORM_RECONCILIATION_ENABLED": "yes"})

    def test_publication_scheduling_requires_explicit_boolean_enablement(self) -> None:
        enabled = Settings.from_env({"FLOWX_PUBLICATION_SCHEDULING_ENABLED": "true"})
        self.assertTrue(enabled.publication_scheduling_enabled)
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"FLOWX_PUBLICATION_SCHEDULING_ENABLED": "yes"})

    def test_platform_analytics_requires_explicit_boolean_enablement(self) -> None:
        enabled = Settings.from_env({"FLOWX_PLATFORM_ANALYTICS_ENABLED": "true"})
        self.assertTrue(enabled.platform_analytics_enabled)
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"FLOWX_PLATFORM_ANALYTICS_ENABLED": "yes"})

    def test_comment_ingestion_requires_explicit_boolean_enablement(self) -> None:
        enabled = Settings.from_env({"FLOWX_COMMENT_INGESTION_ENABLED": "true"})
        self.assertTrue(enabled.comment_ingestion_enabled)
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"FLOWX_COMMENT_INGESTION_ENABLED": "yes"})

    def test_community_analysis_requires_explicit_boolean_enablement(self) -> None:
        enabled = Settings.from_env({"FLOWX_COMMUNITY_ANALYSIS_ENABLED": "true"})
        self.assertTrue(enabled.community_analysis_enabled)
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"FLOWX_COMMUNITY_ANALYSIS_ENABLED": "yes"})

    def test_community_reply_drafting_requires_explicit_boolean_enablement(self) -> None:
        enabled = Settings.from_env({"FLOWX_COMMUNITY_REPLY_DRAFTING_ENABLED": "true"})
        self.assertTrue(enabled.community_reply_drafting_enabled)
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"FLOWX_COMMUNITY_REPLY_DRAFTING_ENABLED": "yes"})

    def test_community_official_responses_require_explicit_boolean_enablement(self) -> None:
        enabled = Settings.from_env({"FLOWX_COMMUNITY_OFFICIAL_RESPONSES_ENABLED": "true"})
        self.assertTrue(enabled.community_official_responses_enabled)
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"FLOWX_COMMUNITY_OFFICIAL_RESPONSES_ENABLED": "yes"})

    def test_empty_storage_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "FLOWX_STORAGE_ROOT"):
            Settings.from_env({"FLOWX_STORAGE_ROOT": " "})

    def test_env_file_values_are_overridden_by_process_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "FLOWX_ENVIRONMENT=test\n"
                "FLOWX_LOG_LEVEL=DEBUG\n"
                "FLOWX_GEMINI_CREDENTIALS_REF=secretref://local/gemini\n",
                encoding="utf-8",
            )
            settings = Settings.from_env_file(env_file, {"FLOWX_LOG_LEVEL": "WARNING"})
        self.assertEqual(settings.environment, "test")
        self.assertEqual(settings.log_level, "WARNING")
        self.assertEqual(settings.gemini_credentials_ref, "secretref://local/gemini")


if __name__ == "__main__":
    unittest.main()
