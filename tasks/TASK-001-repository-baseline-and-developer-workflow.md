# TASK-001: Repository baseline and developer workflow

- **Parent epic:** EPIC-01 — Project Foundation
- **Assigned agent:** DevOps Engineer
- **Priority:** P0
- **Dependencies:** None
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** MASTER PROMPT; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want repository baseline and developer workflow, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver repository baseline and developer workflow as an independently verifiable capability within project foundation.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`README.md`, `CONTRIBUTING.md`, `.gitignore`, `scripts/validate_project_plan.py`, `.github/workflows/project-validation.yml`, `TASKS.md`, `GOALS.md`, `story.md`, `docs/IMPLEMENTATION_PLAN.md`, and this task specification.

## Acceptance Criteria
- [x] Repository has a documented `main`/`develop` and task-branch workflow; no workflow directs contributors to push to `main`.
- [x] A project-plan validator checks required files, all 15 epics, all 76 task specs, required task sections, valid dependency references, and dependency-cycle absence.
- [x] GitHub Actions runs the validator for relevant pushes and pull requests.
- [x] Git ignore rules exclude secrets, local configuration, and generated media.
- [x] GitHub `main` has active PR-only protection; repository identity and protected-rule evidence are documented.
- [ ] Task branch PR targeting `develop` passes required CI on the latest commit and is merged after review.

## Tests and Verification
- Run `python scripts/validate_project_plan.py` locally and in GitHub Actions.
- Verify branch protection via GitHub API; confirm the PR target and check result from GitHub.
- Review staged diff and repository status for secret/media exclusions.

## GitHub References
- Repository: https://github.com/dhruv0641/Dolla
- Issue: https://github.com/dhruv0641/Dolla/issues/2
- Branch: `feature/TASK-001-repository-baseline-and-developer-workflow`
- Pull request: https://github.com/dhruv0641/Dolla/pull/3
- CI run: initial commit checks passed; latest commit checks pending after tracker updates

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
