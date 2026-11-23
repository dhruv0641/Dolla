from contextlib import asynccontextmanager
import hashlib
import json
import unittest
from uuid import uuid4

from flowx_os.db.content import OwnedContentNotFound
from flowx_os.db.facebook_publications import (
    FacebookPublicationNotAllowed,
    FacebookPublicationRepository,
)
from flowx_os.publishing.facebook import (
    FacebookError,
    FacebookPublishReceipt,
    FacebookPublishRequest,
    FacebookRemoteReel,
    FacebookUploadReceipt,
    FacebookUploadSession,
    FacebookVideoState,
    FacebookVideoStatus,
)


class FakeCursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, query, params=None):
        self.calls.append((query, params))
        return FakeCursor(self.rows.pop(0) if self.rows else None)


class FakePool:
    def __init__(self, connection):
        self.connection_value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.connection_value


def publication_request():
    return FacebookPublishRequest(
        request_id=uuid4(), publication_id=uuid4(), brand_id=uuid4(),
        content_id=uuid4(), channel_id=uuid4(), asset_id=uuid4(),
        owner_user_id="owner-1", artifact_version=5,
        title="Reviewed Reel", description="Approved description",
    )


def claim_row(request, *, status="DRAFT", phase="CLAIMED", video=None,
              session=None, post=None, remote_url=None, attempts=0):
    destination = hashlib.sha256(
        b"123456|secretref://os/facebook-owner-1"
    ).hexdigest()
    data = b"approved-facebook-reel"
    return (
        request.publication_id, request.fingerprint, request.brand_id,
        request.owner_user_id, request.content_id, request.channel_id,
        request.asset_id, uuid4(), request.artifact_version,
        "123456", "secretref://os/facebook-owner-1", destination,
        f"managed://assets/{request.asset_id.hex}/payload",
        hashlib.sha256(data).hexdigest(), len(data), "video/mp4", status, phase,
        video, session, post, remote_url, attempts,
    )


def eligible_evidence(request, **changes):
    values = {
        "kind": "EXPORT_VARIANT", "retention": "ACTIVE",
        "storage_uri": f"managed://assets/{request.asset_id.hex}/payload",
        "sha256_hex": hashlib.sha256(b"approved-facebook-reel").hexdigest(),
        "mime_type": "video/mp4", "size_bytes": len(b"approved-facebook-reel"),
        "media": {
            "export_profile_id": "FACEBOOK_REELS_V1", "platform": "FACEBOOK",
            "publishing_performed": False,
        },
        "profile_id": "FACEBOOK_REELS_V1", "render_version": request.artifact_version,
        "approval_id": uuid4(), "decision": "APPROVE", "platform": "FACEBOOK",
        "external_id": "123456", "credentials_ref": "secretref://os/facebook-owner-1",
        "permissions": "VALID", "enabled": True,
    }
    values.update(changes)
    return (
        values["kind"], values["retention"], values["storage_uri"],
        values["sha256_hex"], values["mime_type"], values["size_bytes"],
        values["media"], values["profile_id"], values["render_version"],
        values["approval_id"], values["decision"], values["platform"],
        values["external_id"], values["credentials_ref"],
        values["permissions"], values["enabled"],
    )


def video_status(claim, state=FacebookVideoState.READY, *, published=False):
    completed = state == FacebookVideoState.READY
    return FacebookVideoStatus(
        claim.remote_video_id, claim.page_id, state,
        "completed" if completed else "in_progress",
        "completed" if completed else "in_progress",
        "completed" if published else "not_started",
        "published" if published else "not_started",
        claim.asset_size_bytes if completed else 0, claim.asset_size_bytes,
    )


class FacebookPublicationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_is_owner_scoped_and_binds_exact_facebook_export(self):
        request = publication_request()
        connection = FakeConnection([
            ("READY",), None, eligible_evidence(request),
            (request.publication_id,), claim_row(request),
        ])
        claim = await FacebookPublicationRepository(FakePool(connection)).claim(request)
        self.assertEqual(claim.request_fingerprint, request.fingerprint)
        self.assertEqual(claim.page_id, "123456")
        self.assertIn("FOR UPDATE OF c", connection.calls[0][0])
        self.assertIn("rd.decision = 'APPROVE'", connection.calls[2][0])
        self.assertIn("FACEBOOK_REELS_V1", connection.calls[3][0])
        metadata = json.loads(connection.calls[3][1][-1])
        self.assertEqual(metadata["video_state"], "PUBLISHED")
        self.assertTrue(metadata["is_ai_generated"])

    async def test_foreign_content_is_concealed_before_provider_evidence(self):
        request = publication_request()
        connection = FakeConnection([None])
        with self.assertRaises(OwnedContentNotFound):
            await FacebookPublicationRepository(FakePool(connection)).claim(request)
        self.assertEqual(len(connection.calls), 1)

    async def test_ineligible_page_or_export_fails_before_insert(self):
        request = publication_request()
        connection = FakeConnection([
            ("READY",), None, eligible_evidence(request, enabled=False),
        ])
        with self.assertRaises(FacebookPublicationNotAllowed):
            await FacebookPublicationRepository(FakePool(connection)).claim(request)
        self.assertFalse(any("INSERT INTO publication_jobs" in query for query, _ in connection.calls))

    async def test_start_upload_and_publish_have_distinct_atomic_barriers(self):
        request = publication_request()
        initial = FacebookPublicationRepository._claim(claim_row(request))
        start_row = claim_row(request, status="UPLOAD_STARTED", phase="START_RESERVED")
        connection = FakeConnection([("DRAFT",), (request.publication_id,), start_row])
        repository = FacebookPublicationRepository(FakePool(connection))
        start = await repository.reserve_start(initial)
        self.assertEqual(start.phase, "START_RESERVED")

        session_row = claim_row(
            request, status="UPLOAD_STARTED", phase="SESSION_CREATED",
            video="video_1", session="secretref://meta/upload/session-1",
        )
        connection = FakeConnection([("UPLOAD_STARTED",), (request.publication_id,), session_row])
        session = await FacebookPublicationRepository(FakePool(connection)).record_session(
            claim=start,
            session=FacebookUploadSession("video_1", "secretref://meta/upload/session-1"),
        )
        self.assertEqual(session.remote_video_id, "video_1")

        upload_row = claim_row(
            request, status="PROCESSING", phase="UPLOAD_RESERVED",
            video="video_1", session="secretref://meta/upload/session-1",
        )
        connection = FakeConnection([("UPLOAD_STARTED",), (request.publication_id,), upload_row])
        upload = await FacebookPublicationRepository(FakePool(connection)).reserve_upload(session)
        self.assertEqual(upload.phase, "UPLOAD_RESERVED")

        accepted_row = claim_row(
            request, status="PROCESSING", phase="UPLOAD_ACCEPTED",
            video="video_1", session="secretref://meta/upload/session-1",
        )
        connection = FakeConnection([("PROCESSING",), (request.publication_id,), accepted_row])
        accepted = await FacebookPublicationRepository(FakePool(connection)).record_upload(
            claim=upload, receipt=FacebookUploadReceipt("video_1", True),
        )
        self.assertEqual(accepted.phase, "UPLOAD_ACCEPTED")

    async def test_status_and_final_verification_store_bounded_nonsecret_proof(self):
        request = publication_request()
        processing = FacebookPublicationRepository._claim(claim_row(
            request, status="PROCESSING", phase="UPLOAD_ACCEPTED",
            video="video_1", session="secretref://meta/upload/session-1",
        ))
        ready_row = claim_row(
            request, status="PROCESSING", phase="VIDEO_READY",
            video="video_1", session="secretref://meta/upload/session-1", attempts=1,
        )
        connection = FakeConnection([("PROCESSING",), (request.publication_id,), ready_row])
        ready = await FacebookPublicationRepository(FakePool(connection)).record_video_status(
            claim=processing, remote=video_status(processing),
        )
        self.assertEqual(ready.phase, "VIDEO_READY")
        proof = connection.calls[1][1][3]
        self.assertIn('"bytes_transferred":', proof)
        self.assertNotIn("secretref", proof)

        accepted = FacebookPublicationRepository._claim(claim_row(
            request, status="VERIFY_PENDING", phase="PUBLISH_ACCEPTED",
            video="video_1", session="secretref://meta/upload/session-1", post="post_1",
        ))
        published_status = video_status(accepted, published=True)
        remote = FacebookRemoteReel(
            "video_1", "123456", "post_1",
            "https://www.facebook.com/reel/video_1", True,
        )
        connection = FakeConnection([
            ("VERIFY_PENDING",),
            (request.publication_id, "PUBLISHED", "video_1", remote.permalink),
        ])
        result = await FacebookPublicationRepository(FakePool(connection)).record_verification(
            claim=accepted, status=published_status, remote=remote,
        )
        self.assertEqual(result.status, "PUBLISHED")
        final_proof = connection.calls[1][1][2]
        self.assertIn('"page_id":"123456"', final_proof)
        self.assertIn('"published":true', final_proof)
        self.assertNotIn("credentials_ref", final_proof)

    async def test_destination_recheck_uses_current_page_and_credential_snapshot(self):
        request = publication_request()
        claim = FacebookPublicationRepository._claim(claim_row(request))
        connection = FakeConnection([(1,)])
        await FacebookPublicationRepository(FakePool(connection)).assert_network_ready(claim)
        query = connection.calls[0][0]
        self.assertIn("ch.platform = 'FACEBOOK'", query)
        self.assertIn("channel_external_id_snapshot", query)
        self.assertIn("credentials_ref_snapshot", query)
        self.assertIn("JOIN publication_delivery_reservations AS dr", query)
        self.assertIn("JOIN publication_delivery_approvals AS da", query)
        self.assertIn("dr.scheduled_at_utc <= now()", query)
        self.assertIn("dr.state = 'DISPATCH_RESERVED' OR da.valid_until > now()", query)
        self.assertIn("pr.requires_human_review = true", query)

    async def test_recovered_publish_is_owner_scoped_and_exact(self):
        request = publication_request()
        unknown = claim_row(
            request, status="PUBLISH_REQUESTED", phase="PUBLISH_RESERVED",
            video="video_1", session="secretref://meta/upload/session-1",
        )
        recovered = claim_row(
            request, status="VERIFY_PENDING", phase="PUBLISH_ACCEPTED",
            video="video_1", session="secretref://meta/upload/session-1", post="post_1",
        )
        connection = FakeConnection([
            unknown, ("PUBLISH_REQUESTED",), (request.publication_id,), recovered,
        ])
        claim = await FacebookPublicationRepository(FakePool(connection)).recover_publish(
            request=request, receipt=FacebookPublishReceipt("video_1", True, "post_1"),
        )
        self.assertEqual(claim.remote_post_id, "post_1")
        self.assertIn("b.owner_user_id = %s", connection.calls[0][0])

    async def test_pre_receipt_published_evidence_has_an_exact_recovery_path(self):
        request = publication_request()
        unknown = claim_row(
            request, status="PROCESSING", phase="VIDEO_READY",
            video="video_1", session="secretref://meta/upload/session-1",
        )
        recovered = claim_row(
            request, status="VERIFY_PENDING", phase="PUBLISH_ACCEPTED",
            video="video_1", session="secretref://meta/upload/session-1", post="post_1",
        )
        connection = FakeConnection([
            unknown, ("PROCESSING",), (request.publication_id,), recovered,
        ])
        claim = await FacebookPublicationRepository(FakePool(connection)).recover_publish(
            request=request, receipt=FacebookPublishReceipt("video_1", True, "post_1"),
        )
        self.assertEqual(claim.phase, "PUBLISH_ACCEPTED")
        recovery_query = connection.calls[2][0]
        self.assertIn("last_error_code = 'PUBLISH_RECEIPT_UNKNOWN'", recovery_query)
        self.assertIn("'UPLOAD_ACCEPTED','VIDEO_PROCESSING','VIDEO_READY'", recovery_query)

    async def test_unexpected_remote_publish_observation_advances_bound(self):
        request = publication_request()
        claim = FacebookPublicationRepository._claim(claim_row(
            request, status="PROCESSING", phase="VIDEO_READY",
            video="video_1", session="secretref://meta/upload/session-1",
        ))
        connection = FakeConnection([("PROCESSING",)])
        await FacebookPublicationRepository(FakePool(connection)).record_transport_failure(
            claim=claim,
            error=FacebookError(
                "PUBLISH_RECEIPT_UNKNOWN", "operator recovery required", ambiguous=True,
            ),
        )
        query, params = connection.calls[1]
        self.assertIn("verification_attempt_count = verification_attempt_count + %s", query)
        self.assertEqual(params[2:4], (1, True))

    async def test_recovered_session_and_upload_are_exact_and_single_winner(self):
        request = publication_request()
        unknown_start = claim_row(request, status="UPLOAD_STARTED", phase="START_RESERVED")
        session_row = claim_row(
            request, status="UPLOAD_STARTED", phase="SESSION_CREATED",
            video="video_1", session="secretref://meta/upload/session-1",
        )
        connection = FakeConnection([
            unknown_start, ("UPLOAD_STARTED",), (request.publication_id,), session_row,
        ])
        session = await FacebookPublicationRepository(FakePool(connection)).recover_session(
            request=request,
            session=FacebookUploadSession("video_1", "secretref://meta/upload/session-1"),
        )
        self.assertEqual(session.phase, "SESSION_CREATED")
        self.assertIn("facebook_phase = 'START_RESERVED'", connection.calls[2][0])

        unknown_upload = claim_row(
            request, status="PROCESSING", phase="UPLOAD_RESERVED",
            video="video_1", session="secretref://meta/upload/session-1",
        )
        recovered_upload = claim_row(
            request, status="PROCESSING", phase="UPLOAD_ACCEPTED",
            video="video_1", session="secretref://meta/upload/session-1", attempts=1,
        )
        claim = FacebookPublicationRepository._claim(unknown_upload)
        remote = video_status(claim)
        connection = FakeConnection([
            unknown_upload, ("PROCESSING",), (request.publication_id,), recovered_upload,
        ])
        recovered = await FacebookPublicationRepository(FakePool(connection)).recover_upload(
            request=request, status=remote,
        )
        self.assertEqual(recovered.phase, "UPLOAD_ACCEPTED")
        self.assertIn("facebook_phase = 'UPLOAD_RESERVED'", connection.calls[2][0])


if __name__ == "__main__":
    unittest.main()
