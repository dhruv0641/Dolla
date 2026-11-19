# Brand and content API

All routes require a configured bearer-token verifier. A PostgreSQL pool must also be injected into `create_app`; otherwise content routes return `503 database_not_configured`. Admin and operator roles can create; admin, operator and reviewer roles can read. The token subject is the tenant owner identifier and is always used for owner filters.

## Routes

| Method | Path | Behavior |
|---|---|---|
| `POST` | `/api/v1/brands` | Create an owner-scoped brand. Optional timezone defaults to `Asia/Kolkata`; timezone names are validated. |
| `GET` | `/api/v1/brands` | List only brands owned by the authenticated subject. |
| `POST` | `/api/v1/brands/{brand_id}/content` | Create an initial `IDEA` content item only under a brand owned by the authenticated subject. |
| `GET` | `/api/v1/brands/{brand_id}/content` | List content for an owned brand. |
| `POST` | `/api/v1/brands/{brand_id}/content/{content_id}/transition` | Validate and persist one allowed content lifecycle transition. |
| `PUT` | `/api/v1/brands/{brand_id}/content/{content_id}/storyboard` | Append a storyboard timeline version using an `expected_version` optimistic concurrency token. |
| `GET` | `/api/v1/brands/{brand_id}/content/{content_id}/storyboard` | Read the current immutable storyboard snapshot. |
| `GET` | `/api/v1/brands/{brand_id}/content/{content_id}/storyboard/versions` | Read version history for an owned content item. |
| `GET` | `/api/v1/brands/{brand_id}/content/{content_id}/assets` | List owner-scoped asset metadata, optionally filtered by `scene_id`; never returns local file bytes or absolute paths. |

Brand names are limited to 160 characters, niche to 500, audience to 1,000. Content title is limited to 300 characters, idea text to 20,000, topic/audience segment to 300, language to 20, duration to 4–180 seconds and priority to 1–5. Blank required text is rejected. Responses omit owner IDs and database internals.

Storyboard timeline scenes must be sequential, contiguous, and start at zero; the final end time must equal the content target duration. Each write inserts a snapshot and scene projections in one owner-scoped transaction, increments `storyboard_version`, and transitions eligible content from `SCRIPT_READY` or `NEEDS_REVIEW` to `STORYBOARD_READY`. Revisions of already `STORYBOARD_READY` content keep that state. The caller must supply the version it read; stale writes return `409 storyboard_version_conflict` with the current version. Prior snapshots and scene rows are retained for lineage.

Invalid requests return FastAPI validation errors (`422`); invalid transitions and stale storyboard versions return `409`; absent or foreign-owned content returns the same `404 content_not_found`; a content item without a storyboard returns `404 storyboard_not_found`; database absence or errors return a safe `503`. The generic transition API cannot set scheduling or publication outcomes. Repository statements are parameterized, and storyboard reads/writes constrain the owner in SQL. The initial schema has a globally unique brand name, so duplicate names surface as a generic storage error (`503`) until a follow-up migration/API contract introduces a tenant-scoped uniqueness rule.

Asset registration remains a backend/service operation through `AssetIngestService`, not an endpoint that accepts client-supplied filesystem paths or hash claims. Its read route exposes only verified, owner-scoped metadata. See `docs/ASSET_STORAGE_AND_LINEAGE.md` for managed-root, integrity, idempotency and database-lineage contracts.

The storyboard repository and route contracts have deterministic fake-pool tests; PostgreSQL transaction/concurrency behavior remains unverified. The API does not yet provide general content updates/deletes, brand-bible policy editing, RLS, or production readiness. Transition edges are defined in `docs/CONTENT_STATE_MACHINE.md`.
