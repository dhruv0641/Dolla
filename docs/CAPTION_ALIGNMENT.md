# Caption and subtitle alignment

`flowx_os.audio.captions.CaptionAlignmentService` creates deterministic SRT from an immutable storyboard version and its normalized narration asset. Callers must supply `StoryboardVersionRecord` and `AssetRecord` objects returned by owner-scoped repositories. The service binds content ID, storyboard version, full timeline, narration asset identity, asset kind, content lineage, normalized duration, zero-millisecond start and normalization fingerprint before writing a caption asset.

Caption text comes only from approved `TimelineScene.narration_text`. The service does not transcribe audio, call a model or infer word timestamps. It normalizes whitespace, rejects unsafe controls and overlong unbreakable words, wraps text without changing its word sequence, and checks that the complete cue text exactly preserves the storyboard narration.

Cues never cross scene boundaries. Within each narrated scene, deterministic durations are estimated from non-space character counts with a configured minimum cue duration. Cues cover that narrated scene window; scenes with empty narration intentionally create no cue. If the text density cannot fit, generation fails with `CAPTION_DENSITY_EXCEEDED` instead of emitting unreadable timing. This is recorded as `STORYBOARD_SCENE_ESTIMATE` with `word_level_alignment_verified=false`.

SRT output uses ordered, non-overlapping millisecond timestamps, UTF-8, LF line endings and HTML-escaped display text so storyboard markup cannot become subtitle styling. Cue count and byte size are bounded. The output is fsynced in a private temporary directory and ingested as an immutable `CAPTION_SRT` asset. The caption fingerprint binds request/output IDs, exact audio digest, storyboard version/timeline and timing policy. Repeating the same output UUID and evidence is safe through `AssetIngestService`; rebinding that UUID fails closed.

Run focused verification with:

```powershell
python -m unittest tests.test_captions tests.test_audio_normalization tests.test_audio_synthesis tests.test_audio_repository -v
```

The repository does not claim speech recognition, phoneme/word alignment, caption visual QA, platform subtitle compatibility, PostgreSQL runtime behavior or publication readiness. Those require later measured integration and human review. No network, paid service, Flow credit or account action is used.
