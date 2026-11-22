# TASK-048: Policy, factuality and copyright signals

- **Parent epic:** EPIC-10 — Video Quality Assurance
- **Assigned agent:** QA and Security Engineer
- **Priority:** P1
- **Dependencies:** TASK-047
- **Estimated complexity:** 12 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** ARCHITECTURE; MASTER PROMPT
- **GitHub issue:** [#171](https://github.com/dhruv0641/Dolla/issues/171)
- **Branch:** `feature/TASK-048-policy-factuality-copyright-signals`
- **Blockers:** None for bounded local implementation; unavailable provider or human evidence must fail closed and be reported explicitly.

## User Story
As a FLOW AI Content OS operator, I want policy, factuality and copyright signals, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver policy, factuality and copyright signals as an independently verifiable capability within video quality assurance.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
QA signal contracts and service, owner-scoped persistence/migration if needed, focused tests and operator documentation. Reuse TASK-017 source evidence and TASK-047 QA report boundaries; select exact paths after targeted repository inspection.

## Acceptance Criteria
- [x] Capability is implemented behind documented interfaces and configuration.
- [x] Errors, state transitions and security boundaries are explicit and observable.
- [x] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.

## Implementation and acceptance evidence

- `PolicySignalService` deterministically maps the already validated content-review assessment into fixed POLICY, FACTUALITY and COPYRIGHT signals after requiring exact PASS `av-v1` evidence and matching content lineage.
- Signal states distinguish `NO_AUTOMATED_FLAG`, `FLAGGED` and `UNAVAILABLE`; none is represented as authoritative truth, policy clearance or legal determination. Critical findings block, lesser findings/revision requests and absent rights authority require human review.
- PASS remains an automated-stage result only. Every report structurally retains `human_approval_required=true` and `content_approved=false`.
- Unknown citation IDs, malformed/duplicate rights references, changed content, non-passing AV evidence, non-canonical findings/states/decisions and fingerprint tampering fail closed.
- The canonical fingerprint binds asset/content, upstream AV evidence, a raw-text-free review-context digest, pinned prompt/policy versions, the validated assessment, signals, findings and human boundary.
- Migration 0015 and `PolicySignalReportRepository` persist one immutable owner-scoped `signals-v1` report per active final/export asset. Exact replay is idempotent; rebinding fails closed; the database requires exact passing AV evidence and derived blocker/decision consistency.
- `docs/POLICY_SIGNAL_QA.md` records meaning, trust boundaries, recovery and explicit unverified provider/legal/live-database limits.
- Eleven service tests and four repository tests pass; 40 focused signal/review/migration regressions pass. Full suite: 420 tests passed.
- Every migration parses through `pglast`; compileall, diff hygiene and project validation (15 epics, 76 tasks, no cycles) pass.
- Live PostgreSQL execution, live policy/fact-check/rights providers, rights-record authenticity, current platform-rule completeness and human/legal judgment remain unverified and are not claimed.
- Initial independent review of commit `6eb2454a4da17367ff4c4c8c9cc9d28adebd78af` found cross-context review-result rebinding and a database path to PASS with unavailable copyright authority. Re-review of correction commit `f429d940b70340b440e27b8dcb77dbfaeffabdf6` confirmed both closed and found one remaining model-layer nested/top-level context mismatch. The final correction binds every `HumanReviewResult` at the source workflow, rechecks it at QA and in the strict report model, and makes migration 0015 require context, authority/finding/state/disposition consistency, canonical codes/severity/order and unique bounded references. Regressions cover cross-context reuse, nested provenance tampering and a rights flag without authority. Exact final correction re-review is pending.
