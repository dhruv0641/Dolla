# Managed media probing

`flowx_os.assets.probing.MediaProbeService` inspects video/audio already placed by `ManagedAssetStore`. It supports MP4, WebM, WAV, MP3 and Ogg. Stills/text are explicitly unsupported. Tools must be installed: local `ffprobe` and `ffmpeg`, or operator-supplied executable paths. No provider call or Flow credit consumption occurs.

`ProbePolicy` defines expected duration and absolute tolerance (seconds), expected display aspect and absolute ratio tolerance, required video/audio streams, dimension limits and codec allowlists. Every audio/video stream is checked. Sample aspect and right-angle rotation affect display dimensions/aspect. Missing, nonfinite, zero or malformed duration/stream metadata fails closed. Unknown stream types are excluded from decoding and are not a subtitle/accessibility verification claim.

The service copies the bounded regular managed file into a private temporary snapshot, checks its SHA-256 and size against `StoredAssetFile`, and probes that same snapshot. Explicit demuxers exclude playlists; only the file protocol is permitted, and MP4 external data references are disabled. Tools run without a shell, with closed stdin, one decode thread, a 256 MiB per-allocation limit, a configurable timeout (default 60 seconds **per tool**) and bounded stdout/stderr (default 1 MB **per pipe**). Processes are killed and reaped on timeout/output overflow. Snapshot files are removed on return/error. These limits do not provide an aggregate RAM, CPU, or disk quota: deployment workers should run with OS/container resource limits and a private storage/temp directory. A hostile actor able to modify filesystem paths concurrently is outside the storage-root trust boundary; hash verification prevents passing changed snapshot bytes as the original asset.

Metadata violations return `MediaReport` with `decode_verified=False` and stable violation codes, before invoking the decoder. Acceptable metadata proceeds through a full FFmpeg audio/video decode with error escalation. A successful process must also report completion, positive decoded output time and at least one video frame when video exists. The final decoded output time is recorded as `decoded_duration_seconds` and must agree with both probed and expected duration within the policy duration tolerance. Contradictory duration evidence returns explicit decode-duration violations and `passed=False`. Tool/parse/integrity failures raise safe `MediaProbeError` codes without returning paths or raw stderr. `passed` is true only when all checks and decode pass. This is technical media evidence, not visual/content QC, review approval, lip-sync scoring, caption verification, or permission to publish.

## Worker integration

Authorize owner/content/scene/job lineage **before** storage/probing. The synchronous service should run with `asyncio.to_thread` in async workers. A typical owner-authorized ingestion path is:

```python
await repository.assert_lineage(
    brand_id=brand_id, content_id=content_id, owner_user_id=owner_id,
    scene_id=scene_id, source_job_id=job_id,
)
stored = await asyncio.to_thread(
    ManagedAssetStore(storage_root).store,
    asset_id=asset_id, source_path=downloaded_path, mime_type="video/mp4",
)
report = await asyncio.to_thread(
    MediaProbeService(storage_root).inspect, stored,
    ProbePolicy(expected_duration_seconds=8, expected_aspect_ratio=9/16),
)
if not report.passed:
    # Record/report the failed QC result; do not advance this asset as ready.
    raise ValueError(report.violations)
record = await ingest_service.ingest(
    asset_id=asset_id, source_path=stored.path, mime_type=stored.mime_type,
    brand_id=brand_id, content_id=content_id, owner_user_id=owner_id,
    kind=AssetKind.RAW_FLOW_CLIP, scene_id=scene_id, source_job_id=job_id,
    media_metadata=report.to_metadata(),
)
```

The same UUID and managed bytes are revalidated on ingestion. `to_metadata()` returns a JSON-compatible `media_probe` object including hash, duration, streams, decode evidence, violations and schema version. The existing ingestion repository persists this object. No automatic worker scheduler, new API endpoint or scene lifecycle transition is wired by this module.

## Evidence and references

`python -m unittest tests.test_media_probing -v` exercises actual local FFmpeg H.264/AAC MP4 and PCM WAV fixture generation/probe/decode, truncated MP4 refusal, policy failures, changed-file/forged-path refusal, playlist refusal, malformed metadata, aspect/rotation handling, empty decode output, timeout and output overflow. Real fixture tests skip explicitly when tools are absent; CI and backend image install FFmpeg. Real local verification does not prove live Flow retrieval, PostgreSQL persistence, or production resource isolation.

Primary tool references: [ffprobe options and structured output](https://ffmpeg.org/ffprobe.html), [FFmpeg protocol whitelist](https://ffmpeg.org/ffmpeg-protocols.html).
