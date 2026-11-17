# TASK-004: Prompt and policy registry

- **Parent epic:** EPIC-01 — Project Foundation
- **Assigned agent:** AI Workflow Engineer
- **Priority:** P0
- **Dependencies:** TASK-003
- **Estimated complexity:** 4 engineering hours (planning estimate)
- **Status:** IN_PROGRESS
- **Related source documents:** MASTER PROMPT; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want prompt and policy registry, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver prompt and policy registry as an independently verifiable capability within project foundation.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`config/prompt_registry.json`, `src/flowx_os/policies/`, `tests/test_policy_registry.py`, `docs/PROMPT_POLICY_REGISTRY.md`, README and project trackers.

## Acceptance Criteria
- [ ] Versioned JSON registry provides typed lookup for named prompt versions.
- [ ] Invalid schema, duplicate IDs, invalid retry caps, and inconsistent approval policy are rejected without exposing file contents.
- [ ] Default policy caps scene regenerations at two, requires human approval, and disables autonomous publishing.
- [ ] Operator docs define versioning, safe limits, and explicitly state no provider invocation occurs.
- [ ] Unit tests cover valid loading and malformed/unsafe registry cases; CI passes.

## Tests and Verification
- Run `python -m unittest discover -s tests -v` and `python scripts/validate_project_plan.py`.
- Record PR and GitHub Actions evidence in this specification and `docs/IMPLEMENTATION_PLAN.md`.

## GitHub References
- Repository: https://github.com/dhruv0641/Dolla
- Issue: https://github.com/dhruv0641/Dolla/issues/8
- Branch: `feature/TASK-004-prompt-and-policy-registry`
- Pull request: pending
- CI run: pending

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
