# PostgreSQL schema review

This review covers the supplied `SCHEMA.sql` reference and the reviewed initial migration in `migrations/0001_initial_schema.sql`. The migration targets PostgreSQL 15+ and uses `pgcrypto` for `gen_random_uuid()`.

## Applied corrections

- Added the missing `assets.source_job_id → generation_jobs.id` foreign key after both tables exist, preserving generation lineage and preventing dangling references.
- Constrained `content_recommendations` so its source period cannot end before it starts.
- Retained the supplied status checks, uniqueness rules, `SKIP LOCKED` leasing example, JSONB payloads, and secret-reference-only credential columns.

## Required follow-up before multi-user production

- **Tenant isolation:** `owner_user_id` exists on brands and Flow accounts, but many child tables rely on indirect ownership and no RLS policy is supplied. Define tenant keys, ownership joins, and tested RLS policies before serving multiple users.
- **Cross-row ownership:** ordinary foreign keys do not ensure a scene, asset, report, or publication belongs to the same brand/content lineage as its related rows. Add composite tenant-aware keys or transactional domain validation.
- **Credential references:** columns are plain text references. Validate allowed URI schemes and provider/path format in application code; never resolve secrets in SQL or expose references in API responses.
- **Error and payload redaction:** `request_json`, response payloads, event payloads, and text error fields can contain prompts or provider data. Define retention, size limits, and redaction before writing external responses.
- **Credit semantics:** document the sign convention and reversal/idempotency rules for `credit_delta`; add a unique source reference if reconciliation must be replay-safe.
- **Workflow event identity:** `workflow_events.entity_id` is intentionally polymorphic and cannot use a normal foreign key. Consumers must tolerate deleted/missing entities and use `correlation_id` for tracing.
- **Deletion and retention:** define archive/delete behavior for generation attempts, assets, analytics, audit events, and outbox rows before enabling destructive operations.
- **Concurrency policy:** outbox workers need transactional lease acquisition, heartbeat/expiry behavior, and bounded retries; the example is illustrative and should not be used without those rules.

## Migration operation

`0001_initial_schema.sql` is a one-time, forward-only baseline, not an idempotent bootstrap script. Apply it to a disposable PostgreSQL 15+ database first, then record its filename and checksum in the selected migration runner. Do not apply it to a populated database. A local PostgreSQL server/client was not available during this review, so execution against PostgreSQL remains a CI/deployment verification item.
