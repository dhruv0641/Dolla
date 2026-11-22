# Narration timing and normalization

`flowx_os.audio.normalization.AudioNormalizationService` converts an existing, authorized managed narration asset into a deterministic PCM WAV for later video assembly. The caller must supply the `AssetRecord` returned by an owner-scoped asset repository query together with its `StoredAssetFile`; the service binds asset identity, content, optional scene, kind, URI, digest, MIME type and size before any tool invocation.

`NarrationTiming` requires primary narration to begin at exactly `start_ms = 0`. Its content duration is bounded to 180 seconds. Narration longer than the content timeline fails with `NARRATION_TOO_LONG`; shorter narration is padded with silence to the exact content duration. The service never inserts an implicit opening delay.

The local FFmpeg command runs with closed stdin, no shell, one worker thread, an explicit demuxer/protocol allowlist, bounded execution/output and a private digest-verified snapshot. It removes metadata, selects only the first audio stream, disables video, applies the configured loudness filter, resamples, pads/trims to the timeline and emits 16-bit PCM WAV. The output must be a private regular file with the configured rate/channel count and duration before `AssetIngestService` receives it.

The default target policy is 48 kHz mono, -16 LUFS integrated loudness, -1.5 dBTP true peak and 11 LU loudness range. TASK-038 records these as requested filter targets and explicitly sets `loudness_measurement_verified=false`; one-pass filtering is not a measured loudness-conformance claim. A later QA task must measure the final render.

The normalization fingerprint covers all identities, zero start time, target duration and policy fields. The caller-provided output asset UUID is the idempotency key: immutable asset storage safely reuses identical output and refuses rebinding. A crash before ingest leaves only a temporary file; a storage/database interruption after placement can be retried with the same IDs and policy. No network, model, account, Flow credit or paid service is used.

Run focused verification with:

```powershell
python -m unittest tests.test_audio_normalization tests.test_audio_synthesis tests.test_audio_repository -v
```

The real normalization test uses locally installed FFmpeg/ffprobe and verifies zero-millisecond timing, silence padding, exact duration, PCM format and asset-ingest metadata. Production filesystem, PostgreSQL persistence and final-render loudness remain unverified.
