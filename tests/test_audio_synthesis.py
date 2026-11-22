import asyncio
from pathlib import Path
import tempfile
import unittest
from uuid import UUID
import wave

from pydantic import ValidationError

from flowx_os.audio.synthesis import (
    SynthesisClaim,
    SynthesisPolicy,
    SynthesisRequest,
    TtsSynthesisError,
    VoiceConsentStatus,
    VoiceLicenseStatus,
    VoiceProfile,
    VoiceSynthesisService,
    WavEvidence,
    synthesis_fingerprint,
)


PROFILE_ID = UUID("bc6077f2-bac0-4503-ac32-ec8149e02332")
BRAND_ID = UUID("94c52e8d-52d7-42f2-9499-a2e8a59206e4")
CONTENT_ID = UUID("24a3b953-3e5d-4e9d-906b-89e9f035972f")
SCENE_ID = UUID("5950c94b-648d-4658-aa3f-d7189f99d73b")
REQUEST_ID = UUID("2a8e06a2-e2a6-447a-a788-8f32123bf65f")
ASSET_ID = UUID("ece550bb-ff97-4169-9489-adada2579243")


def profile(**updates):
    values = {
        "profile_id": PROFILE_ID, "brand_id": BRAND_ID, "name": "Narrator",
        "engine_name": "local-test", "engine_version": "1.0", "voice_key": "en-IN-A",
        "language": "en-IN", "sample_rate_hz": 16_000, "channels": 1,
        "license_status": VoiceLicenseStatus.VERIFIED,
        "license_reference": "docs/licenses/local-test.md",
        "consent_status": VoiceConsentStatus.NOT_REQUIRED,
        "config": {"model_ref": "models/local-test-v1"},
    }
    values.update(updates)
    return VoiceProfile.model_validate(values)


def request(**updates):
    values = {
        "request_id": REQUEST_ID, "asset_id": ASSET_ID, "profile_id": PROFILE_ID,
        "brand_id": BRAND_ID, "content_id": CONTENT_ID, "scene_id": SCENE_ID,
        "owner_user_id": "owner-1", "text": "  Hello,   local voice.  ",
    }
    values.update(updates)
    return SynthesisRequest.model_validate(values)


class FakeStore:
    def __init__(self, selected_profile=None):
        self.profile = selected_profile or profile()
        self.result = None
        self.failed = []
        self.claims = []
        self.complete_error = None

    async def get_profile(self, **kwargs):
        return self.profile

    async def claim(self, **kwargs):
        self.claims.append(kwargs)
        if self.result is not None:
            return SynthesisClaim(False, self.result)
        return SynthesisClaim(True)

    async def complete(self, *, result):
        if self.complete_error:
            raise self.complete_error
        self.result = result

    async def fail(self, *, request_id, error_code):
        self.failed.append((request_id, error_code))


class WavProvider:
    def __init__(self, *, rate=16_000, channels=1, invalid=False, delay=0):
        self.engine_name = "local-test"
        self.engine_version = "1.0"
        self.rate = rate
        self.channels = channels
        self.invalid = invalid
        self.delay = delay
        self.calls = 0

    async def synthesize(self, *, profile, text, output_path):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.invalid:
            output_path.write_bytes(b"not a wav")
            return
        with wave.open(str(output_path), "wb") as output:
            output.setnchannels(self.channels)
            output.setsampwidth(2)
            output.setframerate(self.rate)
            output.writeframes(b"\0\0" * self.channels * (self.rate // 10))


class FakeAssetIngest:
    def __init__(self):
        self.calls = []

    async def ingest(self, **kwargs):
        self.calls.append(kwargs)
        self.payload = Path(kwargs["source_path"]).read_bytes()


class VoiceSynthesisTests(unittest.IsolatedAsyncioTestCase):
    def test_contracts_normalize_text_and_reject_missing_evidence_or_credentials(self):
        self.assertEqual(request().text, "Hello, local voice.")
        with self.assertRaises(ValidationError):
            profile(license_reference=None)
        with self.assertRaises(ValidationError):
            profile(config={"api_token": "must-not-be-stored"})
        first = synthesis_fingerprint(request(), profile())
        second = synthesis_fingerprint(request(text="Different narration"), profile())
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertNotEqual(first, second)

    async def test_synthesizes_valid_pcm_wav_registers_lineage_and_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            store, provider, ingest = FakeStore(), WavProvider(), FakeAssetIngest()
            service = VoiceSynthesisService(
                provider=provider, store=store, asset_ingest=ingest, work_root=Path(directory),
            )
            first = await service.synthesize(request())
            second = await service.synthesize(request())

        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(first.evidence, WavEvidence(100, 16_000, 1, 2))
        self.assertEqual(ingest.calls[0]["kind"].value, "NARRATION")
        self.assertEqual(ingest.calls[0]["scene_id"], SCENE_ID)
        self.assertEqual(ingest.calls[0]["media_metadata"]["voice_profile_id"], PROFILE_ID.hex)
        self.assertTrue(ingest.payload.startswith(b"RIFF"))

    async def test_unverified_profile_fails_before_claim_or_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FakeStore(profile(license_status=VoiceLicenseStatus.UNVERIFIED, license_reference=None))
            provider = WavProvider()
            service = VoiceSynthesisService(
                provider=provider, store=store, asset_ingest=FakeAssetIngest(), work_root=Path(directory),
            )
            with self.assertRaises(TtsSynthesisError) as caught:
                await service.synthesize(request())
        self.assertEqual(caught.exception.code, "LICENSE_UNVERIFIED")
        self.assertEqual(provider.calls, 0)
        self.assertEqual(store.claims, [])

    async def test_provider_must_match_immutable_profile_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            store, provider = FakeStore(), WavProvider()
            provider.engine_version = "other-version"
            service = VoiceSynthesisService(
                provider=provider, store=store, asset_ingest=FakeAssetIngest(),
                work_root=Path(directory),
            )
            with self.assertRaises(TtsSynthesisError) as caught:
                await service.synthesize(request())
        self.assertEqual(caught.exception.code, "ENGINE_MISMATCH")
        self.assertEqual(store.claims, [])

    async def test_invalid_or_mismatched_output_records_stable_failure(self):
        for provider, code in [
            (WavProvider(invalid=True), "OUTPUT_SIZE_INVALID"),
            (WavProvider(rate=22_050), "OUTPUT_PROFILE_MISMATCH"),
        ]:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                store = FakeStore()
                service = VoiceSynthesisService(
                    provider=provider, store=store, asset_ingest=FakeAssetIngest(),
                    work_root=Path(directory),
                )
                with self.assertRaises(TtsSynthesisError) as caught:
                    await service.synthesize(request())
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(store.failed, [(REQUEST_ID, code)])

    async def test_timeout_is_bounded_and_completion_uncertainty_is_not_marked_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            timed_store = FakeStore()
            service = VoiceSynthesisService(
                provider=WavProvider(delay=.05), store=timed_store,
                asset_ingest=FakeAssetIngest(), work_root=Path(directory),
                policy=SynthesisPolicy(timeout_seconds=.01),
            )
            with self.assertRaises(TtsSynthesisError) as caught:
                await service.synthesize(request())
            self.assertEqual(caught.exception.code, "PROVIDER_TIMEOUT")
            self.assertEqual(timed_store.failed, [(REQUEST_ID, "PROVIDER_TIMEOUT")])

        with tempfile.TemporaryDirectory() as directory:
            uncertain_store = FakeStore()
            uncertain_store.complete_error = RuntimeError("database offline")
            service = VoiceSynthesisService(
                provider=WavProvider(), store=uncertain_store,
                asset_ingest=FakeAssetIngest(), work_root=Path(directory),
            )
            with self.assertRaises(TtsSynthesisError) as caught:
                await service.synthesize(request())
            self.assertEqual(caught.exception.code, "SYNTHESIS_RECONCILE_REQUIRED")
            self.assertEqual(uncertain_store.failed, [])


if __name__ == "__main__":
    unittest.main()
