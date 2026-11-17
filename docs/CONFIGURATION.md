# Configuration and Secret References

Copy `.env.example` to `.env` for local development. `.env` is ignored by Git. The example contains only nonfunctional `secretref://` placeholders; replace them with references supported by the selected operating-system secret store. Never put tokens, passwords, Flow cookies, OAuth refresh tokens, or API keys in tracked files, prompts, logs, or SQL.

`flowx_os.config.Settings.from_env_file()` reads `.env` when explicitly called, then applies process environment values as overrides. `Settings.from_env()` reads only the supplied mapping or process environment. Neither method runs at import time. They validate `FLOWX_ENVIRONMENT` (`development`, `test`, or `production`), `FLOWX_LOG_LEVEL`, and `FLOWX_STORAGE_ROOT`, and accept secret references only in the form `secretref://provider/path`. The module does not resolve secret values or connect to a secret store. A later integration must resolve references using OS-protected storage and must never log the returned values.

Production requires `FLOWX_DATABASE_CREDENTIALS_REF`. Gemini API billing, Google AI Pro entitlements, Flow account credentials, YouTube OAuth, and Meta OAuth use separate references. Leave optional references unset until the corresponding integration is authorized. No credentials are required to run planning validation or the configuration unit tests.

Example local check:

```powershell
Copy-Item .env.example .env
python -m unittest discover -s tests -v
```

The example references are placeholders and do not prove that an OS secret store is configured.
