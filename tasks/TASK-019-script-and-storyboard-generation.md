# TASK-019: Script and storyboard generation

- **Parent epic:** EPIC-04 — AI Agent System
- **Assigned agent:** AI Workflow Engineer
- **Priority:** P1
- **Dependencies:** TASK-018
- **Estimated complexity:** 12 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub:** Issue [#46](https://github.com/dhruv0641/Dolla/issues/46); PR [#47](https://github.com/dhruv0641/Dolla/pull/47) merged to `develop` as `10fa7c5`; both CI checks and independent review passed.
- **Related source documents:** ARCHITECTURE; MASTER PROMPT
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want script and storyboard generation, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver script and storyboard generation as an independently verifiable capability within ai agent system.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`src/flowx_os/agents/script_storyboard.py` defines a bounded context, injected async generator protocol, typed workflow results and sanitized errors. It binds strategy/script/scene citations to supplied source snapshots and enforces exact requested scene count/duration, matching titles and ordered narration partitioning. Public exports are in `src/flowx_os/agents/__init__.py`; deterministic fake-provider coverage is in `tests/test_script_storyboard.py`; operator boundary and limitations are in `docs/SCRIPT_STORYBOARD_WORKFLOW.md`. No provider SDK or persistence is added.

## Acceptance Criteria
- [x] Capability is implemented behind a typed, injected provider interface; it makes no implicit provider/network calls.
- [x] Inputs, untrusted provider outputs, evidence provenance, timing and scene/narration coherence are explicitly bounded and validated; errors are payload-safe.
- [x] Deterministic workflow tests and operator documentation record the boundary; no external integration is claimed.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
