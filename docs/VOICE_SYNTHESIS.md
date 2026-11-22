# Local voice profiles and synthesis

`flowx_os.audio.synthesis` defines the provider-neutral TASK-037 boundary. A `VoiceProfile` is immutable engine, engine-version, built-in voice, locale and PCM output configuration owned by one brand. `AudioRepository` creates profiles idempotently and can irreversibly deactivate them under the brand owner. Database triggers reject configuration mutation and reactivation; use a new profile identity for changed evidence or settings.

Synthesis is allowed only when the profile is active, its license evidence is `VERIFIED`, consent is `NOT_REQUIRED` or `VERIFIED`, and the injected local provider reports the exact engine name and version recorded by the profile. These gates are rechecked while the profile/content claim is locked; deactivation prevents later claims. TASK-037 accepts only `LOCAL_BUILTIN` voices. It does not implement voice cloning, voice enrollment, model download, network TTS or a paid provider. License, consent and adapter configuration fields contain restricted references only, never credentials, URLs with query strings or voice samples. Secret material belongs in OS secret storage and is resolved by a future concrete adapter.

`VoiceSynthesisService` normalizes bounded narration, derives a stable SHA-256 request fingerprint and obtains an owner/content/scene-scoped database claim before invoking a provider. Replaying a completed request returns its existing result without another provider call. A claimed, failed or ambiguous request fails closed and requires reconciliation; callers must not automatically retry it. Narration text is passed to the local provider but is not stored in `tts_synthesis_requests`.

The provider writes to a service-controlled temporary path. The service rejects symlinks, hard links, non-files, oversized output, non-PCM WAV, empty audio, excessive duration, and sample-rate/channel mismatch. Accepted WAV bytes are registered through `AssetIngestService` as an immutable `NARRATION` asset with owner/content/scene lineage and technical metadata. If the asset exists but completion persistence is uncertain, the result is `SYNTHESIS_RECONCILE_REQUIRED`; the request is not marked failed and must not be regenerated automatically.

No concrete TTS adapter or verified engine is selected in this repository, so live narration is not production-ready and no live synthesis is claimed. The unit suite uses an in-process WAV fixture writer only. PostgreSQL migration/runtime behavior also remains unverified locally. Run focused checks with:

```powershell
python -m unittest tests.test_audio_synthesis tests.test_audio_repository -v
```
