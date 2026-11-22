from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from flowx_os.publishing.youtube import (
    YOUTUBE_UPLOAD_SCOPE,
    YouTubeAuthorization,
    YouTubeError,
    YouTubePolicy,
    YouTubePrivacy,
    YouTubePublicationClaim,
    YouTubePublicationResult,
    YouTubePublisher,
    YouTubePublishRequest,
    YouTubeRemoteVideo,
    YouTubeUploadOutcome,
    YouTubeUploadSession,
    YouTubeUploadState,
)


NOW = datetime.now(timezone.utc)


def request(**changes):
    values = {
        "request_id": uuid4(), "publication_id": uuid4(), "brand_id": uuid4(),
        "content_id": uuid4(), "channel_id": uuid4(), "asset_id": uuid4(),
        "owner_user_id": "owner-1", "artifact_version": 3,
        "title": "Approved vertical video", "description": "Reviewed description.",
    }
    values.update(changes)
    return YouTubePublishRequest(**values)


def asset_bytes():
    return b"\x00\x00\x00\x18ftypmp42" + b"approved-video" * 10


def claim_for(req, data, **changes):
    values = {
        "publication_id": req.publication_id,
        "request_fingerprint": req.fingerprint,
        "brand_id": req.brand_id,
        "owner_user_id": req.owner_user_id,
        "content_id": req.content_id,
        "channel_id": req.channel_id,
        "asset_id": req.asset_id,
        "approval_decision_id": uuid4(),
        "artifact_version": req.artifact_version,
        "channel_external_id": "UC_verified_channel",
        "credentials_ref": "secretref://os/youtube-owner-1",
        "asset_storage_uri": f"managed://assets/{req.asset_id.hex}/payload",
        "asset_sha256_hex": hashlib.sha256(data).hexdigest(),
        "asset_size_bytes": len(data),
        "asset_mime_type": "video/mp4",
        "privacy_status": req.privacy_status,
        "status": "DRAFT",
    }
    values.update(changes)
    return YouTubePublicationClaim(**values)


class FakeStore:
    def __init__(self, claim):
        self.current = claim
        self.calls = []

    async def claim(self, publish_request):
        self.calls.append(("claim", publish_request))
        return self.current

    async def record_session(self, *, claim, session):
        self.calls.append(("session", session))
        self.current = replace(
            claim, status="UPLOAD_STARTED", upload_session_ref=session.session_ref,
            remote_upload_id=session.upload_id,
        )
        return self.current

    async def record_upload(self, *, claim, outcome):
        self.calls.append(("upload", outcome))
        status = {
            YouTubeUploadState.INCOMPLETE: "UPLOAD_STARTED",
            YouTubeUploadState.COMPLETE: "PROCESSING",
            YouTubeUploadState.UNKNOWN: "VERIFY_PENDING",
        }[outcome.state]
        self.current = replace(claim, status=status, remote_video_id=outcome.video_id)
        return self.current

    async def record_transport_failure(self, *, claim, error):
        self.calls.append(("failure", error.code, error.ambiguous))
        self.current = replace(
            claim,
            status=("VERIFY_PENDING" if error.ambiguous or claim.upload_session_ref else "FAILED"),
        )

    async def record_verification(self, *, claim, remote, status):
        self.calls.append(("verification", status, remote))
        self.current = replace(claim, status=status, remote_video_id=remote.video_id)
        return YouTubePublicationResult(
            claim.publication_id, status, remote.video_id,
            remote.canonical_url if status == "PUBLISHED" else None,
        )


class FakeTransport:
    def __init__(self, *, outcome=None, remote=None, authorization=None):
        self.calls = []
        self.authorization = authorization or YouTubeAuthorization(
            "UC_verified_channel", (YOUTUBE_UPLOAD_SCOPE,),
            NOW - timedelta(seconds=1), NOW + timedelta(hours=1),
        )
        self.outcome = outcome or YouTubeUploadOutcome(
            YouTubeUploadState.COMPLETE, len(asset_bytes()), "video_123",
        )
        self.remote = remote or YouTubeRemoteVideo(
            "video_123", "UC_verified_channel", "processed", "succeeded",
            YouTubePrivacy.PRIVATE,
        )

    async def check_authorization(self, **kwargs):
        self.calls.append(("auth", kwargs))
        return self.authorization

    async def start_resumable_upload(self, **kwargs):
        self.calls.append(("start", kwargs))
        return YouTubeUploadSession("secretref://runtime/youtube-session-1", "upload_123")

    async def resume_upload(self, **kwargs):
        self.calls.append(("resume", kwargs))
        path = kwargs["source_path"]
        self.snapshot_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        return self.outcome

    async def get_video(self, **kwargs):
        self.calls.append(("get", kwargs))
        return self.remote


class ExplodingTransport(FakeTransport):
    async def start_resumable_upload(self, **kwargs):
        raise RuntimeError("raw transport detail must not escape")


class YouTubePublishingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = asset_bytes()
        self.req = request()
        object_dir = self.root / "assets" / self.req.asset_id.hex
        object_dir.mkdir(parents=True)
        (object_dir / "payload").write_bytes(self.data)

    def tearDown(self):
        self.temporary.cleanup()

    def publisher(self, store, transport, policy=None):
        return YouTubePublisher(
            storage_root=self.root, store=store, transport=transport,
            policy=policy or YouTubePolicy(enabled=True),
        )

    async def test_disabled_default_has_no_store_or_transport_side_effect(self):
        store = FakeStore(claim_for(self.req, self.data))
        transport = FakeTransport()
        with self.assertRaisesRegex(YouTubeError, "disabled"):
            await YouTubePublisher(
                storage_root=self.root, store=store, transport=transport,
            ).publish(self.req)
        self.assertEqual(store.calls, [])
        self.assertEqual(transport.calls, [])

    async def test_happy_path_snapshots_exact_asset_and_requires_remote_proof(self):
        store = FakeStore(claim_for(self.req, self.data))
        transport = FakeTransport()
        result = await self.publisher(store, transport).publish(self.req)
        self.assertEqual(result.status, "PUBLISHED")
        self.assertEqual(result.remote_url, "https://www.youtube.com/watch?v=video_123")
        self.assertEqual(transport.snapshot_hash, hashlib.sha256(self.data).hexdigest())
        start = next(value for name, value in transport.calls if name == "start")
        self.assertFalse(start["metadata"]["notify_subscribers"])
        self.assertEqual(start["metadata"]["privacy_status"], "private")
        self.assertEqual([item[0] for item in store.calls], [
            "claim", "session", "upload", "verification",
        ])

    async def test_processing_is_not_misreported_as_published(self):
        store = FakeStore(claim_for(self.req, self.data))
        transport = FakeTransport(remote=YouTubeRemoteVideo(
            "video_123", "UC_verified_channel", "uploaded", "processing",
            YouTubePrivacy.PRIVATE,
        ))
        result = await self.publisher(store, transport).publish(self.req)
        self.assertEqual(result.status, "PROCESSING")
        self.assertIsNone(result.remote_url)

    async def test_terminal_remote_processing_is_failed(self):
        store = FakeStore(claim_for(self.req, self.data))
        transport = FakeTransport(remote=YouTubeRemoteVideo(
            "video_123", "UC_verified_channel", "rejected", "failed",
            YouTubePrivacy.PRIVATE,
        ))
        result = await self.publisher(store, transport).publish(self.req)
        self.assertEqual(result.status, "FAILED")

    async def test_incomplete_upload_keeps_same_resumable_identity(self):
        outcome = YouTubeUploadOutcome(YouTubeUploadState.INCOMPLETE, 20)
        store = FakeStore(claim_for(self.req, self.data))
        transport = FakeTransport(outcome=outcome)
        first = await self.publisher(store, transport).publish(self.req)
        self.assertEqual(first.status, "UPLOAD_STARTED")
        transport.calls.clear()
        second = await self.publisher(store, transport).reconcile(self.req)
        self.assertEqual(second.status, "UPLOAD_STARTED")
        self.assertNotIn("start", [item[0] for item in transport.calls])
        self.assertIn("resume", [item[0] for item in transport.calls])

    async def test_existing_video_identity_verifies_without_reupload(self):
        current = claim_for(
            self.req, self.data, status="PROCESSING",
            upload_session_ref="secretref://runtime/youtube-session-1",
            remote_upload_id="upload_123", remote_video_id="video_123",
        )
        store, transport = FakeStore(current), FakeTransport()
        result = await self.publisher(store, transport).publish(self.req)
        self.assertEqual(result.status, "PUBLISHED")
        self.assertNotIn("resume", [item[0] for item in transport.calls])

    async def test_wrong_channel_or_missing_scope_fails_before_upload(self):
        for authorization in (
            YouTubeAuthorization(
                "UC_other", (YOUTUBE_UPLOAD_SCOPE,), NOW, NOW + timedelta(hours=1),
            ),
            YouTubeAuthorization(
                "UC_verified_channel", ("https://www.googleapis.com/auth/youtube.readonly",),
                NOW, NOW + timedelta(hours=1),
            ),
        ):
            store, transport = FakeStore(claim_for(self.req, self.data)), FakeTransport(
                authorization=authorization,
            )
            with self.subTest(channel=authorization.channel_external_id), self.assertRaisesRegex(
                YouTubeError, "authorization",
            ):
                await self.publisher(store, transport).publish(self.req)
            self.assertNotIn("start", [item[0] for item in transport.calls])

    async def test_untrusted_remote_identity_is_rejected_and_recorded(self):
        store = FakeStore(claim_for(self.req, self.data))
        transport = FakeTransport(remote=YouTubeRemoteVideo(
            "other_video", "UC_verified_channel", "processed", "succeeded",
            YouTubePrivacy.PRIVATE,
        ))
        with self.assertRaisesRegex(YouTubeError, "identity"):
            await self.publisher(store, transport).publish(self.req)
        self.assertIn("failure", [item[0] for item in store.calls])

    async def test_unknown_start_outcome_is_sanitized_and_never_retried_blindly(self):
        store = FakeStore(claim_for(self.req, self.data))
        transport = ExplodingTransport()
        with self.assertRaises(YouTubeError) as caught:
            await self.publisher(store, transport).publish(self.req)
        self.assertEqual(caught.exception.code, "TRANSPORT_OUTCOME_UNKNOWN")
        self.assertNotIn("raw transport", str(caught.exception))
        with self.assertRaises(YouTubeError) as retry:
            await self.publisher(store, transport).publish(self.req)
        self.assertEqual(retry.exception.code, "PUBLICATION_OUTCOME_UNKNOWN")
        self.assertIn(("failure", "TRANSPORT_OUTCOME_UNKNOWN", True), store.calls)

        store.current = replace(store.current, status="VERIFY_PENDING")
        transport = FakeTransport()
        with self.assertRaises(YouTubeError) as retry:
            await self.publisher(store, transport).publish(self.req)
        self.assertEqual(retry.exception.code, "PUBLICATION_OUTCOME_UNKNOWN")
        self.assertNotIn("start", [item[0] for item in transport.calls])

    async def test_asset_integrity_mismatch_fails_after_session_without_upload(self):
        current = claim_for(self.req, self.data, asset_sha256_hex="0" * 64)
        store, transport = FakeStore(current), FakeTransport()
        with self.assertRaisesRegex(YouTubeError, "integrity"):
            await self.publisher(store, transport).publish(self.req)
        self.assertNotIn("resume", [item[0] for item in transport.calls])
        self.assertIn("failure", [item[0] for item in store.calls])

    async def test_public_visibility_requires_explicit_policy(self):
        public_request = request(
            request_id=self.req.request_id, publication_id=self.req.publication_id,
            brand_id=self.req.brand_id, content_id=self.req.content_id,
            channel_id=self.req.channel_id, asset_id=self.req.asset_id,
            privacy_status=YouTubePrivacy.PUBLIC,
        )
        store = FakeStore(claim_for(public_request, self.data))
        with self.assertRaisesRegex(YouTubeError, "privacy"):
            await self.publisher(store, FakeTransport()).publish(public_request)

    def test_request_rejects_controls_and_fingerprint_binds_visibility(self):
        with self.assertRaises(ValueError):
            request(title="unsafe\nmetadata")
        changed = replace(self.req, privacy_status=YouTubePrivacy.UNLISTED)
        self.assertNotEqual(self.req.fingerprint, changed.fingerprint)

    def test_untrusted_transport_models_are_strict(self):
        with self.assertRaises(ValueError):
            YouTubeUploadSession("https://secret-session.example", "upload_123")
        with self.assertRaises(ValueError):
            YouTubeUploadOutcome(YouTubeUploadState.COMPLETE, 1)
        with self.assertRaises(ValueError):
            YouTubeRemoteVideo(
                "video 123", "UC_verified_channel", "processed", "succeeded",
                YouTubePrivacy.PRIVATE,
            )


if __name__ == "__main__":
    unittest.main()
