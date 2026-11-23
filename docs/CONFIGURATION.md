# Configuration and Secret References

Copy `.env.example` to `.env` for local development. `.env` is ignored by Git. The example contains only nonfunctional `secretref://` placeholders; replace them with references supported by the selected operating-system secret store. Never put tokens, passwords, Flow cookies, OAuth refresh tokens, or API keys in tracked files, prompts, logs, or SQL.

`flowx_os.config.Settings.from_env_file()` reads `.env` when explicitly called, then applies process environment values as overrides. `Settings.from_env()` reads only the supplied mapping or process environment. Neither method runs at import time. They validate `FLOWX_ENVIRONMENT` (`development`, `test`, or `production`), `FLOWX_LOG_LEVEL`, and `FLOWX_STORAGE_ROOT`, and accept secret references only in the form `secretref://provider/path`. The module does not resolve secret values or connect to a secret store. A later integration must resolve references using OS-protected storage and must never log the returned values.

`FLOWX_STORAGE_ROOT` defaults to `./data`; `AssetIngestService` stores files below its `assets/` directory. Mount a persistent volume at that root and restrict filesystem permissions to the service identity before enabling worker ingestion. The current Compose shell does not yet wire a database pool or asset worker, so setting the root alone does not enable ingestion.

Production requires `FLOWX_DATABASE_CREDENTIALS_REF`. Gemini API billing, Google AI Pro entitlements, Flow account credentials, YouTube OAuth, and Meta OAuth use separate references. Leave optional references unset until the corresponding integration is authorized. No credentials are required to run planning validation or the configuration unit tests.

`FLOWX_COMMENT_INGESTION_ENABLED` defaults to `false`. Turning it on only enables the application boundary described in `AUTHORIZED_COMMENT_INGESTION.md`; it does not connect an account, resolve a credential reference, install a provider adapter, retrieve a comment, or authorize a reply. A deployment must separately supply an official provider implementation and current owned-channel authorization. Unknown authorization or reconciliation state fails closed.

`FLOWX_COMMUNITY_ANALYSIS_ENABLED` also defaults to `false`. Turning it on enables only the local, deterministic `community-theme-v1` and `community-safety-v1` analysis described in `COMMUNITY_THEME_SAFETY_ANALYSIS.md`. It does not invoke Gemini or another model, and `NO_DETECTED_SIGNAL` is not a safety guarantee. Reports remain inert and cannot draft, moderate, reply, publish, connect accounts or spend.

`FLOWX_COMMUNITY_REPLY_DRAFTING_ENABLED` defaults to `false`. Enabling it permits only the fixed local `community-reply-v1` templates and escalation records documented in `COMMUNITY_REPLY_DRAFTS.md`. Comment text is never interpolated into a template. Every draft still requires human approval and grants no posting, moderation or provider authority.

Example local check:

```powershell
Copy-Item .env.example .env
python -m unittest discover -s tests -v
```

The example references are placeholders and do not prove that an OS secret store is configured.
