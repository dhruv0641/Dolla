# TASK-052: Live executive command center

- **Parent epic:** EPIC-11 — Frontend Dashboard
- **Assigned agent:** Frontend Engineer
- **Priority:** P1
- **Dependencies:** TASK-051
- **Estimated complexity:** 12 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub:** Issue [#58](https://github.com/dhruv0641/Dolla/issues/58); branch `feature/TASK-052-live-executive-command-center` targets `develop`.
- **Related source documents:** DASHBOARD_DEMO.html; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want live executive command center, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver live executive command center as an independently verifiable capability within frontend dashboard.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`web/src/app/api/dashboard-status/route.ts` validates and relays the existing public backend health/readiness contracts; `web/src/components/dashboard-shell.tsx` renders refreshed service status while preserving unavailable states for metrics without a backend summary API. Configure the server-side `FLOWX_API_BASE_URL`; no bearer token or external account access is involved.

## Acceptance Criteria
- [ ] Capability is implemented behind documented interfaces and configuration.
- [ ] Errors, state transitions and security boundaries are explicit and observable.
- [ ] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.
- [ ] Operational figures use backend data; absent data is shown unavailable, never fabricated.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.

## Tests and Verification
- `cd web; npm run typecheck` — passed.
- `cd web; npm run build` — passed; `/api/dashboard-status` is dynamically served.
- `git diff --check` — passed.
- Manual HTTP check with `FLOWX_API_BASE_URL` unset returned HTTP 503 `{ "state": "unavailable", "reason": "api_not_configured" }`.
- Independent Technical Reviewer: passed with no blocker. Reviewer findings on independent readiness failure handling, overlapping refreshes, and HTTP/body consistency were addressed and re-reviewed.
- No visual browser review or successful upstream integration check completed; no authenticated content, Flow MCP, publishing or analytics data is claimed.
