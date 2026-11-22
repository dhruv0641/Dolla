# Scene, narration and subtitle composition

`flowx_os.rendering.MediaCompositionService` creates one local MP4 from an ordered, contiguous scene timeline, one normalized WAV narration asset and one generated SRT asset. Every input is an immutable managed asset backed by an owner-scoped record from the requested content.

## Lineage contract

- Scene numbers begin at one, scene intervals begin at 0 ms and have no gaps or overlaps. Each video asset must be a `RAW_FLOW_CLIP` whose `scene_id` matches its timeline entry.
- Narration must be the content-level `NARRATION` WAV produced by normalization version 1, with `timeline_start_ms = 0` and duration equal to the complete scene timeline.
- Subtitles must be the content-level `CAPTION_SRT` version 1 for the same storyboard version and normalized narration asset, starting at 0 and ending at the timeline duration.
- All input and output UUIDs are distinct. The normalized `inputs_manifest` lists scene assets in playback order, followed by narration and subtitles. The path-free command manifest and SHA-256 fingerprint bind all hashes, timings, roles, versions and output profile.

## Fixed execution

The service snapshots and hashes every complete managed object, with an aggregate input-byte ceiling. A generated filter graph normalizes each scene with the TASK-042 profile, pads a short scene by cloning its final frame, trims it to its declared duration and concatenates scenes in manifest order. Narration is padded/trimmed to the full duration and rebased to 0:00.

SRT is passed as a separate, protocol-restricted FFmpeg input and muxed as an MP4 `mov_text` subtitle stream. It is not interpolated into a filter expression and is not burned into video pixels. This preserves selectable captions; a platform that requires burned-in text must add an explicitly reviewed export policy later.

Before ingest, bounded `ffprobe` must report the exact H.264 dimensions/FPS/square-SAR profile, one AAC audio stream, one `mov_text` subtitle stream and total duration within 250 ms. Any missing, foreign, changed, oversized or invalid input/output fails with a stable redacted code and no asset ingest.

## Limits

The service supports 1–30 scenes and a maximum 180-second timeline. It does not choose editorial transitions, music mixing, subtitle styling, platform variants or semantic crop framing. Byte equality across FFmpeg builds, PostgreSQL render-job persistence and production process isolation remain unverified.
