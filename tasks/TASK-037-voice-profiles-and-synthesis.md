# TASK-037: Voice profiles and synthesis

- **Parent epic:** EPIC-08 — Local Audio and Voiceover
- **Assigned agent:** Media Pipeline Engineer
- **Priority:** P1
- **Dependencies:** TASK-036
- **Estimated complexity:** 4 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** ARCHITECTURE; DASHBOARD_DEMO.html
- **GitHub issue:** [#138](https://github.com/dhruv0641/Dolla/issues/138)
- **Branch:** `feature/TASK-037-voice-profiles-and-synthesis`
- **Blockers:** No code blocker. A live local TTS engine remains unselected and unverified; the implementation must fail closed rather than simulate synthesis.

## User Story
As a FLOW AI Content OS operator, I want voice profiles and synthesis, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver voice profiles and synthesis as an independently verifiable capability within local audio and voiceover.

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
- Commits `d3efe3a` and `06ded3c` implement provider-neutral profile, persistence and synthesis boundaries; GitHub issue [#138](https://github.com/dhruv0641/Dolla/issues/138) tracks delivery.
- Focused synthesis/repository suite passes 11 tests. Full non-migration backend suite passes 331 tests; the 7 real-FFmpeg tests pass after isolating one transient local tool failure.
- Independent Technical Reviewer found no blockers after the configuration-reference correction.
- Compileall, project-plan validation and diff check pass. GitHub CI must verify PostgreSQL migration parsing because Windows Application Control blocks the local `pglast` DLL.
- No concrete TTS engine/provider was selected or invoked. Live PostgreSQL concurrency, live synthesis and production readiness are not claimed.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
