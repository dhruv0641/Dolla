"""Side-effect-free application settings with secret-reference validation.

This module reads configuration only when ``Settings.from_env`` is called.
It deliberately stores secret references, never resolves or logs secret values.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigurationError(ValueError):
    """Safe-to-display configuration error that does not echo supplied values."""


_SECRET_REF = re.compile(r"^secretref://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$")
_ENVIRONMENTS = {"development", "test", "production"}
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _secret_ref(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key, "").strip()
    if not value:
        return None
    if not _SECRET_REF.fullmatch(value):
        raise ConfigurationError(
            f"{key} must be a secret reference (secretref://provider/path); raw values are not accepted."
        )
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    log_level: str
    storage_root: Path
    database_credentials_ref: str | None
    gemini_credentials_ref: str | None
    flow_credentials_ref: str | None
    youtube_credentials_ref: str | None
    youtube_publishing_enabled: bool
    meta_credentials_ref: str | None
    instagram_publishing_enabled: bool
    facebook_publishing_enabled: bool
    platform_reconciliation_enabled: bool
    publication_scheduling_enabled: bool
    platform_analytics_enabled: bool
    comment_ingestion_enabled: bool
    community_analysis_enabled: bool
    community_reply_drafting_enabled: bool

    @classmethod
    def from_env_file(
        cls,
        path: str | Path = ".env",
        environ: Mapping[str, str] | None = None,
    ) -> "Settings":
        """Load a simple KEY=VALUE file, then let process environment override it.

        No shell expansion, command substitution, or interpolation is performed.
        """
        file_values: dict[str, str] = {}
        env_path = Path(path)
        if env_path.exists():
            for line_number, raw_line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), 1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    raise ConfigurationError(f"Invalid .env syntax at line {line_number}.")
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not _ENV_KEY.fullmatch(key):
                    raise ConfigurationError(f"Invalid environment variable name at line {line_number}.")
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                    value = value[1:-1]
                file_values[key] = value

        process_values = os.environ if environ is None else environ
        file_values.update(process_values)
        return cls.from_env(file_values)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        """Parse and validate process environment or a supplied mapping."""
        env = os.environ if environ is None else environ
        environment = env.get("FLOWX_ENVIRONMENT", "development").strip().lower()
        if environment not in _ENVIRONMENTS:
            raise ConfigurationError("FLOWX_ENVIRONMENT must be development, test, or production.")

        log_level = env.get("FLOWX_LOG_LEVEL", "INFO").strip().upper()
        if log_level not in _LOG_LEVELS:
            raise ConfigurationError("FLOWX_LOG_LEVEL must be a standard Python logging level.")

        storage_value = env.get("FLOWX_STORAGE_ROOT", "./data").strip()
        if not storage_value:
            raise ConfigurationError("FLOWX_STORAGE_ROOT must not be empty.")
        storage_root = Path(storage_value).expanduser()

        database_ref = _secret_ref(env, "FLOWX_DATABASE_CREDENTIALS_REF")
        if environment == "production" and database_ref is None:
            raise ConfigurationError("FLOWX_DATABASE_CREDENTIALS_REF is required in production.")

        youtube_enabled = env.get("FLOWX_YOUTUBE_PUBLISHING_ENABLED", "false").strip().lower()
        if youtube_enabled not in {"true", "false"}:
            raise ConfigurationError("FLOWX_YOUTUBE_PUBLISHING_ENABLED must be true or false.")
        instagram_enabled = env.get("FLOWX_INSTAGRAM_PUBLISHING_ENABLED", "false").strip().lower()
        if instagram_enabled not in {"true", "false"}:
            raise ConfigurationError("FLOWX_INSTAGRAM_PUBLISHING_ENABLED must be true or false.")
        facebook_enabled = env.get("FLOWX_FACEBOOK_PUBLISHING_ENABLED", "false").strip().lower()
        if facebook_enabled not in {"true", "false"}:
            raise ConfigurationError("FLOWX_FACEBOOK_PUBLISHING_ENABLED must be true or false.")
        reconciliation_enabled = env.get(
            "FLOWX_PLATFORM_RECONCILIATION_ENABLED", "false"
        ).strip().lower()
        if reconciliation_enabled not in {"true", "false"}:
            raise ConfigurationError("FLOWX_PLATFORM_RECONCILIATION_ENABLED must be true or false.")
        scheduling_enabled = env.get(
            "FLOWX_PUBLICATION_SCHEDULING_ENABLED", "false"
        ).strip().lower()
        if scheduling_enabled not in {"true", "false"}:
            raise ConfigurationError("FLOWX_PUBLICATION_SCHEDULING_ENABLED must be true or false.")
        analytics_enabled = env.get(
            "FLOWX_PLATFORM_ANALYTICS_ENABLED", "false"
        ).strip().lower()
        if analytics_enabled not in {"true", "false"}:
            raise ConfigurationError("FLOWX_PLATFORM_ANALYTICS_ENABLED must be true or false.")
        comment_ingestion_enabled = env.get(
            "FLOWX_COMMENT_INGESTION_ENABLED", "false"
        ).strip().lower()
        if comment_ingestion_enabled not in {"true", "false"}:
            raise ConfigurationError("FLOWX_COMMENT_INGESTION_ENABLED must be true or false.")
        community_analysis_enabled = env.get(
            "FLOWX_COMMUNITY_ANALYSIS_ENABLED", "false"
        ).strip().lower()
        if community_analysis_enabled not in {"true", "false"}:
            raise ConfigurationError("FLOWX_COMMUNITY_ANALYSIS_ENABLED must be true or false.")
        community_reply_drafting_enabled = env.get(
            "FLOWX_COMMUNITY_REPLY_DRAFTING_ENABLED", "false"
        ).strip().lower()
        if community_reply_drafting_enabled not in {"true", "false"}:
            raise ConfigurationError(
                "FLOWX_COMMUNITY_REPLY_DRAFTING_ENABLED must be true or false."
            )

        return cls(
            environment=environment,
            log_level=log_level,
            storage_root=storage_root,
            database_credentials_ref=database_ref,
            gemini_credentials_ref=_secret_ref(env, "FLOWX_GEMINI_CREDENTIALS_REF"),
            flow_credentials_ref=_secret_ref(env, "FLOWX_FLOW_CREDENTIALS_REF"),
            youtube_credentials_ref=_secret_ref(env, "FLOWX_YOUTUBE_CREDENTIALS_REF"),
            youtube_publishing_enabled=youtube_enabled == "true",
            meta_credentials_ref=_secret_ref(env, "FLOWX_META_CREDENTIALS_REF"),
            instagram_publishing_enabled=instagram_enabled == "true",
            facebook_publishing_enabled=facebook_enabled == "true",
            platform_reconciliation_enabled=reconciliation_enabled == "true",
            publication_scheduling_enabled=scheduling_enabled == "true",
            platform_analytics_enabled=analytics_enabled == "true",
            comment_ingestion_enabled=comment_ingestion_enabled == "true",
            community_analysis_enabled=community_analysis_enabled == "true",
            community_reply_drafting_enabled=community_reply_drafting_enabled == "true",
        )
