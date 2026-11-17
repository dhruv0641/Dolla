# TASK-056: Agent, analytics, community and settings screens

- **Parent epic:** EPIC-11 — Frontend Dashboard
- **Assigned agent:** Frontend Engineer
- **Priority:** P1
- **Dependencies:** TASK-055
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** BACKLOG
- **Related source documents:** DASHBOARD_DEMO.html; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want agent, analytics, community and settings screens, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver agent, analytics, community and settings screens as an independently verifiable capability within frontend dashboard.

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

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
