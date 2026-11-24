# Local container profile

## Start and stop

The Compose `local` profile runs PostgreSQL, ordered migrations, the API, a bounded local worker and the Next.js dashboard. Copy `.env.example` to `.env` if you want to change loopback ports, then run:

```sh
docker compose --profile local config --quiet
docker compose --profile local up --build --wait
```

Open <http://127.0.0.1:3000>. Stop with `docker compose --profile local down`. The API is also bound to `127.0.0.1:8000`. Change `FLOWX_WEB_HOST` or `FLOWX_API_HOST` only when you intentionally want to expose the service beyond loopback.

Application containers run as non-root users, drop Linux capabilities and set `no-new-privileges`; the narrow storage initializer receives only the ownership capabilities required to prepare the named volume. PostgreSQL is not published to the host. API and dashboard stay on internal networks; a fixed, secretless TCP gateway attached to a narrow edge network publishes only their two loopback ports. `/healthz` reports process liveness while `/readyz` requires live database, managed-storage and FFmpeg checks.

## Scope and environment limits

This is a local development profile. `secret-init` creates high-entropy administrator, runtime and token material in separate Docker volumes; each service mounts only the secret classes it needs. Services receive validated `secretref://file/run/secrets/...` references and never receive raw values through Compose environment variables. `migrate` records SHA-256 checksums, serializes execution with an advisory lock, applies all SQL migrations in filename order and safely accepts an unchanged replay. The local worker processes only `local.smoke` outbox events.

Run the local-only lifecycle verification after the stack is healthy:

```sh
docker compose --profile local --profile verification run --rm --build smoke
```

The smoke test verifies bearer authentication, persistent brand/content creation, an allowed workflow transition, owner isolation, idempotent outbox enqueue and worker completion. It uses unique local identities and performs no provider call.

Do not expose this profile to a public network or treat it as a production deployment. YouTube, Instagram and Facebook publishing, official responses, reconciliation, analytics/comment ingestion, Google Flow and all paid operations are explicitly disabled. A production profile still requires an approved external secret store, TLS/ingress policy, deployment-specific resource and alert configuration, production backup/restore exercises and separately authorized provider connections. The Next.js status route talks to the API over the internal Compose network using `FLOWX_API_BASE_URL=http://api:8000`; it does not forward credentials.

## Build verification

Use `docker compose --profile local config --quiet` to validate Compose interpolation without starting containers. Inspect state with `docker compose --profile local ps`; a successful start shows database, API, worker and dashboard healthy and the initializer/migration jobs exited successfully. An unchanged migration replay can be checked with `docker compose --profile local run --rm migrate`.

The current Dockerfiles use major/minor base-image tags and Python dependency ranges rather than digest-pinned images and a generated lockfile. Pinning and supply-chain scanning are production hardening follow-ups.
