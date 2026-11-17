# TASK-020: Prompt, review and analyst agents

- **Parent epic:** EPIC-04 — AI Agent System
- **Assigned agent:** AI Workflow Engineer
- **Priority:** P1
- **Dependencies:** TASK-019
- **Estimated complexity:** 16 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub:** Issue [#49](https://github.com/dhruv0641/Dolla/issues/49); branch `feature/TASK-020-prompt-review-and-analyst-agents` targets `develop`.
- **Related source documents:** ARCHITECTURE; MASTER PROMPT
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want prompt, review and analyst agents, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver prompt, review and analyst agents as an independently verifiable capability within ai agent system.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`src/flowx_os/policies/registry.py` adds strict versioned prompt templates with exact safe-variable allowlists and bounded rendering. `config/prompt_registry.json` defines visual-direction, content-review and performance-analysis prompts. `src/flowx_os/agents/review.py` provides evidence-bound structured content review with a fixed human approval gate; `src/flowx_os/agents/analyst.py` validates observation-linked analysis without claiming metric authenticity or causality. Tests are in `tests/test_policy_registry.py` and `tests/test_review_analyst_agents.py`; trust boundaries are in `docs/REVIEW_ANALYST_AGENTS.md`. Provider calls remain injected interfaces.

## Acceptance Criteria
- [x] Versioned prompt templates use exact allowlists, bounded values and no executable formatting expressions.
- [x] Review and analyst provider responses are strictly validated and linked only to supplied evidence/observation IDs; errors are payload-safe.
- [x] Review output cannot approve content, analyst output requires human interpretation, and external provider behavior is not claimed.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- `python -m unittest discover -s tests`: 149 tests passed.
- `python scripts/validate_project_plan.py`: 15 epics, 76 task specs, 76 dependency nodes, no cycles.
- `python -m compileall -q src tests` and `git diff --check`: passed.
- Independent Technical Reviewer re-reviewed prompt versioning/immutability and evidence gates; no blockers. Live model/provider, analytics, Flow MCP, paid generation, publishing and end-to-end integration are not configured or verified.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
