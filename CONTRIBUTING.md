# Contributing and Git Delivery Workflow

## Branch model

| Branch | Purpose | Rules |
|---|---|---|
| `main` | Protected production history | PR-only; required CI and review; no direct pushes or force pushes. Production merges require the owner's authorization. |
| `develop` | Integration branch | Task and milestone PRs target this branch; require CI and review. |
| `feature/TASK-###-short-name` | New capabilities | Branch from `develop`; one task or cohesive set of dependent tasks per branch. |
| `fix/TASK-###-short-name` | Defect correction | Branch from `develop`; link the affected task/issue and regression evidence. |
| `epic/EPIC-##-short-name` | Large coordinated milestone | Branch from `develop`; use when several task PRs must integrate together. |

## Task delivery

1. Read `AGENTS.md`, `story.md`, `GOALS.md`, `TASKS.md`, and the task specification. Confirm dependencies are complete and the task is part of the active user goal.
2. Fetch and branch from the latest `develop`. Do not start work from `main`.
3. Implement only the scoped task. Keep credentials and generated media out of commits unless explicitly required and safely licensed.
4. Run the task's verification commands, inspect the diff, and update the task spec, `TASKS.md`, `GOALS.md`, `story.md`, and the unified development log with evidence and timestamps.
5. Commit with a meaningful message containing the task ID, e.g. `feat(TASK-001): add project validation workflow`.
6. Push the task branch and open a descriptive PR targeting `develop`. Include task IDs, summary, acceptance criteria, actual test results, screenshots for UI changes, and related issue/PR links.
7. Monitor CI, review changes, fix failures, and keep the PR current. Merge only after required checks/review and authorization applicable to the target branch.
8. Record the PR URL and CI result in `TASKS.md`, `GOALS.md`, and `story.md`. Do not label an external integration production-ready from mocks alone.

## Delivery cadence and safety

During active work, push verified checkpoints after each completed task or significant milestone, aiming for 30–60 minutes between checkpoints when work is continuous. Never push directly to `main`, force-push a shared branch, commit secrets, publish content, or merge into production without authorization. If GitHub access is unavailable, retain local commits, state the exact blocker, and do not claim a push or PR succeeded.

## GitHub repository settings

Configure a ruleset for `main` that blocks deletion and force pushes, requires pull requests, at least one approval, and successful required CI checks. Protect `develop` with PR and CI requirements. Keep `main` as the default/production branch. Ruleset configuration is an external GitHub setting; local files do not prove it is enabled. Record the settings/API evidence in the development log when verified.
