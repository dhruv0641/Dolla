# TASK-023: Auth and account health

- **Parent epic:** EPIC-05 — Google Flow MCP Integration
- **Assigned agent:** Flow MCP Integration Engineer
- **Priority:** P0
- **Dependencies:** TASK-022
- **Estimated complexity:** 12 engineering hours (planning estimate)
- **Status:** BACKLOG
- **Related source documents:** FLOW_MCP_ADAPTER_CONTRACT.json; ARCHITECTURE
- **External prerequisite:** Verify the Google account shown in the authorized Flow browser matches the intended account `dobariyadhruvv@gmail.com`. The current connector status reports `logged_in: true` but does not expose the email; do not treat that as account verification.
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want auth and account health, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver auth and account health as an independently verifiable capability within google flow mcp integration.

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
- [ ] Unsupported or unverified server capabilities fail closed.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
