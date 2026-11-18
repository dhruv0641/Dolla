# TASK-055: QA, voice, calendar and publishing screens

- **Parent epic:** EPIC-11 — Frontend Dashboard
- **Assigned agent:** Frontend Engineer
- **Priority:** P1
- **Dependencies:** TASK-054
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub:** Issue [#88](https://github.com/dhruv0641/Dolla/issues/88); draft PR [#89](https://github.com/dhruv0641/Dolla/pull/89) targets `develop`; branch `feature/TASK-055-qa-voice-calendar-and-publishing`.
- **Related source documents:** DASHBOARD_DEMO.html; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want qa, voice, calendar and publishing screens, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver qa, voice, calendar and publishing screens as an independently verifiable capability within frontend dashboard.

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
- [ ] Operational figures use backend data; absent data is shown unavailable, never fabricated.

## Implementation checkpoint — 2026-11-18
- Added a QA workspace for media integrity, caption/timing, safety/evidence and human approval. It reports no QA asset/report and keeps review actions disabled.
- Added a voice workspace that shows local speech engine, approved profile/consent and narration assets as unavailable; generation and preview remain disabled.
- Added a publishing workspace with independent platform authorization states, a month-navigable empty calendar and a per-platform publication ledger. Create/connect controls remain disabled; no posts or schedule records are fabricated.
- The calendar receives its initial month from the server in UTC, uses semantic read-only table markup, and does not assert external schedules are empty.
- `npm run typecheck` and `npm run build` pass in `web/`; project-plan validation reports 15 epics, 76 task specs and no cycles; `git diff --check` is clean.
- Independent review identified an incomplete ARIA grid; it was replaced by a semantic table and UTC initialization was made explicit. Re-review found no remaining blocker.
- Local browser preview confirmed the QA/voice and publishing/calendar workspaces render at a narrow viewport with clear unavailable states. No screenshot artifact was retained.
- No TTS engine, QA media service, platform OAuth or publishing API is configured; no external connection, content submission or public publishing was attempted.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
