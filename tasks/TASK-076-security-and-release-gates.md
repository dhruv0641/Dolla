# TASK-076: Security and release gates

- **Parent epic:** EPIC-15 — Security Observability and Deployment
- **Assigned agent:** DevOps Engineer
- **Priority:** P2
- **Dependencies:** TASK-075
- **Estimated complexity:** 4 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub:** Issue [#78](https://github.com/dhruv0641/Dolla/issues/78); branch `feature/TASK-076-security-release-gates` targets `develop`.
- **Related source documents:** ARCHITECTURE; SCHEMA.sql
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want security and release gates, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver security and release gates as an independently verifiable capability within security observability and deployment.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`.github/workflows/project-validation.yml` adds a Python package vulnerability audit to the required CI status check. `docs/RELEASE_GATES.md` documents automated checks, repository rulesets, manual release readiness and current limitations.

## Acceptance Criteria
- [x] Known-vulnerability audit runs against installed runtime and development Python dependencies as part of the existing required PR status check; audit failures block that check.
- [x] Automated checks and repository branch ruleset evidence are documented, including the limits of dependency scanning and absent deployment automation.
- [x] Operator release checklist records manual environment-specific prerequisites and verification evidence without claiming integrations that are not live.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- `python -m pip_audit` in an isolated environment with `.[dev]` and `pip-audit==2.10.1` installed — passed after upgrading the environment's `pip` and `setuptools`; no known vulnerabilities found in the resolved Python environment.
- `python -m unittest discover -s tests` — 157 tests passed.
- `python -m compileall -q src tests` — passed.
- `python scripts/validate_project_plan.py` — 15 epics and 76 task specs/dependency nodes validated; no cycles.
- Workflow YAML parsed successfully; `npm audit --audit-level=high --prefix web` found 0 vulnerabilities; `npm run typecheck --prefix web` and `npm run build --prefix web` passed.
- Independent Technical Reviewer — no blocking findings; confirmed the pinned action runs in the required check and includes development dependencies.
- This release gate does not certify production readiness, malicious-package safety, or reproducible backend dependency resolution; Python has no committed lock file.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
