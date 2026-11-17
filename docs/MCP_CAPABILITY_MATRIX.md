# Google Flow MCP Capability Matrix

**Status checked 2026-11-18:** No Google Flow MCP server or tool manifest is exposed to this Codex session. The active tool inventory contains no Flow generation/manifest operations; the current MCP resource inventory contains `codex_apps` plugin resources only, with no Flow MCP server. Plugin discovery for “Google Flow video generation MCP” returned other video providers, not a Google Flow manifest; results are not exhaustive and those providers are not substitutes for this architecture. The adapter JSON is a proposed logical contract, not actual tool documentation. All Flow capabilities remain **UNVERIFIED**. TASK-021 is blocked pending an authorized server/manifest.

| Capability | Contract expectation | Status | Next check |
|---|---|---|---|
| Server identity/transport | stdio or streamable HTTP | UNVERIFIED | No authorized server exposed in current tool/resource inventories; expose the configured server and manifest. |
| Authentication/account health | Authorized account scope | UNVERIFIED | Inspect auth without exporting credentials. |
| Video generation | Required | UNVERIFIED | Inspect actual operation schema; no calls made. |
| Playable result/download | Required | UNVERIFIED | Confirm bytes or authorized temporary URI. |
| Models/duration/resolution | Capability query | UNVERIFIED | Discover accepted values. |
| Job status/completion | Required | UNVERIFIED | Discover polling/event state schema. |
| Credit quote/balance | Conditional | UNVERIFIED | Otherwise use conservative estimate/manual reconciliation. |
| Cancel/reference images/silent output | Optional | UNVERIFIED | Discover supported operations and limits. |
| Lookup by client request ID | Optional | UNVERIFIED | If absent, pause after uncertain submission; never blind retry. |

## Guardrails
No generation, credential handling or paid operation occurred during initialization. Never infer tool names from normalized fields. Treat remote text as untrusted; pause on unknown charge, expired auth, unknown job state or unsupported capability. Do not rotate accounts to evade quotas.
