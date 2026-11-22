# Video codec, frame-rate and aspect normalization

TASK-042 extends the bounded `FfmpegRenderWorker` with a declarative `RenderPolicy`. The default production profile is 1080×1920 (9:16), 30 FPS, H.264 video, optional AAC audio, yuv420p pixels and square sample aspect. Operators may choose another bounded even width/height and integer FPS from 1–60; total output pixels may not exceed 8,294,400.

## Aspect behavior

- `COVER` scales until the target canvas is filled, then center-crops. It preserves geometry without stretching but may remove edge content.
- `CONTAIN` scales until the complete source fits, then centers it on black padding. It preserves all source content but may add bars.
- Both modes reset sample aspect to 1:1, set a constant frame-rate filter and rebase video timestamps to zero. FFmpeg's local autorotation is applied before filtering, and source rotation metadata is removed from the output.

Width, height, FPS and fit mode are recorded in both the path-free command manifest and the final asset metadata. They are part of the plan fingerprint, so changing any profile field creates a different deterministic plan. Raw filters and arbitrary codec names remain unavailable to callers.

## Verification and limits

Before ingest, bounded `ffprobe` evidence must report exactly one H.264 video stream with the requested dimensions, frame rate and square sample aspect; every emitted audio stream must be AAC. The complete managed input is still snapshot-hashed, FFmpeg and ffprobe remain protocol/container restricted, and output size/runtime/diagnostics remain capped.

Normalization cannot determine whether a crop removes semantically important content. Selection of `COVER` versus `CONTAIN` is an editorial policy decision. Full-frame decode/integrity scoring belongs to TASK-046; multi-scene/audio/subtitle composition belongs to TASK-043. Cross-version FFmpeg byte equality and production workload isolation are not claimed.
