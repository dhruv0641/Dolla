# Local container profile

## Start and stop

The Compose `local` profile runs the API and Next.js dashboard shell. Copy `.env.example` to `.env` if you want to change loopback ports, then run:

```sh
docker compose --profile local config --quiet
docker compose --profile local up --build
```

Open <http://127.0.0.1:3000>. Stop with `docker compose --profile local down`. The API is also bound to `127.0.0.1:8000`. Change `FLOWX_WEB_HOST` or `FLOWX_API_HOST` only when you intentionally want to expose the service beyond loopback.

Both images run as non-root users, drop Linux capabilities and set `no-new-privileges`. Container health checks use process liveness; the application readiness route remains HTTP 503 when no dependencies are wired. The dashboard reports that dependency state rather than claiming the database or provider integrations are ready.

## Scope and environment limits

This is a local application-shell profile. It does not start PostgreSQL because the API factory does not create a database pool or read the secret references yet. It does not issue/verify user tokens because identity startup wiring is also absent. Protected content and admin metrics routes therefore return `authentication_not_configured`; no persistent data, credentials, generation, credits, publishing, or analytics are connected. The existing `FLOWX_*_CREDENTIALS_REF` sample values are references only and are not consumed by these containers.

Do not expose this profile to a public network or treat it as a production deployment. A production profile must wait for database and identity wiring, migrations, secret-store integration, tenant isolation, database readiness checks, persistence and backup procedures, TLS/network policy, and deployment-specific resource/alert configuration. The Next.js status route talks to the API over the Compose network using `FLOWX_API_BASE_URL=http://api:8000`; it does not forward credentials.

## Build verification

Use `docker compose --profile local config --quiet` to validate Compose interpolation without starting containers. Image build/start verification requires a running Docker Engine; record successful startup and health checks before making deployment-readiness claims.

The current Dockerfiles use major/minor base-image tags and Python dependency ranges rather than digest-pinned images and a generated lockfile. Pinning and supply-chain scanning are production hardening follow-ups.
