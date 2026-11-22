import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from flowx_os.publishing.instagram import (
    INSTAGRAM_BASIC_SCOPE,
    INSTAGRAM_PUBLISH_SCOPE,
    InstagramAccountType,
    InstagramAuthorization,
    InstagramContainer,
    InstagramContainerState,
    InstagramContainerStatus,
    InstagramError,
    InstagramPolicy,
    InstagramPublicationClaim,
    InstagramPublicationResult,
    InstagramPublishedMedia,
    InstagramPublisher,
    InstagramPublishRequest,
    InstagramRemoteMedia,
)


NOW = datetime.now(timezone.utc)


def asset_bytes():
    return b"\x00\x00\x00\x18ftypmp42" + b"approved-instagram-reel" * 10


def request(**changes):
    values = {
        "request_id": uuid4(), "publication_id": uuid4(), "brand_id": uuid4(),
        "content_id": uuid4(), "channel_id": uuid4(), "asset_id": uuid4(),
        "owner_user_id": "owner-1", "artifact_version": 4,
        "media_source_ref": "secretref://media/instagram/reel-1",
        "caption": "Reviewed Reel caption", "share_to_feed": False,
    }
    values.update(changes)
    return InstagramPublishRequest(**values)


def claim_for(req, data, **changes):
    values = {
        "publication_id": req.publication_id,
        "request_fingerprint": req.fingerprint,
        "brand_id": req.brand_id, "owner_user_id": req.owner_user_id,
        "content_id": req.content_id, "channel_id": req.channel_id,
        "asset_id": req.asset_id, "approval_decision_id": uuid4(),
        "artifact_version": req.artifact_version,
        "professional_account_id": "ig_professional_123",
        "credentials_ref": "secretref://os/instagram-owner-1",
        "destination_fingerprint": hashlib.sha256(
            b"ig_professional_123|secretref://os/instagram-owner-1"
        ).hexdigest(),
        "media_source_ref": req.media_source_ref,
        "asset_storage_uri": f"managed://assets/{req.asset_id.hex}/payload",
        "asset_sha256_hex": hashlib.sha256(data).hexdigest(),
        "asset_size_bytes": len(data), "asset_mime_type": "video/mp4",
        "status": "DRAFT", "phase": "CLAIMED",
    }
    values.update(changes)
    return InstagramPublicationClaim(**values)


class FakeStore:
    def __init__(self, claim):
        self.current = claim
        self.calls = []
        self.lock = asyncio.Lock()

    async def claim(self, publish_request):
        self.calls.append(("claim", publish_request))
        return self.current

    async def assert_network_ready(self, claim):
        self.calls.append(("ready", claim.phase))

    async def reserve_container(self, claim):
        async with self.lock:
            if self.current.phase != "CLAIMED":
                raise InstagramError("START_ALREADY_RESERVED", "container start already reserved")
            self.current = replace(claim, status="UPLOAD_STARTED", phase="CONTAINER_RESERVED")
            self.calls.append(("reserve_container", claim.publication_id))
            return self.current

    async def record_container(self, *, claim, container):
        self.current = replace(
            claim, status="PROCESSING", phase="CONTAINER_CREATED",
            remote_container_id=container.container_id,
        )
        self.calls.append(("container", container.container_id))
        return self.current

    async def record_container_status(self, *, claim, remote):
        phase = {
            InstagramContainerState.IN_PROGRESS: "CONTAINER_PROCESSING",
            InstagramContainerState.FINISHED: "CONTAINER_READY",
            InstagramContainerState.PUBLISHED: (
                "MEDIA_RECORDED" if claim.remote_media_id else "MEDIA_ID_UNKNOWN"
            ),
            InstagramContainerState.ERROR: "FAILED",
            InstagramContainerState.EXPIRED: "FAILED",
        }[remote.state]
        status = "PROCESSING"
        if remote.state == InstagramContainerState.PUBLISHED:
            status = "VERIFY_PENDING"
        elif remote.state in {InstagramContainerState.ERROR, InstagramContainerState.EXPIRED}:
            status = "FAILED"
        self.current = replace(
            claim, status=status, phase=phase,
            verification_attempt_count=claim.verification_attempt_count + 1,
        )
        self.calls.append(("container_status", remote.state.value))
        return self.current

    async def reserve_publish(self, claim):
        async with self.lock:
            if self.current.phase != "CONTAINER_READY":
                raise InstagramError("PUBLISH_ALREADY_RESERVED", "publish already reserved")
            self.current = replace(claim, status="PUBLISH_REQUESTED", phase="PUBLISH_RESERVED")
            self.calls.append(("reserve_publish", claim.publication_id))
            return self.current

    async def record_media(self, *, claim, media):
        self.current = replace(
            claim, status="VERIFY_PENDING", phase="MEDIA_RECORDED",
            remote_media_id=media.media_id,
        )
        self.calls.append(("media", media.media_id))
        return self.current

    async def record_transport_failure(self, *, claim, error):
        self.calls.append(("failure", error.code, error.ambiguous))

    async def record_verification(self, *, claim, container, media):
        self.current = replace(
            claim, status="PUBLISHED", phase="VERIFIED", remote_url=media.permalink,
            verification_attempt_count=claim.verification_attempt_count + 1,
        )
        self.calls.append(("verification", container.state.value, media.media_id))
        return InstagramPublicationResult(
            claim.publication_id, "PUBLISHED", media.media_id, media.permalink,
        )

    async def recover_container(self, *, request, container):
        self.current = replace(
            self.current, status="PROCESSING", phase="CONTAINER_CREATED",
            remote_container_id=container.container_id,
        )
        return self.current

    async def recover_media(self, *, request, media):
        self.current = replace(
            self.current, status="VERIFY_PENDING", phase="MEDIA_RECORDED",
            remote_media_id=media.media_id,
        )
        return self.current

    async def cancel_unknown(self, *, request, reason):
        self.current = replace(self.current, status="CANCELLED", phase="CANCELLED")
        return InstagramPublicationResult(self.current.publication_id, "CANCELLED")


class FakeTransport:
    def __init__(self, *, authorization=None, statuses=None, remote=None):
        self.calls = []
        self.authorization = authorization or InstagramAuthorization(
            "ig_professional_123", InstagramAccountType.BUSINESS,
            (INSTAGRAM_BASIC_SCOPE, INSTAGRAM_PUBLISH_SCOPE),
            NOW - timedelta(seconds=1), NOW + timedelta(hours=1),
        )
        self.statuses = list(statuses or [
            InstagramContainerState.FINISHED, InstagramContainerState.PUBLISHED,
        ])
        self.remote = remote or InstagramRemoteMedia(
            "media_123", "ig_professional_123", "VIDEO",
            "https://www.instagram.com/reel/ABC_123/",
        )

    async def check_authorization(self, **kwargs):
        self.calls.append(("auth", kwargs))
        return self.authorization

    async def create_reel_container(self, **kwargs):
        self.calls.append(("create", kwargs))
        return InstagramContainer("container_123")

    async def get_container(self, **kwargs):
        self.calls.append(("get_container", kwargs))
        state = self.statuses.pop(0) if self.statuses else InstagramContainerState.PUBLISHED
        return InstagramContainerStatus("container_123", state)

    async def publish_container(self, **kwargs):
        self.calls.append(("publish", kwargs))
        return InstagramPublishedMedia("media_123")

    async def get_media(self, **kwargs):
        self.calls.append(("get_media", kwargs))
        return self.remote


class ExplodingCreateTransport(FakeTransport):
    async def create_reel_container(self, **kwargs):
        self.calls.append(("create", kwargs))
        raise RuntimeError("raw access token detail must not escape")


class ExplodingPublishTransport(FakeTransport):
    async def publish_container(self, **kwargs):
        self.calls.append(("publish", kwargs))
        raise RuntimeError("raw credential detail must not escape")


class BlockingCreateTransport(FakeTransport):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.create_count = 0

    async def create_reel_container(self, **kwargs):
        self.create_count += 1
        self.started.set()
        await self.release.wait()
        return await super().create_reel_container(**kwargs)


class InstagramPublishingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = asset_bytes()
        self.req = request()
        directory = self.root / "assets" / self.req.asset_id.hex
        directory.mkdir(parents=True)
        (directory / "payload").write_bytes(self.data)

    def tearDown(self):
        self.temporary.cleanup()

    def publisher(self, store, transport, policy=None):
        return InstagramPublisher(
            storage_root=self.root, store=store, transport=transport,
            policy=policy or InstagramPolicy(enabled=True),
        )

    async def test_disabled_default_has_no_side_effect(self):
        store, transport = FakeStore(claim_for(self.req, self.data)), FakeTransport()
        with self.assertRaisesRegex(InstagramError, "disabled"):
            await InstagramPublisher(
                storage_root=self.root, store=store, transport=transport,
            ).publish(self.req)
        self.assertEqual(store.calls, [])
        self.assertEqual(transport.calls, [])

    async def test_happy_path_requires_container_and_media_proof(self):
        store, transport = FakeStore(claim_for(self.req, self.data)), FakeTransport()
        result = await self.publisher(store, transport).publish(self.req)
        self.assertEqual(result.status, "PUBLISHED")
        self.assertEqual(result.remote_url, "https://www.instagram.com/reel/ABC_123/")
        create = next(value for name, value in transport.calls if name == "create")
        self.assertEqual(create["media_source_ref"], self.req.media_source_ref)
        self.assertEqual(create["asset_sha256_hex"], hashlib.sha256(self.data).hexdigest())
        self.assertEqual(create["metadata"]["media_type"], "REELS")
        self.assertTrue(create["metadata"]["is_ai_generated"])
        self.assertFalse(create["metadata"]["share_to_feed"])

    async def test_processing_container_is_not_published(self):
        store = FakeStore(claim_for(self.req, self.data))
        result = await self.publisher(
            store, FakeTransport(statuses=[InstagramContainerState.IN_PROGRESS]),
        ).publish(self.req)
        self.assertEqual(result.status, "PROCESSING")
        self.assertIsNone(result.remote_url)

    async def test_terminal_container_is_failed(self):
        for state in (InstagramContainerState.ERROR, InstagramContainerState.EXPIRED):
            with self.subTest(state=state):
                store = FakeStore(claim_for(self.req, self.data))
                result = await self.publisher(
                    store, FakeTransport(statuses=[state]),
                ).publish(self.req)
                self.assertEqual(result.status, "FAILED")

    async def test_wrong_account_or_missing_scope_fails_before_container(self):
        authorizations = (
            InstagramAuthorization(
                "other_account", InstagramAccountType.CREATOR,
                (INSTAGRAM_BASIC_SCOPE, INSTAGRAM_PUBLISH_SCOPE), NOW, NOW + timedelta(hours=1),
            ),
            InstagramAuthorization(
                "ig_professional_123", InstagramAccountType.BUSINESS,
                (INSTAGRAM_BASIC_SCOPE,), NOW, NOW + timedelta(hours=1),
            ),
        )
        for authorization in authorizations:
            store, transport = FakeStore(claim_for(self.req, self.data)), FakeTransport(
                authorization=authorization,
            )
            with self.assertRaisesRegex(InstagramError, "authorization"):
                await self.publisher(store, transport).publish(self.req)
            self.assertNotIn("create", [call[0] for call in transport.calls])

    async def test_unknown_container_outcome_is_not_retried(self):
        store, transport = FakeStore(claim_for(self.req, self.data)), ExplodingCreateTransport()
        with self.assertRaises(InstagramError) as caught:
            await self.publisher(store, transport).publish(self.req)
        self.assertEqual(caught.exception.code, "CONTAINER_OUTCOME_UNKNOWN")
        self.assertNotIn("raw access", str(caught.exception))
        with self.assertRaises(InstagramError) as retry:
            await self.publisher(store, transport).publish(self.req)
        self.assertEqual(retry.exception.code, "PUBLICATION_OUTCOME_UNKNOWN")
        self.assertEqual([call[0] for call in transport.calls].count("create"), 1)

    async def test_unknown_publish_outcome_is_not_retried(self):
        store, transport = FakeStore(claim_for(self.req, self.data)), ExplodingPublishTransport()
        with self.assertRaises(InstagramError) as caught:
            await self.publisher(store, transport).publish(self.req)
        self.assertEqual(caught.exception.code, "PUBLISH_OUTCOME_UNKNOWN")
        with self.assertRaises(InstagramError) as retry:
            await self.publisher(store, transport).publish(self.req)
        self.assertEqual(retry.exception.code, "PUBLICATION_OUTCOME_UNKNOWN")
        self.assertEqual([call[0] for call in transport.calls].count("publish"), 1)

    async def test_atomic_container_reservation_has_single_winner(self):
        store = FakeStore(claim_for(self.req, self.data))
        transport = BlockingCreateTransport()
        publisher = self.publisher(store, transport)
        first = asyncio.create_task(publisher.publish(self.req))
        await transport.started.wait()
        with self.assertRaises(InstagramError) as second:
            await publisher.publish(self.req)
        self.assertEqual(second.exception.code, "PUBLICATION_OUTCOME_UNKNOWN")
        transport.release.set()
        self.assertEqual((await first).status, "PUBLISHED")
        self.assertEqual(transport.create_count, 1)

    async def test_remote_identity_mismatch_is_rejected(self):
        remote = InstagramRemoteMedia(
            "media_123", "other_account", "VIDEO",
            "https://www.instagram.com/reel/ABC_123/",
        )
        store = FakeStore(claim_for(self.req, self.data))
        with self.assertRaises(InstagramError) as caught:
            await self.publisher(store, FakeTransport(remote=remote)).publish(self.req)
        self.assertEqual(caught.exception.code, "REMOTE_IDENTITY_MISMATCH")
        self.assertIn("failure", [call[0] for call in store.calls])

    async def test_asset_integrity_is_checked_before_container_creation(self):
        store = FakeStore(claim_for(self.req, self.data, asset_sha256_hex="0" * 64))
        transport = FakeTransport()
        with self.assertRaisesRegex(InstagramError, "integrity"):
            await self.publisher(store, transport).publish(self.req)
        self.assertNotIn("create", [call[0] for call in transport.calls])

    async def test_verification_attempt_limit_fails_closed(self):
        current = claim_for(
            self.req, self.data, status="PROCESSING", phase="CONTAINER_PROCESSING",
            remote_container_id="container_123", verification_attempt_count=5,
        )
        store, transport = FakeStore(current), FakeTransport()
        with self.assertRaises(InstagramError) as caught:
            await self.publisher(store, transport).publish(self.req)
        self.assertEqual(caught.exception.code, "VERIFY_LIMIT_REACHED")
        self.assertNotIn("get_container", [call[0] for call in transport.calls])

    async def test_operator_recovery_and_cancellation_do_not_use_network(self):
        unknown = claim_for(
            self.req, self.data, status="UPLOAD_STARTED", phase="CONTAINER_RESERVED",
        )
        store, transport = FakeStore(unknown), FakeTransport()
        publisher = self.publisher(store, transport)
        recovered = await publisher.recover_container(
            request=self.req, container=InstagramContainer("container_recovered"),
        )
        self.assertEqual(recovered.phase, "CONTAINER_CREATED")
        self.assertEqual(transport.calls, [])

        store.current = replace(
            unknown, status="PUBLISH_REQUESTED", phase="PUBLISH_RESERVED",
            remote_container_id="container_recovered",
        )
        media = await publisher.recover_media(
            request=self.req, media=InstagramPublishedMedia("media_recovered"),
        )
        self.assertEqual(media.phase, "MEDIA_RECORDED")
        self.assertEqual(transport.calls, [])

        store.current = replace(unknown, status="UPLOAD_STARTED", phase="CONTAINER_RESERVED")
        cancelled = await publisher.cancel_unknown(
            request=self.req, reason="Operator verified no remote container exists.",
        )
        self.assertEqual(cancelled.status, "CANCELLED")
        self.assertEqual(transport.calls, [])

    def test_request_rejects_unsafe_metadata_and_binds_source(self):
        with self.assertRaises(ValueError):
            request(caption="unsafe\ncaption")
        with self.assertRaises(ValueError):
            request(media_source_ref="https://public.example/video.mp4")
        first = request()
        second = request(
            request_id=first.request_id, publication_id=first.publication_id,
            brand_id=first.brand_id, content_id=first.content_id,
            channel_id=first.channel_id, asset_id=first.asset_id,
            media_source_ref="secretref://media/instagram/reel-2",
        )
        self.assertNotEqual(first.fingerprint, second.fingerprint)


if __name__ == "__main__":
    unittest.main()
