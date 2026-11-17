# TASK-016: Agent schemas and validation

- **Parent epic:** EPIC-04 — AI Agent System
- **Assigned agent:** AI Workflow Engineer
- **Priority:** P1
- **Dependencies:** TASK-011, TASK-013
- **Estimated complexity:** 4 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub:** Issue [#37](https://github.com/dhruv0641/Dolla/issues/37); PR [#38](https://github.com/dhruv0641/Dolla/pull/38) targets `develop`.
- **Related source documents:** ARCHITECTURE; MASTER PROMPT
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want agent schemas and validation, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver agent schemas and validation as an independently verifiable capability within ai agent system.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`src/flowx_os/agents/schemas.py` and the package exports define strict request, role, evidence, research, strategy, script and storyboard contracts. `tests/test_agent_schemas.py` verifies validation boundaries; `docs/AGENT_SCHEMAS.md` documents their trust and network limits. `pyproject.toml` declares Pydantic directly. No migration or provider integration is in scope.

## Acceptance Criteria
- [x] Capability is implemented behind documented interfaces and configuration.
- [x] Errors and security boundaries are explicit: request/output errors omit rejected values; evidence URLs are references only and are never fetched by these schemas.
- [x] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
