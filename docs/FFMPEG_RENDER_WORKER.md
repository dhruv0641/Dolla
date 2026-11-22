# Local FFmpeg render worker

`flowx_os.rendering.FfmpegRenderWorker` provides the bounded execution foundation for automated editing. It supports one verified managed video input and emits one managed normalized MP4. TASK-042 adds a fingerprinted codec/FPS/aspect profile; TASK-043 later adds multi-input composition rather than accepting arbitrary FFmpeg arguments here.

## Trust boundary

- The caller supplies an authenticated `RenderRequest`, ordered `StoredAssetFile` values and owner-scoped `AssetRecord` values. Every UUID, content lineage field, managed URI, MIME type, size and SHA-256 must agree.
- The worker derives paths from asset UUIDs below the configured root, rejects symlinks and hard links, snapshots and hashes the complete input, and detects file identity changes while reading.
- FFmpeg runs without a shell or stdin, with a fixed protocol/demuxer allowlist, one thread, bounded runtime and bounded diagnostic output. Callers cannot inject paths, filters, protocols, codecs or flags.
- FFmpeg receives an output file-size ceiling. The temporary MP4 must be a regular single-link file, remain under the byte cap, have an MP4 signature, and pass a bounded local `ffprobe` container/video/duration check before it is passed to the existing owner-scoped asset-ingest boundary.

## Durable manifests and retries

`RenderManifest.inputs_manifest()` returns the exact migration-0010 shape `{ "asset_ids": [...] }`. `command_manifest()` is declarative and path-free; it records the schema, operation, request/version, fixed codec policy and deterministic fingerprint, never a raw command line. The fingerprint covers ordered input identities, hashes, sizes and output policy. Retrying the same request therefore preserves plan identity, while the existing managed store and asset registry reject an output UUID that resolves to different bytes or metadata.

The baseline transform removes metadata and chapters and uses bit-exact flags. This is deterministic for the pinned local FFmpeg build and fixed inputs, but byte equality across different FFmpeg builds or CPU implementations is not claimed. The tool version should be captured by deployment inventory before production certification.

## Failure behavior

Failures expose stable codes such as `INPUT_LINEAGE_MISMATCH`, `INPUT_INTEGRITY_MISMATCH`, `INPUT_SIZE_LIMIT`, `FFMPEG_FAILED`, `OUTPUT_SIZE_LIMIT` and `RENDER_FAILED`; stderr and local paths are never returned. A failed execution never calls asset ingest and must be persisted as a failed job by the later render-job orchestration layer. No network service, Google Flow credit or publishing action is used.
