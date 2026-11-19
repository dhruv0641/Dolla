# Flow media retrieval and metadata

`FlowMediaService` is the app-side boundary for reading a Flow project grid and retrieving an item whose UUID was exposed by that grid. It uses only the manifest-gated `PROJECT_OPEN` and `MEDIA_DOWNLOAD` adapter operations; no generation capability is called.

## Metadata and retrieval

`list_project()` accepts HTTPS project URLs on `flow.google.com` or `labs.google` with a project identifier in the path. It returns the project ID and only grid entries with unique, parseable UUIDs, supported `image`/`video` kinds, and bounded titles. Missing UUIDs are omitted. This matters because Flow project listings do not guarantee UUID exposure for video tiles.

`retrieve()` requires a discovered `FlowMediaItem`, creates an isolated temporary output directory under the configured media root, and passes the UUID and directory to the adapter. It accepts only a regular file directly inside that directory, checks declared MIME type against image/video kind and a recognized file signature, enforces a configurable byte limit, and computes SHA-256. It then atomically moves the file into the media root with an ID/hash-derived name. Repeated retrieval of identical bytes is idempotent; conflicting or unsafe paths fail closed. MCP responses and returned paths are untrusted.

Supported signatures currently include PNG, JPEG, WebP, MP4 and WebM. This service does not perform antivirus scanning, video probing, codec validation, image moderation, asset-table persistence, lineage writes or retention. Those remain separate acceptance areas, including TASK-032 and TASK-034. A MIME/signature check is not a full media safety or quality review.

## Live operation limits

The app's Flow transport is not configured, so this service has only been verified with adapter fakes. No live Flow item was downloaded and no production integration is claimed. The runtime `flow_media_download` capability accepts a media UUID and output directory. Video generation results may already include downloaded file paths; the project grid may not expose video UUIDs. Never infer a missing result or retry an ambiguous paid generation to obtain media.
