# Scene retry limits and spend gate

TASK-049 closes the gap between a definitive scene-generation failure and scheduling another paid attempt. It does not submit, resume or cancel a Google Flow job and does not itself spend credits.

## Preconditions

- The failed job and scene must belong to the authenticated owner.
- The remote outcome must be definitive. `REMOTE_SUBMISSION_UNKNOWN` and other ambiguous outcomes remain blocked and never enter this retry path.
- The current job status and scene retry counter must identify the same attempt.
- The configured `SceneRetryPolicy` must allow another attempt. The default policy permits two regenerations after the initial attempt.
- A retryable failure must have a distinct, owner-scoped `RESERVED` credit reservation for the next attempt.
- The reservation quote, observed daily/monthly balances, account health/compliance, reset/cycle window and approval verification must all be fresh at the transactional decision time.
- The approval verifier must confirm `VIDEO_GENERATE` for the exact account and reserved credit ceiling. Only a SHA-256 approval fingerprint is persisted; the raw approval reference is not stored in retry-gate evidence.

Job ownership and a repository-sourced owner-scoped reservation snapshot are both preflighted before the account/reservation identity is sent to the injected approval verifier. Ownership and all mutable spend state are checked again while the failed job, scene, reservation and account are locked.

## Decisions

Every newly recorded definitive failure receives one immutable `ALLOW` or `DENY` retry-gate decision and a stable reason:

- `ELIGIBLE`: attempt limit, exact reservation, fresh wallet state and explicit approval all pass; the scene enters `RETRY_WAIT`.
- `FAILURE_NOT_RETRYABLE`: the observed failure class is not safe to retry.
- `ATTEMPT_LIMIT_EXHAUSTED`: the configured regeneration bound has been reached.
- `RESERVATION_UNAVAILABLE`: no next-attempt reservation was supplied.
- `APPROVAL_REQUIRED`, `APPROVAL_REJECTED`, `APPROVAL_UNAVAILABLE`: explicit spend approval is missing, false or could not be verified.
- `SPEND_STATE_INVALID`: the reservation, quote, account, balances, approval freshness or reservation reuse check failed.

All reasons except `ELIGIBLE` are durable no-retry decisions and leave the scene `FAILED`. This conservative v1 behavior prevents an automatic retry from becoming spend-authorized later through changed external state. An operator must create a separately reviewed workflow attempt if policy permits.

## Idempotency and next submission

The failed generation job is the idempotency key. A replay returns its stored decision before contacting the approval provider. An allowed retry binds one unique next reservation to the failed job. Both the repository and migration trigger require the next attempt to claim that exact prior-gate reservation; the submission path also rechecks owner, request ID, model, duration, quote, wallet freshness, account state, attempt index and explicit spend authorization before any Flow invocation.

Scheduling is permission to attempt the normal claim flow, not proof that generation occurred and not authorization to bypass `auto_confirm`, account, quota or human controls.

## Persistence

Migration 0016 adds the decision, stable reason, unique retry reservation, approval fingerprint, configured maximum attempts and decision time to `generation_jobs`. New transitions to `FAILED` require a complete gate envelope. `ALLOW` requires an eligible same-owner reserved wallet record; `DENY` cannot carry reservation or approval evidence. Once written, retry-gate fields, `retry_scheduled`, and the decision row cannot be updated or deleted.

Pre-migration failed rows are retained as legacy history; they cannot be represented as new verified TASK-049 decisions. Repository replay fails closed if a failed row lacks the new evidence.

## Unverified boundaries

- No live approval provider, Flow account, quote, reservation, retry, generation or paid operation was invoked for TASK-049.
- PostgreSQL trigger, lock ordering and concurrent transaction behavior remain unverified until exercised against the deployment database.
- Provider-side approval revocation between verification and a later submission is handled by the submission path's independent authorization check, not by this stored scheduling decision.
