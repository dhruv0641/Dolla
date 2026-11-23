# FLOW AI Content OS

An auditable, self-hosted content production system for YouTube, Instagram and Facebook. Google Flow through a verified, user-authorized MCP server is the only generative video engine.

## Project status

Initialization is complete. See [the project story](story.md), [task backlog](TASKS.md), [implementation roadmap and development log](docs/IMPLEMENTATION_PLAN.md), and [Flow MCP capability matrix](docs/MCP_CAPABILITY_MATRIX.md). All feature work is tracked by task ID; nothing is considered complete without acceptance evidence and review.

## Development setup

- Python 3.11+; install backend dependencies with `python -m pip install -e ".[dev]"`.
- Run the API locally with `uvicorn flowx_os.api.main:app --reload --app-dir src`.
- API liveness and readiness semantics are documented in [HEALTH_READINESS.md](docs/HEALTH_READINESS.md).
- Prompt and policy defaults are versioned in `config/prompt_registry.json`; see [registry documentation](docs/PROMPT_POLICY_REGISTRY.md).
- Platform metric semantics, missing-value rules and the disabled-by-default collection boundary are documented in [PLATFORM_METRIC_DEFINITIONS.md](docs/PLATFORM_METRIC_DEFINITIONS.md).
- The reviewed PostgreSQL baseline and open design findings are in [SCHEMA_REVIEW.md](docs/SCHEMA_REVIEW.md) and `migrations/`.
- Async transaction boundaries are documented in [DATABASE_TRANSACTIONS.md](docs/DATABASE_TRANSACTIONS.md).
- Workflow audit-event persistence is documented in [WORKFLOW_EVENTS.md](docs/WORKFLOW_EVENTS.md).
- Outbox leasing invariants and remaining worker lifecycle limits are documented in [WORKER_OUTBOX.md](docs/WORKER_OUTBOX.md).
- PostgreSQL backup, restore, and dry-run retention behavior is documented in [BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md).
- API bearer-token verification and role guards are documented in [AUTHENTICATION.md](docs/AUTHENTICATION.md).
- Local configuration: copy `.env.example` to `.env`; configuration accepts secret references only.
- Run tests: `python -m unittest discover -s tests -v`
- Start the Next.js dashboard from `web/` with `npm ci && npm run dev`.
- Start the loopback-only Docker application shell with `docker compose --profile local up --build`; see [container scope and limitations](docs/CONTAINERS.md). PostgreSQL/authentication startup wiring is not yet available, so this is not a production deployment.
- Validate planning structure with `python scripts/validate_project_plan.py`.
- Git and Git Credential Manager for GitHub operations
- Feature runtime dependencies will be recorded with their implementation tasks.

## Git workflow

- `main` is production and must be protected by a GitHub ruleset; never push to it directly.
- `develop` is the integration branch. Open pull requests into `develop` for task or milestone changes.
- Use `feature/TASK-###-short-name`, `fix/TASK-###-short-name`, or `epic/EPIC-##-short-name` branches.
- Keep commits focused and descriptive. Include task IDs in branch names, commit messages and pull request descriptions.
- Run local validation and required CI before requesting review. Never force-push shared branches or commit credentials.
- GitHub remote: <https://github.com/dhruv0641/Dolla>

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete workflow.
