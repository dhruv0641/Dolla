# TASK-024: Safe submit, polling and recovery

- **Parent epic:** EPIC-05 — Google Flow MCP Integration
- **Assigned agent:** Flow MCP Integration Engineer
- **Priority:** P0
- **Dependencies:** TASK-023
- **Estimated complexity:** 16 engineering hours (planning estimate)
- **Status:** IN_PROGRESS
- **GitHub:** Issue [#113](https://github.com/dhruv0641/Dolla/issues/113); draft PR [#114](https://github.com/dhruv0641/Dolla/pull/114); branch `feature/TASK-024-safe-submit-polling-and-recovery`.
- **Related source documents:** FLOW_MCP_ADAPTER_CONTRACT.json; ARCHITECTURE
- **External prerequisite:** Reconcile existing image job `muvi26hx-46e6c8`, currently `sent` with no final result or output path, before any retry or new generation. Do not infer success/failure or blindly resubmit.
- **External blocker:** Live reconciliation remains unavailable because current session status exposes no project URL for the job and there is no standalone job-ID lookup. Keep it unresolved; this does not authorize retry or generation.

## User Story
As a FLOW AI Content OS operator, I want safe submit, polling and recovery, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver safe submit, polling and recovery as an independently verifiable capability within google flow mcp integration.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [ ] Capability is implemented behind documented interfaces and configuration.
- [ ] Errors, state transitions and security boundaries are explicit and observable.
- [ ] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.
- [ ] Unsupported or unverified server capabilities fail closed.

## Implementation checkpoint — 2026-11-19
- Added deterministic SHA-256 request fingerprinting, a submission service that only sends a newly claimed job against a matching explicit spend approval, and an owner-scoped SQL repository that locks and rechecks quote age/expiry, account eligibility, balance/reset freshness and current reservation capacity before inserting `RESERVED`.
- Added migration `0006_generation_job_credit_reservation.sql` to bind one generation job to at most one credit reservation. Ambiguous submit responses transition to `REMOTE_SUBMISSION_UNKNOWN`; duplicate claims never call Flow again.
- Added strict in-flight and resume-result interpreters that preserve UNKNOWN on missing/malformed/mismatched states, recognize the actual `files` response shape, and a persisted-context resume service. The separate `JOB_RESUME` operation requires the existing external ID and original persisted prompt/project/output path scoped to the verified account alias and authenticated owner, plus `resume=true` and `auto_confirm=false`; it remains unavailable unless explicitly bound to the inspected manifest. New video submission uses actual tool arguments `duration` and `ratio`.
- Added focused coverage for idempotency, owner/reservation checks, duplicate claims, quote expiration/account pause gates, ambiguous job states, actual response shape, safe resume and rejected submission-shaped resume calls. Focused suite: 43 passed; full suite: 262 passed; all migrations parse; project-plan validation and compileall pass; `git diff --check` clean. Independent Technical Reviewer re-review found no remaining code blockers. TASK-024 stays IN_PROGRESS because the old live Flow job still lacks a project URL and terminal result; no live resume/reconciliation or generation is claimed.
- Live read-only `flow_status` on 2026-11-19 reports `connected=true`, `logged_in=true`, and the old image job in `sent`; no project URL or terminal status was returned. No resume, retry, cancellation, generation or paid operation was called. See `docs/FLOW_JOB_RECOVERY.md` and `docs/MCP_CAPABILITY_MATRIX.md`.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
