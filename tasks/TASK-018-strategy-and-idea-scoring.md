# TASK-018: Strategy and idea scoring

- **Parent epic:** EPIC-04 — AI Agent System
- **Assigned agent:** AI Workflow Engineer
- **Priority:** P1
- **Dependencies:** TASK-017
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub:** Issue [#43](https://github.com/dhruv0641/Dolla/issues/43); PR [#44](https://github.com/dhruv0641/Dolla/pull/44) merged to `develop` as `ef36c14`; GitHub Actions passed; independent review passed.
- **Related source documents:** ARCHITECTURE; MASTER PROMPT
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want strategy and idea scoring, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver strategy and idea scoring as an independently verifiable capability within ai agent system.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`src/flowx_os/agents/strategy.py` provides versioned weights, candidate signals, scored contributions, readiness status, blockers and deterministic ranking. `tests/test_strategy.py` covers score math and readiness policy. `docs/STRATEGY_SCORING.md` documents defaults and configuration tradeoffs. No persistence or model provider is in scope.

## Acceptance Criteria
- [x] Capability is implemented behind documented interfaces and configuration.
- [x] Scoring and readiness rules are explicit and observable, with fixed blockers and profile-controlled thresholds/evidence minimums.
- [x] Acceptance evidence and operator documentation are recorded; no provider-generated ratings are claimed.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
