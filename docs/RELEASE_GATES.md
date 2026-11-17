# Security and release gates

## Automated pull request gate

Pull requests targeting `develop` or `main` run the `validate-project-plan` status check. The check validates the task index and dependency graph, runs the backend test suite, audits the installed Python environment (including runtime and development dependencies) for known vulnerabilities, type-checks and builds the web client, and runs `npm audit` at the configured high severity threshold. CI upgrades its preinstalled `pip` and `setuptools` before dependency installation so the audit sees current installer tooling instead of vulnerable runner defaults. The Python vulnerability audit uses PyPA's pip-audit GitHub Action pinned to the `v1.1.0` commit. Any failed step blocks the required status check; do not merge around a failed check.

The active `develop` ruleset requires this status check and a pull request. The `main` ruleset also requires one approving review, dismisses stale approvals after new commits, and requires the status check. Keep these repository rulesets enabled. The independent Technical Reviewer provides project-level review evidence; `develop` does not currently enforce an approval count.

The backend audit checks resolved package versions from the CI install; Python does not yet have a committed lock file. Audit results therefore apply to the package versions from that run and do not establish reproducible builds or detect malicious packages. The frontend audit is lockfile-based through `npm ci` and `npm audit`.

## Manual release readiness checklist

Before any production deployment, a release owner must verify and record:

- Required CI checks pass on the exact candidate commit, and the pull request was reviewed and merged through the protected branch workflow.
- Supported database migration and rollback/recovery procedures are tested against the candidate schema.
- Database, identity verification and secret-store startup wiring are present and verified; credential references resolve through the approved secret system.
- A recent encrypted backup restores successfully to a disposable database using the documented identity and recovery process. Record restore evidence and key custody without exposing secrets.
- Readiness, protected routes, tenant boundaries, resource limits, TLS/network policy, logs, metrics and alert delivery have been verified in the target environment.
- Operational runbooks, incident contacts, change record and explicit deployment authorization are available.

This checklist is a release procedure, not an automated deployment approval. There is no production deploy or package publishing workflow configured. Current local Compose and application configuration do not wire PostgreSQL, identity, or secret resolution, and no live encrypted restore has been performed. A passing CI check does not certify production readiness.
