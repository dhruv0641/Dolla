# TASK-001: Repository baseline and developer workflow

- **Parent epic:** EPIC-01 — Project Foundation
- **Assigned agent:** DevOps Engineer
- **Priority:** P0
- **Dependencies:** None
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** IN_PROGRESS
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
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [ ] Repository has a documented `main`/`develop` and task-branch workflow; no workflow directs contributors to push to `main`.
- [ ] A project-plan validator checks required files, all 15 epics, all 76 task specs, required task sections, valid dependency references, and dependency-cycle absence.
- [ ] GitHub Actions runs the validator for relevant pushes and pull requests.
- [ ] Git ignore rules exclude secrets, local configuration, and generated media.
- [ ] GitHub `main` has active PR-only protection; repository identity and protected-rule evidence are documented.
- [ ] A task branch PR targeting `develop` passes required CI and is reviewed before TASK-001 is marked DONE.

## Tests and Verification
- Run `python scripts/validate_project_plan.py` locally and in GitHub Actions.
- Verify branch protection via GitHub API; confirm the PR target and check result from GitHub.
- Review staged diff and repository status for secret/media exclusions.

## GitHub References
- Repository: https://github.com/dhruv0641/Dolla
- Issue: https://github.com/dhruv0641/Dolla/issues/2
- Branch: `feature/TASK-001-repository-baseline-and-developer-workflow`
- Pull request: pending
- CI run: pending

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
