# TASK-054: Flow control, ledger and jobs

- **Parent epic:** EPIC-11 — Frontend Dashboard
- **Assigned agent:** Frontend Engineer
- **Priority:** P1
- **Dependencies:** TASK-021, TASK-022, TASK-053
- **Estimated complexity:** 4 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub:** Issue [#64](https://github.com/dhruv0641/Dolla/issues/64) closed; PR [#87](https://github.com/dhruv0641/Dolla/pull/87) merged to `develop` as `6476cbd`; required PR and post-merge CI passed.
- **Related source documents:** DASHBOARD_DEMO.html; ARCHITECTURE
- **Blockers:** No task dependency remains: TASK-021, TASK-022 and TASK-053 are complete. TASK-023 account verification and TASK-024 old-job reconciliation remain external Flow integration limits; dashboard controls must present these as unavailable until verified backend evidence exists. See [capability matrix](../docs/MCP_CAPABILITY_MATRIX.md). Issue [#64](https://github.com/dhruv0641/Dolla/issues/64) tracks this task; no alternative video provider or simulated controls are permitted.

## User Story
As a FLOW AI Content OS operator, I want flow control, ledger and jobs, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver flow control, ledger and jobs as an independently verifiable capability within frontend dashboard.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] Capability is implemented behind a dedicated dashboard section; operation controls stay disabled without backend capability.
- [x] Account/server/job/spend states and security boundaries are explicit in the UI.
- [x] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.
- [x] Operational figures are shown unavailable without backend records; no sample values or jobs are fabricated.

## Implementation checkpoint — 2026-11-18
- Added a dedicated Flow control view with disabled generate/retry/cancel actions, explicit server/account/job/spend gates, unavailable credit ledger values, and a job table with no placeholder records.
- Dashboard documentation: [`docs/FLOW_CONTROL_DASHBOARD.md`](../docs/FLOW_CONTROL_DASHBOARD.md).
- `npm run typecheck` and `npm run build` pass under Next.js 16.4.6. Independent reviewer found no blocking issue; copy now avoids stale job-state claims and the disabled action group is labeled for assistive technology.
- PR #87 and post-merge `validate-project-plan` checks passed; issue #64 closed. Typecheck/build passed and independent review found no blocker. No live Flow operation was invoked; the dashboard remains unavailable until verified backend evidence exists.
- No Flow API, account status, balance, or external job row is fabricated or connected. TASK-023 direct account verification and TASK-024 old-job reconciliation remain separate integration gates.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
