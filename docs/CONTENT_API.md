# Brand and content API

All routes require a configured bearer-token verifier. A PostgreSQL pool must also be injected into `create_app`; otherwise content routes return `503 database_not_configured`. Admin and operator roles can create; admin, operator and reviewer roles can read. The token subject is the tenant owner identifier and is always used for owner filters.

## Routes

| Method | Path | Behavior |
|---|---|---|
| `POST` | `/api/v1/brands` | Create an owner-scoped brand. Optional timezone defaults to `Asia/Kolkata`; timezone names are validated. |
| `GET` | `/api/v1/brands` | List only brands owned by the authenticated subject. |
| `POST` | `/api/v1/brands/{brand_id}/content` | Create an initial `IDEA` content item only under a brand owned by the authenticated subject. |
| `GET` | `/api/v1/brands/{brand_id}/content` | List content for an owned brand. |

Brand names are limited to 160 characters, niche to 500, audience to 1,000. Content title is limited to 300 characters, idea text to 20,000, topic/audience segment to 300, language to 20, duration to 4–180 seconds and priority to 1–5. Blank required text is rejected. Responses omit owner IDs and database internals.

Invalid requests return FastAPI validation errors (`422`); absent or foreign-owned brands return the same `404 brand_not_found`; database absence or errors return a safe `503`. Repository statements are parameterized, and inserts/selects constrain the owner in SQL. The initial schema has a globally unique brand name, so duplicate names surface as a generic storage error (`503`) until a follow-up migration/API contract introduces a tenant-scoped uniqueness rule.

This implementation has mock-boundary API tests but no live PostgreSQL execution. It does not yet provide updates/deletes, brand-bible policy editing, state transitions, RLS, or production readiness. See `docs/SCHEMA_REVIEW.md` and the future typed state-machine task.
