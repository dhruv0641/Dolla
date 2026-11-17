# Health and readiness

`GET /healthz` is process liveness only. It returns `alive` while the API can answer and does not report integration status.

`GET /readyz` evaluates explicitly configured, fast, side-effect-free dependency probes. It returns HTTP 200 only when at least one probe is configured and every probe returns true; otherwise it returns HTTP 503 with per-dependency states (`ready`, `unavailable`, or `not_configured`). Probe exception text is suppressed. Do not place credentials, query results, or other private data in probe names or responses.

The application factory accepts probes for future integration wiring. It does not create or claim a database, Flow MCP, or publishing connection. The default empty probe set reports not ready until deployment wiring is configured.
