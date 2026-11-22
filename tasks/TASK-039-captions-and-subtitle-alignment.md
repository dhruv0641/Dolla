# TASK-039: Captions and subtitle alignment

- **Parent epic:** EPIC-08 — Local Audio and Voiceover
- **Assigned agent:** Media Pipeline Engineer
- **Priority:** P1
- **Dependencies:** TASK-038
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** ARCHITECTURE; DASHBOARD_DEMO.html
- **GitHub issue:** [#144](https://github.com/dhruv0641/Dolla/issues/144)
- **Branch:** `feature/TASK-039-caption-subtitle-alignment`
- **Blockers:** No code blocker. Caption generation must remain deterministic/local and must not claim transcription or word-level alignment without evidence.

## User Story
As a FLOW AI Content OS operator, I want captions and subtitle alignment, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver captions and subtitle alignment as an independently verifiable capability within local audio and voiceover.

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
- Commit `a922bbf` implements owner-scoped storyboard/audio evidence binding, scene-bounded deterministic cues, safe SRT rendering and idempotent caption asset ingest; issue [#144](https://github.com/dhruv0641/Dolla/issues/144) tracks delivery.
- Four focused caption tests, 18 combined audio tests and the full 338-test non-migration backend suite pass.
- Independent Technical Reviewer found no blocker and confirmed narration fidelity, timing, wrapping, Unicode/SRT safety, lineage, idempotency and honest alignment claims.
- Compileall, project-plan validation and diff check pass. No migration is added by this task.
- Word-level timing, transcription, PostgreSQL runtime and production asset-store behavior remain unverified and are not claimed.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
