# TASK-047: Visual and audio evaluation

- **Parent epic:** EPIC-10 — Video Quality Assurance
- **Assigned agent:** QA and Security Engineer
- **Priority:** P1
- **Dependencies:** TASK-046
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** ARCHITECTURE; MASTER PROMPT
- **GitHub issue:** [#168](https://github.com/dhruv0641/Dolla/issues/168)
- **Branch:** `feature/TASK-047-visual-audio-evaluation`
- **Blockers:** None for local implementation. Production threshold calibration and subjective/semantic review evidence must be reported separately.

## User Story
As a FLOW AI Content OS operator, I want visual and audio evaluation, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver visual and audio evaluation as an independently verifiable capability within video quality assurance.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

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

- `AvEvaluationService` requires exact passing `integrity-v1` evidence and revalidates owner-scoped final/export lineage before evaluating immutable media bytes.
- `LocalFfmpegAvAnalyzer` uses a verified private snapshot and a fixed, bounded FFmpeg filter graph for black, freeze, silence, EBU R128 integrated loudness and true-peak measurements. Tool output is parsed into closed numeric evidence and then discarded.
- Strict policy, finding and report models derive PASS, FAIL or NEEDS_HUMAN without a fabricated score. Semantic visual quality, speech intelligibility and mix preference remain explicitly `NOT_EVALUATED`.
- Migration 0014 and `AvReportRepository` persist one immutable owner-scoped `av-v1` report per asset, bound to the exact passing integrity fingerprint. Exact replay is idempotent and rebinding fails closed.
- Shared media snapshot hardening rejects symlinks, non-regular files and multiple hard links and verifies size and SHA-256 before analysis.
- `docs/VISUAL_AUDIO_QA.md` documents defaults, trust boundaries, recovery and unverified production calibration/subjective-review limits.
- Full application and migration suite: 404 tests passed before the final migration-only NULL-safety hardening. After that hardening, 34 focused QA, repository, probe and migration tests passed; every migration parsed through `pglast`.
- Compileall, diff hygiene and project validation (15 epics, 76 tasks, no cycles) pass.
- Real generated fixtures verify clean moving video/tone and measured black, freeze and silence intervals. Live PostgreSQL trigger/locking execution, production threshold calibration, diverse production media and human subjective judgments remain unverified and are not claimed.
- Independent Technical Reviewer found no blocker on exact implementation commit `3be9d7c7ba3a60c7a449c2cd01bffaf747ef9ae0`. The independently verified command grouping passed 20 AV/probe tests, 13 migration tests with all SQL parsed through `pglast`, and the project validator. The reported residual boundaries are live PostgreSQL behavior, production media diversity and threshold calibration, human subjective judgment, and FFmpeg child-process containment beyond the spawned process.
