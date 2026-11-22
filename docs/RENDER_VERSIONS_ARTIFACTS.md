# Render Versions and Artifacts

TASK-045 adds a durable, owner-scoped record for each local render plan. It
does not execute FFmpeg, call Google Flow, publish media, or consume a paid
service.

## Contract

`RenderJobRepository.create_or_get` persists a caller-selected job UUID,
positive render version, normalized input asset UUIDs, a path-free command
manifest, and a SHA-256 plan fingerprint. Replaying the exact identity and
plan is idempotent; rebinding an existing version to different inputs or a
different job fails closed.

All repository methods require the brand, content, and owner identity. Queries
join through the owning brand and lock the render row before transitions.
Manifests reject secret-like fields, unsupported JSON values, non-finite
numbers, duplicate or noncanonical UUIDs, and oversized data.

## State and recovery

The persisted lifecycle is `PENDING -> RUNNING -> DONE` or
`PENDING -> RUNNING -> FAILED -> PENDING`. A worker claim has a bounded lease
and increments the attempt counter. The same worker can replay an active claim
without another attempt; an expired lease can be recovered by another worker.
Active leases and exhausted attempt budgets fail closed. Completion and
failure require the current unexpired lease.

Only a safe uppercase error code is retained. Raw FFmpeg output, paths,
credentials, and exception text are not persisted in the render row.

## Artifact lineage

Completion requires exactly one active same-content `FINAL_VIDEO` asset and up
to three uniquely profiled active same-content `EXPORT_VARIANT` assets. Both
the repository transaction and PostgreSQL triggers enforce lineage. A replay
of completion succeeds only when the stored final asset and the complete
artifact set match exactly.

## Operational limits and evidence

- Lease duration: 1 second to 1 hour; default 5 minutes.
- Attempt limit: 1 to 10; default 3.
- Input asset list: 1 to 100 canonical UUIDs.
- Command manifest: 65,536 UTF-8 bytes; input manifest: 4,096 bytes.
- Completion artifacts: 1 to 4, matching the final plus three platform
  variants produced by TASK-044.

Repository behavior is covered with deterministic fake-transaction tests.
Migration SQL has static contract checks. This workstation cannot load the
installed `pglast` parser because Windows Application Control blocks its DLL,
and no live PostgreSQL endpoint is configured; PostgreSQL migration execution,
locking, and trigger behavior therefore remain integration-unverified rather
than being represented as production-ready.
