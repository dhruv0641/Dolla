# Flow job submission and recovery

## Submission identity

Before a generation request is sent, `FlowJobSubmissionService` computes a SHA-256 idempotency fingerprint from the opaque account reference, scene ID, attempt index, model, prompt, reserved request ID, and canonical settings/arguments. Flow video submission arguments use the inspected field names `duration` and `ratio`. `FlowGenerationJobRepository` locks the account and reservation, verifies account/scene owner, fresh unexpired quote, healthy/unpaused/compliant account, fresh balance and reset windows, a matching active credit reservation and current available-credit limits, then inserts a `RESERVED` generation row under the unique fingerprint. Migration `0006` binds each generation row to at most one credit reservation. Repeating the same identity returns the existing row and never calls Flow again. Only a newly inserted `RESERVED` row can reach Flow, and the supplied approval ceiling must cover the reserved quote. If the call or response is ambiguous, the job moves to `REMOTE_SUBMISSION_UNKNOWN`; never resend it automatically. Do not log prompts or raw request bodies to expose them alongside fingerprints.

## Status interpretation

`flow_status` only returns the current session and in-flight jobs. `observe_in_flight_job` accepts exactly one record matching the expected external job ID and recognizes a small allowlist of in-flight phases. Missing records, duplicates, unknown phases, malformed payloads, and mismatched IDs produce `UNKNOWN`; absence never means success or failure.

`observe_resume_result` requires a matching external job ID. Explicit in-flight states map to `RUNNING`; explicit failure states map to `FAILED`; a success state requires a matching output path (or one entry in Flow's observed `files` array) before it maps to `SUCCEEDED`. Every other response remains `UNKNOWN`. Returned file paths remain untrusted and require separate filesystem and media validation before use.

## Safe resume

`FlowJobResumeService` first loads the external ID, project URL, original prompt, and output directory from a persisted job row scoped to the authenticated owner and approved account alias. If any field is unavailable, it returns `UNKNOWN` without calling Flow. The adapter requires `resume=true`, `auto_confirm=false`, and only those stored arguments plus the external job ID. The manifest must explicitly bind this operation to an inspected Flow tool schema. It does not require spend authorization because the exposed Flow tool documents `resume=true` as wait/download-only; with `auto_confirm=false`, it cannot submit a new generation through this boundary.

If the tool is absent, the manifest is stale, the tool schema requires unsupported inputs, account authorization is stale, transport fails, or response parsing cannot match the existing job, fail closed and leave the job unresolved. Do not fall back to generation. No standalone per-job lookup or cancellation tool is currently exposed.

## Live limitation

The current session reports an old image job as `sent`, but its project URL and terminal result are unavailable. The app-side MCP transport is not configured. The job must remain unresolved until a supported read-only status/resume path provides matching evidence; do not retry, cancel, spend credits, or claim completion based solely on elapsed time or a missing in-flight entry.
