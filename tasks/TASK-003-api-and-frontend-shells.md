# TASK-003: API and frontend shells

- **Parent epic:** EPIC-01 — Project Foundation
- **Assigned agent:** Backend Engineer
- **Priority:** P0
- **Dependencies:** TASK-002
- **Estimated complexity:** 16 engineering hours (planning estimate)
- **Status:** IN_PROGRESS
- **Related source documents:** MASTER PROMPT; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want api and frontend shells, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver api and frontend shells as an independently verifiable capability within project foundation.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`pyproject.toml`, `src/flowx_os/api/`, `tests/test_api.py`, `web/`, `.github/workflows/project-validation.yml`, README and project trackers.

## Acceptance Criteria
- [ ] FastAPI application factory exposes service metadata and a process liveness route; it does not imply database, Flow MCP, or publishing readiness.
- [ ] Next.js App Router shell builds and presents all 14 required dashboard areas with accessible navigation.
- [ ] Dashboard displays clear empty/not-connected states and no fabricated operational data.
- [ ] Backend endpoint tests verify response shape and liveness semantics.
- [ ] CI installs Python and Node dependencies, runs planning/config/API checks, TypeScript checks, and a production frontend build.
- [ ] README documents local backend/frontend setup and run commands.

## Tests and Verification
- Run `python -m unittest discover -s tests -v` and `python scripts/validate_project_plan.py`.
- Run `npm ci`, `npm run typecheck`, and `npm run build` in `web/`.
- Confirm all dashboard sections are present and carry no sample metrics; record GitHub Actions results.

## GitHub References
- Repository: https://github.com/dhruv0641/Dolla
- Issue: https://github.com/dhruv0641/Dolla/issues/6
- Branch: `feature/TASK-003-api-and-frontend-shells`
- Pull request: pending
- CI run: pending

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
