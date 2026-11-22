# TASK-047: Visual and audio evaluation

- **Parent epic:** EPIC-10 — Video Quality Assurance
- **Assigned agent:** QA and Security Engineer
- **Priority:** P1
- **Dependencies:** TASK-046
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** READY
- **Related source documents:** ARCHITECTURE; MASTER PROMPT
- **Blockers:** None. TASK-046 is DONE; the Head Man must select and scope this task before implementation begins.

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
- [ ] Capability is implemented behind documented interfaces and configuration.
- [ ] Errors, state transitions and security boundaries are explicit and observable.
- [ ] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
