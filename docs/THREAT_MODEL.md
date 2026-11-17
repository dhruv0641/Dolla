# FLOW AI Content OS threat model

**Review state:** repository-grounded design review, 2026-11-18. This document records controls visible in the current source and residual risks; it is not a production security certification or a penetration-test report.

## Scope and trust boundaries

The reviewed path is browser/operator → Next.js dashboard → FastAPI → PostgreSQL, with future boundaries to Google Flow MCP, model providers, local media processing, and official publishing APIs. Only the application/API and persistence foundations are represented in this repository today. Flow MCP access and publishing credentials are not configured. Treat browser input, bearer tokens, database contents, generated text/media, MCP/provider responses, and imported media as untrusted.

## Assets to protect

- User identity, role assignments, brand/content records, scripts and audience information.
- Provider credentials, Flow account identifiers, credit/usage records, OAuth grants and secret references.
- Generated media, asset lineage, workflow/outbox events, review decisions and publication state.
- Integrity of approval gates, spend limits, job leases and audit history.

## Threat and control register

| Threat | Evidence-backed controls | Residual risk and follow-up |
| --- | --- | --- |
| Forged, expired or wrong-audience access token | `TokenVerifier` pins HS256/JWT, verifies HMAC with constant-time comparison, checks issuer, audience, expiry, not-before, subject and supported roles; token length is bounded. Auth dependencies fail closed when verification is not configured. | Token issuance, revocation, rotation, key custody, MFA, refresh policy and rate limits are not implemented or verified. Define issuer lifecycle and key rotation before production. |
| Privilege escalation or cross-owner record access | Protected API routes require explicit admin/operator/reviewer roles. Brand and content queries filter on principal subject; transitions lock the owned row, validate state changes and return bounded 404/409/503 errors. SQL uses bound parameters. | PostgreSQL RLS is absent. Child records lack complete tenant-aware composite ownership constraints; multi-user production is blocked until schema and repository isolation is strengthened and tested. See `docs/SCHEMA_REVIEW.md`. |
| Secret disclosure or misuse | Settings accept secret references rather than raw credential values; secret values are not resolved or logged here. API responses omit credential references. | Provider-specific reference validation, secret-store resolution, rotation, revocation and access auditing are future work. `Settings.from_env()` requires a database credential reference when environment is production, but API startup does not currently wire settings, the database pool or token verifier; those runtime dependencies must be injected separately. Other provider credentials are unconfigured. |
| Sensitive data or prompt leakage through logs/events | Workflow event writes are parameterized, transaction-scoped, size-bounded and carry an actor/correlation ID. | The caller must redact payloads. There is no system-wide log redaction/retention policy, append-only database role, tamper-evident audit store, or proof that all auth, approval, spend and publish actions emit events. `workflow_events` is audit-shaped, not a complete security audit trail. |
| Malicious provider/MCP output or unsafe generated media | Architecture treats remote content as untrusted; generation, publishing and human approval remain gated. Actual Flow MCP is unavailable, so no provider response is trusted or acted on. | Define schema validation, content policy, media decoding/sandboxing, malware checks and provenance before accepting external outputs. Do not enable generation from an assumed manifest. |
| Replay, duplicate jobs, lost/forged state, or spend drift | Database includes workflow/outbox structures; task work has introduced bounded leases, idempotent handlers and a credit-ledger model. Generic content transitions disallow scheduling/publishing terminal transitions without future coordinated workflows. | Production PostgreSQL concurrency, outbox operations, credit reconciliation, durable event retention and end-to-end failure recovery remain unverified. Preserve unique idempotency/source references and reconcile external state before recording success. |
| Unauthorized or duplicate public publishing | Publishing uses a future official-interface design; human review and auto-publish-off are defaults. Current APIs do not expose publish actions. | OAuth lifecycle, permission minimization, schedule locking, remote verification, duplicate prevention and incident recovery are not implemented or verified. Public publishing must remain disabled until these controls are exercised. |
| Data loss, resource exhaustion or service compromise | Configuration is explicit, bounded token and event payload sizes exist, SQL values are parameterized, and the migration is documented as forward-only. | TLS/network boundaries, deployment hardening, backups/restore tests, quotas, rate limits, security monitoring, dependency scanning and incident response are not established by this review. Complete TASK-073–076 and deployment checks. |

## Access and audit baseline

Protected authentication and content routes fail closed when token verification is absent. The service descriptor (`/`), liveness probe (`/healthz`) and readiness probe (`/readyz`) are public. `/readyz` returns configured dependency names and categorical status values; keep those names non-sensitive, and restrict or sanitize the endpoint if deployment-specific names reveal internal topology. Roles currently are `admin`, `operator`, and `reviewer`; dependencies on protected routes are the authorization boundary, and repository owner filters are the row-ownership boundary. Keep tokens out of browser local storage, URLs, logs, issue text and generated prompts. Never log secret values or raw provider payloads. Persist correlation IDs and sanitized actor/action/target/outcome metadata for security-relevant actions.

The current `WorkflowEventStore` offers an append helper inside the caller's transaction; it does not make rows immutable and does not guarantee every security event is recorded. Before production, define event taxonomy, mandatory transactional emission points, redaction rules, retention, read access, tamper detection and alerting. Test tenant isolation under PostgreSQL roles/RLS and test audit coverage for denied access, content transitions, approvals, spend and publishing.

## Release gates and ownership

1. Before multi-user production: tenant-aware schema/repository boundaries, RLS or equivalent enforcement, and adversarial cross-owner tests (Backend Engineer / QA and Security Engineer).
2. Before external generation: verified authorized Flow MCP manifest, auth/capability checks, bounded credit accounting, output validation and human approval (Flow MCP Integration Engineer / QA and Security Engineer).
3. Before public publishing: official OAuth scopes, duplicate-safe scheduling, approval enforcement, remote reconciliation and incident rollback (Publishing Integration Engineer / QA and Security Engineer).
4. Before deployment: secret-store and key rotation operations, encrypted backup/restore evidence, observability/alerts, network/TLS hardening and documented incident runbooks (DevOps Engineer).

Relevant backlog: TASK-021–030 (Flow capability and credit controls), TASK-046–050 (QC and approvals), TASK-057–061 (publishing), and TASK-072–076 (security, observability and release). No external service, database, credential or paid operation was exercised for this review.
