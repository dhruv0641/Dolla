from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import unittest
from uuid import uuid4

from flowx_os.db.content import OwnedContentNotFound
from flowx_os.db.youtube_publications import (
    YouTubePublicationNotAllowed,
    YouTubePublicationRepository,
)
from flowx_os.publishing.youtube import (
    YouTubePrivacy,
    YouTubePublishRequest,
    YouTubeRemoteVideo,
    YouTubeUploadOutcome,
    YouTubeUploadSession,
    YouTubeUploadState,
)


NOW = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)


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
    return YouTubePublishRequest(
        request_id=uuid4(), publication_id=uuid4(), brand_id=uuid4(),
        content_id=uuid4(), channel_id=uuid4(), asset_id=uuid4(),
        owner_user_id="owner-1", artifact_version=3,
        title="Approved vertical video", description="Reviewed description.",
    )


def claim_row(request, *, status="DRAFT", session=None, upload_id=None, video_id=None):
    data = b"approved-video"
    destination_fingerprint = hashlib.sha256(
        b"UC_verified_channel|secretref://os/youtube-owner-1"
    ).hexdigest()
    return (
        request.publication_id, request.fingerprint, request.brand_id,
        request.owner_user_id, request.content_id, request.channel_id,
        request.asset_id, uuid4(), request.artifact_version,
        "UC_verified_channel", "secretref://os/youtube-owner-1",
        destination_fingerprint,
        f"managed://assets/{request.asset_id.hex}/payload",
        hashlib.sha256(data).hexdigest(), len(data), "video/mp4",
        request.privacy_status.value, status, session, upload_id, video_id,
    )


def eligible_evidence(request, **changes):
    values = {
        "kind": "EXPORT_VARIANT", "retention": "ACTIVE",
        "storage_uri": f"managed://assets/{request.asset_id.hex}/payload",
        "sha256_hex": hashlib.sha256(b"approved-video").hexdigest(),
        "mime_type": "video/mp4", "size_bytes": len(b"approved-video"),
        "media": {
            "export_profile_id": "YOUTUBE_SHORTS_V1", "platform": "YOUTUBE",
            "publishing_performed": False,
        },
        "profile_id": "YOUTUBE_SHORTS_V1", "render_version": request.artifact_version,
        "approval_id": uuid4(), "decision": "APPROVE", "platform": "YOUTUBE",
        "external_channel_id": "UC_verified_channel",
        "credentials_ref": "secretref://os/youtube-owner-1",
        "permissions": "VALID", "enabled": True,
    }
    values.update(changes)
    return (
        values["kind"], values["retention"], values["storage_uri"],
        values["sha256_hex"], values["mime_type"], values["size_bytes"],
        values["media"], values["profile_id"], values["render_version"],
        values["approval_id"], values["decision"], values["platform"],
        values["external_channel_id"], values["credentials_ref"],
        values["permissions"], values["enabled"],
    )


class YouTubePublicationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_locks_owner_and_binds_exact_approved_export(self):
        request = publication_request()
        evidence = eligible_evidence(request)
        row = claim_row(request)
        connection = FakeConnection([
            ("READY",), None, evidence, (request.publication_id,), row,
        ])
        claim = await YouTubePublicationRepository(FakePool(connection)).claim(request)
        self.assertEqual(claim.request_fingerprint, request.fingerprint)
        self.assertEqual(claim.brand_id, request.brand_id)
        self.assertIn("FOR UPDATE OF c", connection.calls[0][0])
        self.assertIn("rd.decision = 'APPROVE'", connection.calls[2][0])
        self.assertIn("rja.profile_id", connection.calls[2][0])
        self.assertIn("INSERT INTO publication_jobs", connection.calls[3][0])

    async def test_foreign_content_is_concealed_before_evidence(self):
        request = publication_request()
        connection = FakeConnection([None])
        with self.assertRaises(OwnedContentNotFound):
            await YouTubePublicationRepository(FakePool(connection)).claim(request)
        self.assertEqual(len(connection.calls), 1)

    async def test_not_ready_or_ineligible_channel_fails_closed(self):
        request = publication_request()
        with self.subTest(reason="not-ready"):
            connection = FakeConnection([("NEEDS_REVIEW",), None])
            with self.assertRaises(YouTubePublicationNotAllowed):
                await YouTubePublicationRepository(FakePool(connection)).claim(request)
        with self.subTest(reason="disabled-channel"):
            connection = FakeConnection([
                ("READY",), None, eligible_evidence(request, enabled=False),
            ])
            with self.assertRaises(YouTubePublicationNotAllowed):
                await YouTubePublicationRepository(FakePool(connection)).claim(request)
            self.assertFalse(any("INSERT INTO publication_jobs" in call[0] for call in connection.calls))

    async def test_existing_claim_replays_before_current_ready_state(self):
        request = publication_request()
        row = claim_row(request, status="UPLOAD_STARTED",
                        session="secretref://runtime/session-1", upload_id="upload_1")
        connection = FakeConnection([("SCHEDULED",), row])
        claim = await YouTubePublicationRepository(FakePool(connection)).claim(request)
        self.assertEqual(claim.status, "UPLOAD_STARTED")
        self.assertEqual(len(connection.calls), 2)

    async def test_terminal_history_replays_without_current_channel_readiness(self):
        request = publication_request()
        row = claim_row(
            request, status="PUBLISHED", session="secretref://runtime/session-1",
            upload_id="upload_1", video_id="video_1",
        )
        connection = FakeConnection([("PUBLISHED",), row])
        claim = await YouTubePublicationRepository(FakePool(connection)).claim(request)
        self.assertEqual(claim.status, "PUBLISHED")
        self.assertFalse(any("ch.enabled = true" in query for query, _ in connection.calls))

    async def test_session_and_upload_updates_lock_exact_owned_claim(self):
        request = publication_request()
        initial = YouTubePublicationRepository._claim(claim_row(request))
        session = YouTubeUploadSession("secretref://runtime/session-1", "upload_1")
        session_row = claim_row(
            request, status="UPLOAD_STARTED", session=session.session_ref,
            upload_id=session.upload_id,
        )
        connection = FakeConnection([("DRAFT",), (request.publication_id,), session_row])
        repository = YouTubePublicationRepository(FakePool(connection))
        updated = await repository.record_session(claim=initial, session=session)
        self.assertEqual(updated.status, "UPLOAD_STARTED")
        self.assertIn("b.owner_user_id = %s", connection.calls[0][0])

        outcome = YouTubeUploadOutcome(YouTubeUploadState.COMPLETE, initial.asset_size_bytes, "video_1")
        processing_row = claim_row(
            request, status="PROCESSING", session=session.session_ref,
            upload_id=session.upload_id, video_id="video_1",
        )
        connection = FakeConnection([("UPLOAD_STARTED",), (request.publication_id,), processing_row])
        repository = YouTubePublicationRepository(FakePool(connection))
        processed = await repository.record_upload(claim=updated, outcome=outcome)
        self.assertEqual(processed.remote_video_id, "video_1")
        self.assertIn("uploaded_bytes", connection.calls[1][0])

    async def test_start_reservation_is_atomic_and_destination_is_rechecked(self):
        request = publication_request()
        initial = YouTubePublicationRepository._claim(claim_row(request))
        requested_row = claim_row(request, status="PUBLISH_REQUESTED")
        connection = FakeConnection([("DRAFT",), (request.publication_id,), requested_row])
        repository = YouTubePublicationRepository(FakePool(connection))
        reserved = await repository.reserve_start(initial)
        self.assertEqual(reserved.status, "PUBLISH_REQUESTED")
        self.assertIn("status = 'DRAFT'", connection.calls[1][0])

        connection = FakeConnection([(1,)])
        await YouTubePublicationRepository(FakePool(connection)).assert_network_ready(reserved)
        query = connection.calls[0][0]
        self.assertIn("channel_external_id_snapshot", query)
        self.assertIn("credentials_ref_snapshot", query)
        self.assertIn("JOIN publication_delivery_reservations AS dr", query)
        self.assertIn("JOIN publication_delivery_approvals AS da", query)
        self.assertIn("dr.scheduled_at_utc <= now()", query)
        self.assertIn("pr.requires_human_review = true", query)

    async def test_operator_recovery_and_cancellation_are_owner_scoped(self):
        request = publication_request()
        unknown_row = claim_row(request, status="VERIFY_PENDING")
        recovered_row = claim_row(
            request, status="UPLOAD_STARTED", session="secretref://runtime/recovered",
            upload_id="upload_recovered",
        )
        connection = FakeConnection([
            unknown_row, (request.publication_id,), recovered_row,
        ])
        repository = YouTubePublicationRepository(FakePool(connection))
        recovered = await repository.recover_unknown_session(
            request=request,
            session=YouTubeUploadSession("secretref://runtime/recovered", "upload_recovered"),
        )
        self.assertEqual(recovered.status, "UPLOAD_STARTED")

        connection = FakeConnection([
            unknown_row,
            (request.publication_id, "CANCELLED", None, None),
        ])
        cancelled = await YouTubePublicationRepository(FakePool(connection)).cancel_unknown(
            request=request, reason="Operator verified no usable remote session.",
        )
        self.assertEqual(cancelled.status, "CANCELLED")

    async def test_remote_verification_persists_bounded_canonical_evidence(self):
        request = publication_request()
        claim = YouTubePublicationRepository._claim(claim_row(
            request, status="PROCESSING", session="secretref://runtime/session-1",
            upload_id="upload_1", video_id="video_1",
        ))
        remote = YouTubeRemoteVideo(
            "video_1", "UC_verified_channel", "processed", "succeeded",
            YouTubePrivacy.PRIVATE,
        )
        connection = FakeConnection([
            ("PROCESSING",),
            (request.publication_id, "PUBLISHED", "video_1",
             "https://www.youtube.com/watch?v=video_1"),
        ])
        result = await YouTubePublicationRepository(FakePool(connection)).record_verification(
            claim=claim, remote=remote, status="PUBLISHED",
        )
        self.assertEqual(result.status, "PUBLISHED")
        query, params = connection.calls[1]
        self.assertIn("last_remote_status", query)
        self.assertIn('"processing_status":"succeeded"', params[3])
        self.assertNotIn("credentials_ref", params[3])


if __name__ == "__main__":
    unittest.main()
