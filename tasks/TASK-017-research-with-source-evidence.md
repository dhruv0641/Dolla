# TASK-017: Research with source evidence

- **Parent epic:** EPIC-04 — AI Agent System
- **Assigned agent:** AI Workflow Engineer
- **Priority:** P1
- **Dependencies:** TASK-016
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub:** Issue [#40](https://github.com/dhruv0641/Dolla/issues/40); PR [#41](https://github.com/dhruv0641/Dolla/pull/41) targets `develop`.
- **Related source documents:** ARCHITECTURE; MASTER PROMPT
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want research with source evidence, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver research with source evidence as an independently verifiable capability within ai agent system.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`src/flowx_os/agents/research.py` defines the injected provider/summarizer contracts, source snapshot bounds and citation-to-source verifier. `tests/test_research.py` covers valid and invalid evidence paths. `docs/RESEARCH_WITH_EVIDENCE.md` describes the trust boundary and provider network requirements. No migration or live provider is in scope.

## Acceptance Criteria
- [x] Capability is implemented behind documented injected interfaces; source fetcher and summarizer providers are not fabricated.
- [x] Errors and security boundaries are explicit: safe stable failure codes, bounded snapshots, citation-source binding, and quote presence checks.
- [x] Acceptance evidence and operator documentation are recorded; source and model provider behavior are not claimed without live verification.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
