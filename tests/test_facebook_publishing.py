import hashlib
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flowx_os.publishing.facebook import (  # noqa: E402
    FACEBOOK_CREATE_CONTENT_TASK,
    FACEBOOK_PAGES_MANAGE_POSTS_SCOPE,
    FACEBOOK_PAGES_READ_ENGAGEMENT_SCOPE,
    FACEBOOK_PAGES_SHOW_LIST_SCOPE,
    FacebookAuthorization,
    FacebookError,
    FacebookPolicy,
    FacebookPublicationClaim,
    FacebookPublicationResult,
    FacebookPublishReceipt,
    FacebookPublisher,
    FacebookPublishRequest,
    FacebookRemoteReel,
    FacebookUploadReceipt,
    FacebookUploadSession,
    FacebookVideoState,
    FacebookVideoStatus,
)


SCOPES = (
    FACEBOOK_PAGES_SHOW_LIST_SCOPE,
    FACEBOOK_PAGES_READ_ENGAGEMENT_SCOPE,
    FACEBOOK_PAGES_MANAGE_POSTS_SCOPE,
)


def request() -> FacebookPublishRequest:
    return FacebookPublishRequest(
        request_id=uuid4(), publication_id=uuid4(), brand_id=uuid4(),
        content_id=uuid4(), channel_id=uuid4(), asset_id=uuid4(),
        owner_user_id="owner-1", artifact_version=3,
        title=" Reel title ", description=" Reel description ",
    )


def status(
    claim: FacebookPublicationClaim, state: FacebookVideoState,
    *, published: bool = False,
) -> FacebookVideoStatus:
    complete = state == FacebookVideoState.READY
    return FacebookVideoStatus(
        video_id=claim.remote_video_id or "video-1", page_id=claim.page_id,
        state=state, uploading_status="completed" if complete else "in_progress",
        processing_status="completed" if complete else "in_progress",
        publishing_status="completed" if published else "not_started",
        publish_status="published" if published else "not_started",
        bytes_transferred=claim.asset_size_bytes if complete else 0,
        source_file_size=claim.asset_size_bytes,
    )


class Store:
    def __init__(self, claim: FacebookPublicationClaim) -> None:
        self.value = claim
        self.fail_assert_at: int | None = None
        self.assertions = 0
        self.errors: list[FacebookError] = []

    async def claim(self, publication_request):
        return self.value

    async def assert_network_ready(self, claim):
        self.assertions += 1
        if self.fail_assert_at == self.assertions:
            raise FacebookError("AUTHORIZATION_REVOKED", "Page authorization changed")

    async def reserve_start(self, claim):
        self.value = replace(claim, status="UPLOAD_STARTED", phase="START_RESERVED")
        return self.value

    async def record_session(self, *, claim, session):
        self.value = replace(
            claim, phase="SESSION_CREATED", remote_video_id=session.video_id,
            upload_session_ref=session.upload_session_ref,
        )
        return self.value

    async def reserve_upload(self, claim):
        self.value = replace(claim, status="PROCESSING", phase="UPLOAD_RESERVED")
        return self.value

    async def record_upload(self, *, claim, receipt):
        self.value = replace(claim, phase="UPLOAD_ACCEPTED")
        return self.value

    async def record_video_status(self, *, claim, remote):
        if remote.state in {FacebookVideoState.ERROR, FacebookVideoState.EXPIRED,
                            FacebookVideoState.UPLOAD_FAILED}:
            phase, publication_status = "FAILED", "FAILED"
        elif claim.phase == "PUBLISH_ACCEPTED":
            phase, publication_status = "PUBLISH_ACCEPTED", "VERIFY_PENDING"
        elif remote.state == FacebookVideoState.READY:
            phase, publication_status = "VIDEO_READY", "PROCESSING"
        else:
            phase, publication_status = "VIDEO_PROCESSING", "PROCESSING"
        self.value = replace(
            claim, phase=phase, status=publication_status,
            verification_attempt_count=claim.verification_attempt_count + 1,
        )
        return self.value

    async def reserve_publish(self, claim):
        self.value = replace(claim, status="PUBLISH_REQUESTED", phase="PUBLISH_RESERVED")
        return self.value

    async def record_publish(self, *, claim, receipt):
        self.value = replace(
            claim, status="VERIFY_PENDING", phase="PUBLISH_ACCEPTED",
            remote_post_id=receipt.post_id,
        )
        return self.value

    async def record_transport_failure(self, *, claim, error):
        self.errors.append(error)

    async def record_verification(self, *, claim, status, remote):
        self.value = replace(
            claim, status="PUBLISHED", phase="VERIFIED",
            remote_post_id=remote.post_id, remote_url=remote.permalink,
        )
        return FacebookPublicationResult(
            claim.publication_id, "PUBLISHED", claim.remote_video_id, remote.permalink,
        )

    async def recover_session(self, *, request, session):
        return await self.record_session(claim=self.value, session=session)

    async def recover_upload(self, *, request, status):
        self.value = replace(self.value, status="PROCESSING", phase="UPLOAD_ACCEPTED")
        return self.value

    async def recover_publish(self, *, request, receipt):
        return await self.record_publish(claim=self.value, receipt=receipt)

    async def cancel_unknown(self, *, request, reason):
        self.value = replace(self.value, status="CANCELLED", phase="CANCELLED")
        return FacebookPublicationResult(self.value.publication_id, "CANCELLED")


class Transport:
    def __init__(self, claim: FacebookPublicationClaim) -> None:
        self.claim = claim
        self.calls: list[str] = []
        self.remote_status = status(
            replace(claim, remote_video_id="video-1"), FacebookVideoState.READY,
        )
        self.failure_at: str | None = None
        self.authorization = FacebookAuthorization(
            page_id=claim.page_id, granted_scopes=SCOPES,
            granted_tasks=(FACEBOOK_CREATE_CONTENT_TASK,),
            checked_at=datetime.now(timezone.utc),
            valid_until=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.failure_at == name:
            raise RuntimeError("remote response lost")

    async def check_authorization(self, **kwargs):
        self._call("authorize")
        return self.authorization

    async def start_reel_upload(self, **kwargs):
        self._call("start")
        return FacebookUploadSession("video-1", "secretref://meta/upload/session-1")

    async def upload_reel(self, **kwargs):
        self._call("upload")
        self.upload_snapshot = kwargs["source_path"].read_bytes()
        return FacebookUploadReceipt("video-1", True)

    async def get_video_status(self, **kwargs):
        self._call("status")
        return self.remote_status

    async def finish_reel(self, **kwargs):
        self._call("finish")
        return FacebookPublishReceipt("video-1", True, "post-1")

    async def get_reel(self, **kwargs):
        self._call("reel")
        return FacebookRemoteReel(
            "video-1", self.claim.page_id, "post-1",
            "https://www.facebook.com/reel/12345", True,
        )


class FacebookPublishingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.request = request()
        payload = b"\x00\x00\x00\x18ftypisom" + b"x" * 2048
        path = self.root / "assets" / self.request.asset_id.hex / "payload"
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
        destination = hashlib.sha256(b"123456|secretref://meta/page/token").hexdigest()
        self.claim = FacebookPublicationClaim(
            publication_id=self.request.publication_id,
            request_fingerprint=self.request.fingerprint,
            brand_id=self.request.brand_id, owner_user_id=self.request.owner_user_id,
            content_id=self.request.content_id, channel_id=self.request.channel_id,
            asset_id=self.request.asset_id, approval_decision_id=uuid4(),
            artifact_version=self.request.artifact_version, page_id="123456",
            credentials_ref="secretref://meta/page/token",
            destination_fingerprint=destination,
            asset_storage_uri=f"managed://assets/{self.request.asset_id.hex}/payload",
            asset_sha256_hex=hashlib.sha256(payload).hexdigest(),
            asset_size_bytes=len(payload), asset_mime_type="video/mp4",
            status="DRAFT", phase="CLAIMED",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def publisher(self, store=None, transport=None, **policy):
        store = store or Store(self.claim)
        transport = transport or Transport(self.claim)
        return FacebookPublisher(
            storage_root=self.root, store=store, transport=transport,
            policy=FacebookPolicy(enabled=True, **policy),
        ), store, transport

    async def test_disabled_by_default_has_no_side_effect(self) -> None:
        store, transport = Store(self.claim), Transport(self.claim)
        publisher = FacebookPublisher(storage_root=self.root, store=store, transport=transport)
        with self.assertRaisesRegex(FacebookError, "disabled"):
            await publisher.publish(self.request)
        self.assertEqual(transport.calls, [])

    async def test_three_mutations_are_separately_fenced_then_verified(self) -> None:
        publisher, store, transport = self.publisher()
        first = await publisher.publish(self.request)
        self.assertEqual((first.status, store.value.phase), ("UPLOAD_STARTED", "SESSION_CREATED"))
        self.assertEqual(transport.calls.count("start"), 1)
        self.assertEqual(transport.calls.count("upload"), 0)

        second = await publisher.publish(self.request)
        self.assertEqual((second.status, store.value.phase), ("PROCESSING", "UPLOAD_ACCEPTED"))
        self.assertEqual(transport.calls.count("upload"), 1)
        self.assertEqual(transport.calls.count("finish"), 0)
        self.assertTrue(transport.upload_snapshot.startswith(b"\x00\x00\x00\x18ftyp"))

        third = await publisher.publish(self.request)
        self.assertEqual((third.status, store.value.phase), ("VERIFY_PENDING", "PUBLISH_ACCEPTED"))
        self.assertEqual(transport.calls.count("finish"), 1)
        self.assertEqual(transport.calls.count("reel"), 0)

        transport.remote_status = status(
            store.value, FacebookVideoState.READY, published=True,
        )
        fourth = await publisher.publish(self.request)
        self.assertEqual(fourth.status, "PUBLISHED")
        self.assertEqual(fourth.remote_url, "https://www.facebook.com/reel/12345")
        self.assertEqual(transport.calls.count("reel"), 1)

    async def test_each_lost_mutation_response_is_ambiguous_and_not_retried(self) -> None:
        for phase, failure, expected in (
            ("CLAIMED", "start", "START_RESERVED"),
            ("SESSION_CREATED", "upload", "UPLOAD_RESERVED"),
            ("VIDEO_READY", "finish", "PUBLISH_RESERVED"),
        ):
            with self.subTest(failure=failure):
                base = self.claim
                if phase != "CLAIMED":
                    base = replace(
                        base, status="UPLOAD_STARTED" if phase == "SESSION_CREATED" else "PROCESSING",
                        phase=phase, remote_video_id="video-1",
                        upload_session_ref="secretref://meta/upload/session-1",
                    )
                store, transport = Store(base), Transport(base)
                transport.failure_at = failure
                publisher = FacebookPublisher(
                    storage_root=self.root, store=store, transport=transport,
                    policy=FacebookPolicy(enabled=True),
                )
                with self.assertRaises(FacebookError) as raised:
                    await publisher.publish(self.request)
                self.assertTrue(raised.exception.ambiguous)
                self.assertEqual(store.value.phase, expected)
                with self.assertRaises(FacebookError):
                    await publisher.publish(self.request)
                self.assertEqual(transport.calls.count(failure), 1)

    async def test_revocation_after_provider_check_blocks_mutation(self) -> None:
        publisher, store, transport = self.publisher()
        store.fail_assert_at = 2
        with self.assertRaisesRegex(FacebookError, "authorization changed"):
            await publisher.publish(self.request)
        self.assertNotIn("start", transport.calls)

    async def test_revocation_after_snapshot_blocks_binary_transfer(self) -> None:
        base = replace(
            self.claim, status="UPLOAD_STARTED", phase="SESSION_CREATED",
            remote_video_id="video-1", upload_session_ref="secretref://meta/upload/session-1",
        )
        publisher, store, transport = self.publisher(Store(base), Transport(base))
        store.fail_assert_at = 6
        with self.assertRaises(FacebookError) as raised:
            await publisher.publish(self.request)
        self.assertTrue(raised.exception.ambiguous)
        self.assertNotIn("upload", transport.calls)
        self.assertEqual(store.value.phase, "UPLOAD_RESERVED")

    async def test_authorization_requires_all_scopes_page_and_create_task(self) -> None:
        for authorization in (
            FacebookAuthorization(
                "123456", SCOPES[:-1], (FACEBOOK_CREATE_CONTENT_TASK,),
                datetime.now(timezone.utc), datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            FacebookAuthorization(
                "654321", SCOPES, (FACEBOOK_CREATE_CONTENT_TASK,),
                datetime.now(timezone.utc), datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            FacebookAuthorization(
                "123456", SCOPES, ("MODERATE",),
                datetime.now(timezone.utc), datetime.now(timezone.utc) + timedelta(hours=1),
            ),
        ):
            with self.subTest(authorization=authorization):
                publisher, _, transport = self.publisher()
                transport.authorization = authorization
                with self.assertRaisesRegex(FacebookError, "not ready"):
                    await publisher.publish(self.request)
                self.assertNotIn("start", transport.calls)

    async def test_remote_identity_and_byte_mismatch_fail_closed(self) -> None:
        base = replace(
            self.claim, status="PROCESSING", phase="UPLOAD_ACCEPTED",
            remote_video_id="video-1", upload_session_ref="secretref://meta/upload/session-1",
        )
        publisher, _, transport = self.publisher(Store(base), Transport(base))
        transport.remote_status = replace(status(base, FacebookVideoState.READY), page_id="654321")
        with self.assertRaisesRegex(FacebookError, "evidence is invalid"):
            await publisher.publish(self.request)

        publisher, _, transport = self.publisher(Store(base), Transport(base))
        transport.remote_status = replace(
            status(base, FacebookVideoState.READY), bytes_transferred=base.asset_size_bytes - 1,
        )
        with self.assertRaisesRegex(FacebookError, "uploaded bytes"):
            await publisher.publish(self.request)

    async def test_verification_bound_is_persistent(self) -> None:
        base = replace(
            self.claim, status="VERIFY_PENDING", phase="PUBLISH_ACCEPTED",
            remote_video_id="video-1", upload_session_ref="secretref://meta/upload/session-1",
            remote_post_id="post-1", verification_attempt_count=2,
        )
        publisher, _, transport = self.publisher(
            Store(base), Transport(base), maximum_verification_attempts=2,
        )
        with self.assertRaisesRegex(FacebookError, "limit"):
            await publisher.publish(self.request)
        self.assertNotIn("status", transport.calls)

    async def test_remote_publish_without_local_receipt_requires_recovery(self) -> None:
        base = replace(
            self.claim, status="PROCESSING", phase="VIDEO_READY",
            remote_video_id="video-1", upload_session_ref="secretref://meta/upload/session-1",
        )
        publisher, store, transport = self.publisher(Store(base), Transport(base))
        transport.remote_status = status(base, FacebookVideoState.READY, published=True)
        with self.assertRaises(FacebookError) as raised:
            await publisher.publish(self.request)
        self.assertTrue(raised.exception.ambiguous)
        self.assertEqual(store.value.phase, "VIDEO_READY")
        self.assertNotIn("finish", transport.calls)
        self.assertEqual(store.errors[-1].code, "PUBLISH_RECEIPT_UNKNOWN")

    async def test_remote_error_after_publish_becomes_terminal(self) -> None:
        base = replace(
            self.claim, status="VERIFY_PENDING", phase="PUBLISH_ACCEPTED",
            remote_video_id="video-1", upload_session_ref="secretref://meta/upload/session-1",
            remote_post_id="post-1",
        )
        publisher, store, transport = self.publisher(Store(base), Transport(base))
        transport.remote_status = FacebookVideoStatus(
            "video-1", base.page_id, FacebookVideoState.ERROR,
            "completed", "error", "error", "error",
            base.asset_size_bytes, base.asset_size_bytes,
        )
        result = await publisher.publish(self.request)
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(store.value.phase, "FAILED")
        self.assertNotIn("reel", transport.calls)

    async def test_terminal_replay_does_not_require_current_authorization(self) -> None:
        base = replace(
            self.claim, status="PUBLISHED", phase="VERIFIED",
            remote_video_id="video-1", upload_session_ref="secretref://meta/upload/session-1",
            remote_post_id="post-1", remote_url="https://www.facebook.com/reel/12345",
        )
        publisher, store, transport = self.publisher(Store(base), Transport(base))
        store.fail_assert_at = 1
        result = await publisher.publish(self.request)
        self.assertEqual(result.status, "PUBLISHED")
        self.assertEqual(transport.calls, [])

    async def test_recovery_and_cancellation_are_store_only(self) -> None:
        base = replace(self.claim, status="UPLOAD_STARTED", phase="START_RESERVED")
        publisher, store, transport = self.publisher(Store(base), Transport(base))
        recovered = await publisher.recover_session(
            request=self.request,
            session=FacebookUploadSession("video-1", "secretref://meta/upload/session-1"),
        )
        self.assertEqual(recovered.phase, "SESSION_CREATED")
        store.value = replace(recovered, status="PROCESSING", phase="UPLOAD_RESERVED")
        cancelled = await publisher.cancel_unknown(request=self.request, reason="operator confirmed no upload")
        self.assertEqual(cancelled.status, "CANCELLED")
        self.assertEqual(transport.calls, [])

    def test_request_and_remote_models_reject_unsafe_values(self) -> None:
        with self.assertRaises(ValueError):
            replace(self.request, description="bad\ntext")
        with self.assertRaises(ValueError):
            FacebookUploadSession("video-1", "https://rupload.facebook.com/raw")
        with self.assertRaises(ValueError):
            FacebookRemoteReel("video-1", "123456", "post-1", "https://evil.example/x", True)


if __name__ == "__main__":
    unittest.main()
