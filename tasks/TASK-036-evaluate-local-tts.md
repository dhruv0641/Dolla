# TASK-036: Evaluate local TTS

- **Parent epic:** EPIC-08 — Local Audio and Voiceover
- **Assigned agent:** Media Pipeline Engineer
- **Priority:** P1
- **Dependencies:** TASK-031
- **Estimated complexity:** 16 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub:** Issue [#135](https://github.com/dhruv0641/Dolla/issues/135); branch `feature/TASK-036-evaluate-local-tts`.
- **Related source documents:** ARCHITECTURE; DASHBOARD_DEMO.html
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want evaluate local tts, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver evaluate local tts as an independently verifiable capability within local audio and voiceover.

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

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.

## Acceptance evidence
- [x] Added a provider-neutral evaluator for explicitly configured local TTS executables with bounded version and optional voice-list probes.
- [x] Probes use closed stdin, no shell, live bounded stdout/stderr readers and timeouts; unavailable, failed, timed-out and oversized probes return explicit evidence codes.
- [x] Licensing remains `UNVERIFIED`; no synthesis, model download, network call or paid service is performed.
- [x] Focused evaluator suite: 4 passed, including fake-engine discovery and output-limit handling. Full backend suite: 330 passed. Compileall, diff check and project-plan validation pass.
- [x] Operator documentation is in `docs/TTS_EVALUATION.md`; local engine availability on this host/CI remains unverified until an operator configures candidates.
