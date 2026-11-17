# Google Flow MCP Capability Matrix

**Status:** No Google Flow MCP server or tool manifest was present in the supplied materials or the connected MCP resource inventory checked on 2026-11-17. The adapter JSON is a proposed logical contract, not actual tool documentation. All capabilities are **UNVERIFIED**; the connected resource inventory exposed no Flow server to inspect.

| Capability | Contract expectation | Status | Next check |
|---|---|---|---|
| Server identity/transport | stdio or streamable HTTP | UNVERIFIED | Obtain configured server identity and manifest. |
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
