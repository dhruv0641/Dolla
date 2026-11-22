# Audio preview and management

TASK-040 exposes owner-scoped audio inventory and preview routes under a specific brand/content lineage:

- `GET /api/v1/brands/{brand_id}/content/{content_id}/audio-assets`
- `GET /api/v1/brands/{brand_id}/content/{content_id}/audio-assets/{asset_id}/preview`
- `POST /api/v1/brands/{brand_id}/content/{content_id}/audio-assets/{asset_id}/retire`

Inventory requires admin, operator or reviewer role and uses the existing owner-scoped active-asset repository. Responses include typed audio identity, kind, MIME, size, safe timing metadata and creation time. They do not expose managed URIs, hashes or filesystem paths. Retired assets are absent because normal repository reads require `retention_state = ACTIVE`.

Preview additionally requires an injected local storage root. `AssetCatalogRepository.get_active_audio` binds asset, brand, content and authenticated owner while requiring active audio MIME. `AudioPreviewService` derives the managed path from the UUID rather than accepting a path, rejects symlinks/hardlinks/non-files, hashes the complete object while holding one file descriptor, and compares its size/digest to database evidence before returning bytes. Integrity or path failures produce a generic unavailable response without a path or database detail.

Only one RFC-style `bytes=` range is accepted. A preview response is limited to 8 MB by default; a larger asset requires a range, and an oversized, multiple, malformed or unsatisfiable range returns `416`. Successful partial responses include `Accept-Ranges`, `Content-Range`, a digest-derived ETag, `nosniff`, exact content length and `Cache-Control: private, no-store`. The selected bytes are buffered only after the complete file passes integrity verification.

Retirement requires admin or operator role, an aware cutoff timestamp in the past and a bounded reason. The route first binds the active audio asset to the requested owner/brand/content, then uses the existing transactional tombstone operation. Only old assets belonging to archived content with no retained scene, QA, review, render or publication references can be hidden. The operation records actor, reason and time and is idempotent; it does not delete bytes. Physical purge remains the separate two-phase, recoverable operator workflow.

The application shell fails closed with `database_not_configured` or `audio_preview_not_configured` until dependencies are explicitly injected. PostgreSQL concurrency, production volume ACLs, large-file performance and browser playback behavior remain unverified. No external provider, paid service, Flow action or publishing is involved.

Run focused verification with:

```powershell
python -m unittest tests.test_audio_preview tests.test_asset_catalog -v
```
