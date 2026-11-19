# Asset storage, hashes and lineage

## Managed local files

`ManagedAssetStore` uses the configured `FLOWX_STORAGE_ROOT` and stores objects below `assets/<asset-uuid>/payload`. It accepts a fixed allowlist of caller-declared MIME types, checks the leading bytes against a limited set of media signatures, enforces a byte limit, computes SHA-256 while streaming, and creates a same-directory hard link so the final object is never partially visible or overwritten. These checks verify transport integrity and a basic type signal; they are not full format parsers. The returned URI is an internal stable reference (`managed://assets/<uuid>/payload`); absolute paths are not returned by the API. Reusing an asset UUID with identical bytes is safe and idempotent; different bytes with that ID fail closed.

The storage component does not scan for malware, transcode, probe codecs, moderate media, or serve the file over HTTP. Configure the storage root on a persistent volume with OS permissions restricted to the FlowX service identity. Local filesystem behavior and production ACLs need deployment-specific verification.

## Registration and lineage

`AssetIngestService` is the worker/service boundary: it validates caller metadata and JSON size, checks owner/content/scene/job lineage before placing bytes, stores the source file, derives the SHA-256 and byte size, and records the normalized declared MIME after its limited signature check. It then calls `AssetRepository.register`, which rechecks lineage transactionally before insertion. Repeating the same asset ID and metadata returns the prior record; reusing an ID for different metadata conflicts. If database registration is unavailable after file placement, retry with the same UUID and same bytes. Abandoned unregistered objects can remain on disk; no automatic garbage collector is enabled.

Migration `0008_asset_lineage_integrity.sql` adds composite foreign keys and checks so a scene must belong to the recorded content, and a source job must belong to that scene. It also validates the stored SHA-256 hex format. These DB checks protect writes from other application code paths as well.

`GET /api/v1/brands/{brand_id}/content/{content_id}/assets` returns owner-scoped metadata, optionally filtered by `scene_id`. The route returns the internal URI and integrity metadata, never the absolute path or file bytes. It requires admin, operator or reviewer role. In this shell no database pool or identity provider is wired, so the route correctly returns unavailable until those dependencies are configured.

## Verification boundary

Unit and fake-pool tests cover file integrity, UUID idempotency, lineage validation, owner scoping, metadata listing and sanitized storage failures. PostgreSQL migration execution, concurrent writes, persistent-volume recovery, backup/restore of actual media, antivirus scanning, and live Flow retrieval remain unverified. This capability does not call Flow, generate media, upload assets to a public platform, or spend credits.
