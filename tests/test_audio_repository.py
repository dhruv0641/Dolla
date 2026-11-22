import json
import unittest
from contextlib import asynccontextmanager
from uuid import UUID

from flowx_os.audio.synthesis import (
    SynthesisRequest,
    SynthesisResult,
    VoiceConsentStatus,
    VoiceLicenseStatus,
    VoiceProfile,
    WavEvidence,
    synthesis_fingerprint,
)
from flowx_os.db.audio import AudioRepository, SynthesisStateConflict


PROFILE_ID = UUID("bc6077f2-bac0-4503-ac32-ec8149e02332")
BRAND_ID = UUID("94c52e8d-52d7-42f2-9499-a2e8a59206e4")
CONTENT_ID = UUID("24a3b953-3e5d-4e9d-906b-89e9f035972f")
SCENE_ID = UUID("5950c94b-648d-4658-aa3f-d7189f99d73b")
REQUEST_ID = UUID("2a8e06a2-e2a6-447a-a788-8f32123bf65f")
ASSET_ID = UUID("ece550bb-ff97-4169-9489-adada2579243")


def voice_profile():
    return VoiceProfile(
        profile_id=PROFILE_ID, brand_id=BRAND_ID, name="Narrator",
        engine_name="local-test", engine_version="1.0", voice_key="en-IN-A",
        language="en-IN", sample_rate_hz=16_000, channels=1,
        license_status=VoiceLicenseStatus.VERIFIED,
        license_reference="docs/licenses/local-test.md",
        consent_status=VoiceConsentStatus.NOT_REQUIRED,
        config={"model_ref": "models/local-test-v1"},
    )


def profile_row():
    profile = voice_profile()
    return (
        profile.profile_id, profile.brand_id, profile.name, profile.engine_name,
        profile.engine_version, profile.voice_key, profile.language,
        profile.sample_rate_hz, profile.channels, profile.source.value,
        profile.license_status.value, profile.license_reference,
        profile.consent_status.value, profile.consent_reference,
        profile.active, profile.config,
    )


def synthesis_request():
    return SynthesisRequest(
        request_id=REQUEST_ID, asset_id=ASSET_ID, profile_id=PROFILE_ID,
        brand_id=BRAND_ID, content_id=CONTENT_ID, scene_id=SCENE_ID,
        owner_user_id="owner-1", text="Narration",
    )


class FakeCursor:
    def __init__(self, one=None):
        self.one = one

    async def fetchone(self):
        return self.one


class FakeConnection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query, params=None):
        self.queries.append((query, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakePool:
    def __init__(self, responses):
        self.connection_value = FakeConnection(responses)

    @asynccontextmanager
    async def connection(self):
        yield self.connection_value


class AudioRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_creation_is_owner_scoped_and_idempotent(self):
        pool = FakePool([FakeCursor((1,)), FakeCursor(profile_row())])
        result = await AudioRepository(pool).create_profile(
            profile=voice_profile(), owner_user_id="owner-1",
        )
        self.assertEqual(result, voice_profile())
        self.assertIn("owner_user_id = %s", pool.connection_value.queries[0][0])
        self.assertIn("ON CONFLICT DO NOTHING", pool.connection_value.queries[1][0])
        self.assertNotIn("secret", pool.connection_value.queries[1][1][-1])

    async def test_new_claim_locks_owner_content_profile_and_scene_before_insert(self):
        request = synthesis_request()
        fingerprint = synthesis_fingerprint(request, voice_profile())
        pool = FakePool([
            FakeCursor(profile_row()), FakeCursor((1,)), FakeCursor((REQUEST_ID,)),
        ])
        claim = await AudioRepository(pool).claim(
            request=request, profile=voice_profile(), request_fingerprint=fingerprint,
        )
        self.assertTrue(claim.is_new)
        queries = pool.connection_value.queries
        self.assertIn("b.owner_user_id = %s", queries[0][0])
        self.assertIn("FOR SHARE OF vp, b, c", queries[0][0])
        self.assertEqual(queries[1][1], (SCENE_ID, CONTENT_ID))
        self.assertNotIn(request.text, queries[2][1])

    async def test_profile_deactivation_is_owner_scoped_and_irreversible_by_contract(self):
        inactive_row = list(profile_row())
        inactive_row[14] = False
        pool = FakePool([FakeCursor(tuple(inactive_row))])
        result = await AudioRepository(pool).deactivate_profile(
            profile_id=PROFILE_ID, brand_id=BRAND_ID, owner_user_id="owner-1",
        )
        self.assertFalse(result.active)
        query, params = pool.connection_value.queries[0]
        self.assertIn("SET active = false", query)
        self.assertIn("b.owner_user_id = %s", query)
        self.assertEqual(params, (PROFILE_ID, BRAND_ID, "owner-1"))

    async def test_completed_claim_replays_but_nonterminal_claim_fails_closed(self):
        request = synthesis_request()
        selected = voice_profile()
        fingerprint = synthesis_fingerprint(request, selected)
        snapshot = selected.model_dump(mode="json")
        completed = (
            ASSET_ID, PROFILE_ID, BRAND_ID, CONTENT_ID, SCENE_ID, fingerprint,
            snapshot, "COMPLETED", ASSET_ID, 100, 16_000, 1, 2,
        )
        pool = FakePool([
            FakeCursor(profile_row()), FakeCursor((1,)), FakeCursor(), FakeCursor(completed),
        ])
        claim = await AudioRepository(pool).claim(
            request=request, profile=selected, request_fingerprint=fingerprint,
        )
        self.assertFalse(claim.is_new)
        self.assertTrue(claim.completed.replayed)
        self.assertEqual(claim.completed.evidence, WavEvidence(100, 16_000, 1, 2))

        in_flight = (*completed[:7], "CLAIMED", None, None, None, None, None)
        pool = FakePool([
            FakeCursor(profile_row()), FakeCursor((1,)), FakeCursor(), FakeCursor(in_flight),
        ])
        with self.assertRaises(SynthesisStateConflict):
            await AudioRepository(pool).claim(
                request=request, profile=selected, request_fingerprint=fingerprint,
            )

    async def test_completion_requires_registered_active_narration_and_failure_is_bounded(self):
        fingerprint = synthesis_fingerprint(synthesis_request(), voice_profile())
        result = SynthesisResult(
            REQUEST_ID, ASSET_ID, fingerprint, WavEvidence(100, 16_000, 1, 2),
        )
        pool = FakePool([FakeCursor((REQUEST_ID,))])
        await AudioRepository(pool).complete(result=result)
        query, params = pool.connection_value.queries[0]
        self.assertIn("a.asset_kind = 'NARRATION'", query)
        self.assertIn("a.retention_state = 'ACTIVE'", query)
        self.assertEqual(params[-3:], (REQUEST_ID, ASSET_ID, fingerprint))

        pool = FakePool([FakeCursor((REQUEST_ID,))])
        await AudioRepository(pool).fail(request_id=REQUEST_ID, error_code="PROVIDER_FAILED")
        self.assertEqual(pool.connection_value.queries[0][1], ("PROVIDER_FAILED", REQUEST_ID))


if __name__ == "__main__":
    unittest.main()
