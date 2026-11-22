# Local platform export variants

`flowx_os.rendering.PlatformExportService` creates local delivery artifacts only. It has no OAuth, channel lookup, upload, publish or network interface. Every result records `publishing_performed: false` and remains subject to human review and later official publishing adapters.

## Versioned product profiles

The immutable allowlist contains `YOUTUBE_SHORTS_V1`, `INSTAGRAM_REELS_V1` and `FACEBOOK_REELS_V1`, matching the three platforms in the database architecture. All v1 profiles produce 1080×1920, 30 FPS, H.264/yuv420p video, AAC audio and selectable `mov_text` captions. They use fixed product bitrate targets: YouTube 8 Mbps/192 kbps and Instagram/Facebook 6 Mbps/128 kbps. These are FLOW product profiles, not a claim of permanent platform limits or upload certification; changes require a new versioned profile and ordinary review.

## Source and execution boundary

The only source is an owner-scoped, content-level `FINAL_VIDEO` MP4 produced by composition version 1. Its valid composition fingerprint, zero timeline start, duration and muxed-subtitle evidence are required. The complete managed object is snapshot-hashed before a fixed, no-shell local FFmpeg command applies the selected allowlisted profile. Callers cannot submit raw dimensions, codecs, filters, bitrates, platform names or command arguments.

Before ingest as `EXPORT_VARIANT`, bounded `ffprobe` must confirm exact dimensions/FPS/square pixels, one H.264 video stream, one AAC audio stream, one `mov_text` subtitle stream and the source duration within 250 ms. Output identity, source identity/hash, platform/profile, profile settings and a deterministic fingerprint are retained in asset metadata and path-free persistence manifests.

No platform account readiness, upload acceptance, remote processing or public availability is implied. Official APIs and reconciliation belong to the publishing epics, and public publishing remains off by default.
