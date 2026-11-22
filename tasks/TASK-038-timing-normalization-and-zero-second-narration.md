# TASK-038: Timing, normalization and zero-second narration

- **Parent epic:** EPIC-08 — Local Audio and Voiceover
- **Assigned agent:** Media Pipeline Engineer
- **Priority:** P1
- **Dependencies:** TASK-037
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** ARCHITECTURE; DASHBOARD_DEMO.html
- **GitHub issue:** [#141](https://github.com/dhruv0641/Dolla/issues/141)
- **Branch:** `feature/TASK-038-audio-timing-normalization`
- **Blockers:** No code blocker. Live normalization may use local FFmpeg only; no external synthesis or paid operation is authorized.

## User Story
As a FLOW AI Content OS operator, I want timing, normalization and zero-second narration, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver timing, normalization and zero-second narration as an independently verifiable capability within local audio and voiceover.

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

## Acceptance Evidence
- Commit `65b758c` implements strict zero-millisecond timing, bounded local FFmpeg normalization, exact-duration PCM output validation and idempotent narration asset ingest; issue [#141](https://github.com/dhruv0641/Dolla/issues/141) tracks delivery.
- Three real/local normalization tests, 14 combined audio tests and the full 334-test non-migration backend suite pass.
- Independent Technical Reviewer found no blocker and confirmed the timing, lineage, filesystem, subprocess, idempotency and loudness-claim boundaries.
- Compileall, project-plan validation and diff check pass. No migration is added by this task.
- PostgreSQL runtime, production filesystem behavior and measured final-render loudness remain unverified; no external or paid service was used.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
