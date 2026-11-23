from contextlib import asynccontextmanager
import hashlib
import json
import unittest
from uuid import uuid4

from flowx_os.db.content import OwnedContentNotFound
from flowx_os.db.instagram_publications import (
    InstagramPublicationNotAllowed,
    InstagramPublicationRepository,
)
from flowx_os.publishing.instagram import (
    InstagramContainer,
    InstagramContainerState,
    InstagramContainerStatus,
    InstagramPublishedMedia,
    InstagramPublishRequest,
    InstagramRemoteMedia,
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
    return InstagramPublishRequest(
        request_id=uuid4(), publication_id=uuid4(), brand_id=uuid4(),
        content_id=uuid4(), channel_id=uuid4(), asset_id=uuid4(),
        owner_user_id="owner-1", artifact_version=4,
        media_source_ref="secretref://media/instagram/reel-1",
        caption="Reviewed Reel caption",
    )


def claim_row(request, *, status="DRAFT", phase="CLAIMED", container=None,
              media=None, remote_url=None):
    destination = hashlib.sha256(
        b"ig_professional_123|secretref://os/instagram-owner-1"
    ).hexdigest()
    data = b"approved-instagram-reel"
    return (
        request.publication_id, request.fingerprint, request.brand_id,
        request.owner_user_id, request.content_id, request.channel_id,
        request.asset_id, uuid4(), request.artifact_version,
        "ig_professional_123", "secretref://os/instagram-owner-1", destination,
        request.media_source_ref, f"managed://assets/{request.asset_id.hex}/payload",
        hashlib.sha256(data).hexdigest(), len(data), "video/mp4", status, phase,
        container, media, remote_url, 0,
    )


def eligible_evidence(request, **changes):
    values = {
        "kind": "EXPORT_VARIANT", "retention": "ACTIVE",
        "storage_uri": f"managed://assets/{request.asset_id.hex}/payload",
        "sha256_hex": hashlib.sha256(b"approved-instagram-reel").hexdigest(),
        "mime_type": "video/mp4", "size_bytes": len(b"approved-instagram-reel"),
        "media": {
            "export_profile_id": "INSTAGRAM_REELS_V1", "platform": "INSTAGRAM",
            "publishing_performed": False,
        },
        "profile_id": "INSTAGRAM_REELS_V1", "render_version": request.artifact_version,
        "approval_id": uuid4(), "decision": "APPROVE", "platform": "INSTAGRAM",
        "external_id": "ig_professional_123",
        "credentials_ref": "secretref://os/instagram-owner-1",
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


class InstagramPublicationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_is_owner_scoped_and_binds_exact_export(self):
        request = publication_request()
        connection = FakeConnection([
            ("READY",), None, eligible_evidence(request),
            (request.publication_id,), claim_row(request),
        ])
        claim = await InstagramPublicationRepository(FakePool(connection)).claim(request)
        self.assertEqual(claim.request_fingerprint, request.fingerprint)
        self.assertEqual(claim.media_source_ref, request.media_source_ref)
        self.assertIn("FOR UPDATE OF c", connection.calls[0][0])
        self.assertIn("rd.decision = 'APPROVE'", connection.calls[2][0])
        self.assertIn("INSTAGRAM_REELS_V1", connection.calls[3][0])
        metadata = json.loads(connection.calls[3][1][-1])
        self.assertEqual(metadata["media_type"], "REELS")

    async def test_foreign_content_is_concealed_before_provider_evidence(self):
        request = publication_request()
        connection = FakeConnection([None])
        with self.assertRaises(OwnedContentNotFound):
            await InstagramPublicationRepository(FakePool(connection)).claim(request)
        self.assertEqual(len(connection.calls), 1)

    async def test_not_ready_or_ineligible_channel_fails_closed(self):
        request = publication_request()
        connection = FakeConnection([("NEEDS_REVIEW",), None])
        with self.assertRaises(InstagramPublicationNotAllowed):
            await InstagramPublicationRepository(FakePool(connection)).claim(request)

        connection = FakeConnection([
            ("READY",), None, eligible_evidence(request, enabled=False),
        ])
        with self.assertRaises(InstagramPublicationNotAllowed):
            await InstagramPublicationRepository(FakePool(connection)).claim(request)
        self.assertFalse(any("INSERT INTO publication_jobs" in query for query, _ in connection.calls))

    async def test_existing_terminal_history_replays_without_channel_readiness(self):
        request = publication_request()
        row = claim_row(
            request, status="PUBLISHED", phase="VERIFIED",
            container="container_1", media="media_1",
            remote_url="https://www.instagram.com/reel/ABC_123/",
        )
        connection = FakeConnection([("PUBLISHED",), row])
        claim = await InstagramPublicationRepository(FakePool(connection)).claim(request)
        self.assertEqual(claim.status, "PUBLISHED")
        self.assertEqual(claim.remote_url, "https://www.instagram.com/reel/ABC_123/")
        self.assertEqual(len(connection.calls), 2)

    async def test_container_reservation_and_destination_recheck_are_atomic(self):
        request = publication_request()
        initial = InstagramPublicationRepository._claim(claim_row(request))
        reserved_row = claim_row(request, status="UPLOAD_STARTED", phase="CONTAINER_RESERVED")
        connection = FakeConnection([("DRAFT",), (request.publication_id,), reserved_row])
        repository = InstagramPublicationRepository(FakePool(connection))
        reserved = await repository.reserve_container(initial)
        self.assertEqual(reserved.phase, "CONTAINER_RESERVED")
        self.assertIn("status = 'DRAFT'", connection.calls[1][0])

        connection = FakeConnection([(1,)])
        await InstagramPublicationRepository(FakePool(connection)).assert_network_ready(reserved)
        query = connection.calls[0][0]
        self.assertIn("channel_external_id_snapshot", query)
        self.assertIn("credentials_ref_snapshot", query)
        self.assertIn("JOIN publication_delivery_reservations AS dr", query)
        self.assertIn("JOIN publication_delivery_approvals AS da", query)
        self.assertIn("dr.scheduled_at_utc <= now()", query)
        self.assertIn("pr.requires_human_review = true", query)

    async def test_container_and_publish_identities_have_separate_barriers(self):
        request = publication_request()
        initial = InstagramPublicationRepository._claim(
            claim_row(request, status="UPLOAD_STARTED", phase="CONTAINER_RESERVED")
        )
        created_row = claim_row(
            request, status="PROCESSING", phase="CONTAINER_CREATED", container="container_1",
        )
        connection = FakeConnection([
            ("UPLOAD_STARTED",), (request.publication_id,), created_row,
        ])
        repository = InstagramPublicationRepository(FakePool(connection))
        created = await repository.record_container(
            claim=initial, container=InstagramContainer("container_1"),
        )
        self.assertEqual(created.remote_container_id, "container_1")

        ready_row = claim_row(
            request, status="PROCESSING", phase="CONTAINER_READY", container="container_1",
        )
        connection = FakeConnection([
            ("PROCESSING",), (request.publication_id,), ready_row,
        ])
        ready = await InstagramPublicationRepository(FakePool(connection)).record_container_status(
            claim=created,
            remote=InstagramContainerStatus("container_1", InstagramContainerState.FINISHED),
        )
        self.assertEqual(ready.phase, "CONTAINER_READY")

        reserved_row = claim_row(
            request, status="PUBLISH_REQUESTED", phase="PUBLISH_RESERVED",
            container="container_1",
        )
        connection = FakeConnection([
            ("PROCESSING",), (request.publication_id,), reserved_row,
        ])
        reserved = await InstagramPublicationRepository(FakePool(connection)).reserve_publish(ready)
        self.assertEqual(reserved.phase, "PUBLISH_RESERVED")
        self.assertIn("CONTAINER_READY", connection.calls[1][0])

        media_row = claim_row(
            request, status="VERIFY_PENDING", phase="MEDIA_RECORDED",
            container="container_1", media="media_1",
        )
        connection = FakeConnection([
            ("PUBLISH_REQUESTED",), (request.publication_id,), media_row,
        ])
        media = await InstagramPublicationRepository(FakePool(connection)).record_media(
            claim=reserved, media=InstagramPublishedMedia("media_1"),
        )
        self.assertEqual(media.remote_media_id, "media_1")

    async def test_operator_recovery_is_owner_scoped(self):
        request = publication_request()
        unknown = claim_row(request, status="UPLOAD_STARTED", phase="CONTAINER_RESERVED")
        recovered = claim_row(
            request, status="PROCESSING", phase="CONTAINER_CREATED", container="container_recovered",
        )
        connection = FakeConnection([unknown, (request.publication_id,), recovered])
        claim = await InstagramPublicationRepository(FakePool(connection)).recover_container(
            request=request, container=InstagramContainer("container_recovered"),
        )
        self.assertEqual(claim.remote_container_id, "container_recovered")
        self.assertIn("b.owner_user_id = %s", connection.calls[0][0])

    async def test_final_verification_persists_canonical_nonsecret_proof(self):
        request = publication_request()
        claim = InstagramPublicationRepository._claim(claim_row(
            request, status="VERIFY_PENDING", phase="MEDIA_RECORDED",
            container="container_1", media="media_1",
        ))
        container = InstagramContainerStatus("container_1", InstagramContainerState.PUBLISHED)
        media = InstagramRemoteMedia(
            "media_1", "ig_professional_123", "VIDEO",
            "https://www.instagram.com/reel/ABC_123/",
        )
        connection = FakeConnection([
            ("VERIFY_PENDING",),
            (request.publication_id, "PUBLISHED", "media_1", media.permalink),
        ])
        result = await InstagramPublicationRepository(FakePool(connection)).record_verification(
            claim=claim, container=container, media=media,
        )
        self.assertEqual(result.status, "PUBLISHED")
        proof = connection.calls[1][1][1]
        self.assertIn('"container_status":"PUBLISHED"', proof)
        self.assertIn('"owner_id":"ig_professional_123"', proof)
        self.assertNotIn("credentials_ref", proof)


if __name__ == "__main__":
    unittest.main()
