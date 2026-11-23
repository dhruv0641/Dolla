from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import unittest
from uuid import uuid4

from flowx_os.community.comments import (
    CommentIngestionRequest,
    CommentIngestionAbandonment,
    CommentReadAuthorization,
    CommentState,
    ProviderComment,
    ProviderCommentBatch,
    YOUTUBE_COMMENT_READ_SCOPE,
)
from flowx_os.db.comments import (
    CommentIngestionConflict,
    CommentIngestionRepository,
)
from flowx_os.publishing.reconciliation import PublicationPlatform


NOW = datetime.now(timezone.utc)


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
        self.value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.value


def make_request(page_index=1):
    return CommentIngestionRequest(uuid4(), uuid4(), uuid4(), "owner-1", page_index)


def target_row(request):
    destination = "channel_1"
    credentials = "secretref://os/youtube-owner-1"
    return (
        request.publication_id,
        request.owner_user_id,
        "YOUTUBE",
        3,
        "a" * 64,
        uuid4(),
        destination,
        credentials,
        hashlib.sha256(f"{destination}|{credentials}".encode()).hexdigest(),
        "video_1",
        "https://www.youtube.com/watch?v=video_1",
        uuid4(),
        "b" * 64,
        "c" * 64,
        NOW,
    )


def provider_batch(request, target):
    authorization = make_authorization(target)
    comment = ProviderComment(
        remote_comment_id="comment_1",
        parent_remote_comment_id=None,
        author_external_id="provider-author-1",
        text="Untrusted but bounded first-party comment.",
        state=CommentState.ACTIVE,
        published_at=NOW,
        provider_updated_at=NOW,
    )
    return ProviderCommentBatch(
        request_id=request.request_id,
        sync_id=request.sync_id,
        publication_id=request.publication_id,
        platform=target.platform,
        destination_id=target.destination_id,
        remote_object_id=target.remote_object_id,
        page_index=request.page_index,
        cursor_fingerprint=target.cursor_fingerprint,
        comments=(comment,),
        has_more=False,
        next_cursor=None,
        observed_at=NOW,
        evidence_id="youtube:comments:etag-1",
        authorization_fingerprint=authorization.fingerprint,
    )


def make_authorization(target):
    return CommentReadAuthorization(
        platform=target.platform,
        destination_id=target.destination_id,
        granted_scopes=(YOUTUBE_COMMENT_READ_SCOPE,),
        checked_at=NOW,
        valid_until=NOW + timedelta(hours=1),
    )


def stored_row(request, target, batch):
    authorization = make_authorization(target)
    return (
        request.request_id,
        request.sync_id,
        request.publication_id,
        "YOUTUBE",
        target.destination_id,
        target.remote_object_id,
        request.page_index,
        target.fingerprint,
        batch.fingerprint,
        target.cursor_fingerprint,
        batch.next_cursor_fingerprint,
        len(batch.comments),
        batch.has_more,
        batch.evidence_id,
        batch.observed_at,
        NOW,
        authorization.fingerprint,
        list(authorization.granted_scopes),
        authorization.checked_at,
        authorization.valid_until,
    )


class CommentIngestionRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_reserve_requires_owner_current_permission_and_verified_publication(self):
        request = make_request()
        row = target_row(request)
        connection = FakeConnection([
            row,
            None,
            None,
            (request.sync_id,),
            None,
            None,
            (request.request_id,),
        ])
        target = await CommentIngestionRepository(FakePool(connection)).reserve(
            request,
            maximum_pages=100,
            maximum_reconciliation_age_seconds=3_600,
            maximum_provider_attempts=3,
            reservation_lease_seconds=120,
        )
        query, params = connection.calls[0]
        self.assertEqual(params, (request.publication_id, request.owner_user_id))
        self.assertIn("p.status = 'PUBLISHED'", query)
        self.assertIn("ch.enabled = true", query)
        self.assertIn("ch.permissions_status = 'VALID'", query)
        self.assertIn("publication_reconciliations", query)
        self.assertIn("verdict = 'IN_SYNC'", query)
        self.assertIn("ORDER BY observed_at DESC, request_id DESC", query)
        self.assertIn("latest.request_id = r.request_id", query)
        self.assertEqual(target.reconciliation_request_id, row[11])
        self.assertIn("comment_ingestion_attempts", connection.calls[-1][0])

    async def test_reserved_request_is_not_read_from_provider_again(self):
        request = make_request()
        row = target_row(request)
        target = CommentIngestionRepository._target(
            row, request=request, page_index=1, page_cursor=None,
            reservation_generation=1,
        )
        run = (
            request.publication_id,
            request.owner_user_id,
            "YOUTUBE",
            target.fingerprint,
            target.reconciliation_request_id,
            0,
            None,
            "ACTIVE",
        )
        attempt = (
            request.sync_id,
            request.publication_id,
            request.owner_user_id,
            target.fingerprint,
            1,
            target.cursor_fingerprint,
            "RESERVED",
            1,
            False,
        )
        connection = FakeConnection([row, run, attempt])
        with self.assertRaisesRegex(RuntimeError, "still leased"):
            await CommentIngestionRepository(FakePool(connection)).reserve(
                request,
                maximum_pages=100,
                maximum_reconciliation_age_seconds=3_600,
                maximum_provider_attempts=3,
                reservation_lease_seconds=120,
            )

    async def test_stale_reconciliation_is_rejected_before_reservation(self):
        request = make_request()
        row = list(target_row(request))
        row[14] = NOW - timedelta(hours=2)
        connection = FakeConnection([tuple(row)])
        with self.assertRaisesRegex(RuntimeError, "allowed time window"):
            await CommentIngestionRepository(FakePool(connection)).reserve(
                request,
                maximum_pages=100,
                maximum_reconciliation_age_seconds=3_600,
                maximum_provider_attempts=3,
                reservation_lease_seconds=120,
            )
        self.assertEqual(len(connection.calls), 1)
        self.assertFalse(any(
            "INSERT INTO comment_ingestion" in query for query, _ in connection.calls
        ))

    async def test_stale_worker_generation_is_fenced_from_network_failure_and_record(self):
        request = make_request()
        row = target_row(request)
        stale = CommentIngestionRepository._target(
            row, request=request, page_index=1, page_cursor=None,
            reservation_generation=1,
        )
        connection = FakeConnection([row, None])
        with self.assertRaises(CommentIngestionConflict):
            await CommentIngestionRepository(FakePool(connection)).assert_network_ready(stale)
        self.assertIn("attempt_count = %s", connection.calls[1][0])
        self.assertEqual(connection.calls[1][1][-1], 1)

        connection = FakeConnection([None])
        with self.assertRaises(CommentIngestionConflict):
            await CommentIngestionRepository(FakePool(connection)).record_failure(
                request=request, target=stale, error_code="PROVIDER_UNAVAILABLE",
            )
        self.assertIn("attempt_count = %s", connection.calls[0][0])
        self.assertEqual(connection.calls[0][1][-1], 1)

        batch = provider_batch(request, stale)
        run = (
            request.publication_id, request.owner_user_id, "YOUTUBE",
            stale.fingerprint, stale.reconciliation_request_id, 0, None, "ACTIVE",
        )
        replacement_attempt = (
            request.sync_id, request.publication_id, request.owner_user_id,
            stale.fingerprint, 1, stale.cursor_fingerprint, "RESERVED", 2, True,
        )
        connection = FakeConnection([None, row, run, replacement_attempt])
        with self.assertRaises(CommentIngestionConflict):
            await CommentIngestionRepository(FakePool(connection)).record(
                request=request,
                target=stale,
                batch=batch,
                authorization=make_authorization(stale),
            )
        self.assertFalse(any(
            "INSERT INTO comment_ingestion_batches" in query
            for query, _ in connection.calls
        ))

    async def test_expired_read_lease_retries_exact_request_and_abandons_at_bound(self):
        request = make_request()
        row = target_row(request)
        target = CommentIngestionRepository._target(
            row, request=request, page_index=1, page_cursor=None,
            reservation_generation=1,
        )
        run = (
            request.publication_id,
            request.owner_user_id,
            "YOUTUBE",
            target.fingerprint,
            target.reconciliation_request_id,
            0,
            None,
            "ACTIVE",
        )
        retry_attempt = (
            request.sync_id,
            request.publication_id,
            request.owner_user_id,
            target.fingerprint,
            1,
            target.cursor_fingerprint,
            "RESERVED",
            1,
            True,
        )
        connection = FakeConnection([row, run, retry_attempt, (request.request_id,)])
        retried = await CommentIngestionRepository(FakePool(connection)).reserve(
            request,
            maximum_pages=100,
            maximum_reconciliation_age_seconds=3_600,
            maximum_provider_attempts=3,
            reservation_lease_seconds=120,
        )
        self.assertEqual(retried, replace(target, reservation_generation=2))
        self.assertIn("attempt_count = attempt_count + 1", connection.calls[-1][0])

        terminal_attempt = retry_attempt[:-2] + (3, True)
        connection = FakeConnection([
            row,
            run,
            terminal_attempt,
            (request.request_id,),
            (request.sync_id,),
        ])
        terminal = await CommentIngestionRepository(FakePool(connection)).reserve(
            request,
            maximum_pages=100,
            maximum_reconciliation_age_seconds=3_600,
            maximum_provider_attempts=3,
            reservation_lease_seconds=120,
        )
        self.assertIsInstance(terminal, CommentIngestionAbandonment)
        self.assertTrue(any("status = 'ABANDONED'" in query for query, _ in connection.calls))

    async def test_record_persists_minimized_version_and_advances_run(self):
        request = make_request()
        row = target_row(request)
        target = CommentIngestionRepository._target(
            row, request=request, page_index=1, page_cursor=None,
            reservation_generation=1,
        )
        batch = provider_batch(request, target)
        run = (
            request.publication_id,
            request.owner_user_id,
            "YOUTUBE",
            target.fingerprint,
            target.reconciliation_request_id,
            0,
            None,
            "ACTIVE",
        )
        attempt = (
            request.sync_id,
            request.publication_id,
            request.owner_user_id,
            target.fingerprint,
            1,
            target.cursor_fingerprint,
            "RESERVED",
            1,
            True,
        )
        returned = stored_row(request, target, batch)
        version_id = uuid4()
        connection = FakeConnection([
            None,
            row,
            run,
            attempt,
            returned,
            None,
            (version_id,),
            (request.request_id,),
            (request.sync_id,),
            (request.request_id,),
        ])
        result = await CommentIngestionRepository(FakePool(connection)).record(
            request=request, target=target, batch=batch,
            authorization=make_authorization(target),
        )
        self.assertEqual(result.batch_fingerprint, batch.fingerprint)
        version_call = next(
            call for call in connection.calls
            if "INSERT INTO community_comment_versions" in call[0]
        )
        self.assertNotIn("provider-author-1", version_call[1])
        self.assertIn(batch.comments[0].author_external_id_hash, version_call[1])
        self.assertTrue(any(
            "UPDATE comment_ingestion_runs" in query for query, _ in connection.calls
        ))
        self.assertTrue(any(
            "UPDATE comment_ingestion_attempts" in query for query, _ in connection.calls
        ))

    async def test_record_rechecks_exact_target_before_writes(self):
        request = make_request()
        row = target_row(request)
        target = CommentIngestionRepository._target(
            row, request=request, page_index=1, page_cursor=None,
            reservation_generation=1,
        )
        batch = provider_batch(request, target)
        changed = list(row)
        changed[3] = 4
        connection = FakeConnection([None, tuple(changed)])
        with self.assertRaises(CommentIngestionConflict):
            await CommentIngestionRepository(FakePool(connection)).record(
                request=request, target=target, batch=batch,
                authorization=make_authorization(target),
            )
        self.assertFalse(any(
            "INSERT INTO comment_ingestion_batches" in query
            for query, _ in connection.calls
        ))

    async def test_exact_overlapping_comment_version_is_linked_without_reinsert(self):
        request = make_request()
        row = target_row(request)
        target = CommentIngestionRepository._target(
            row, request=request, page_index=1, page_cursor=None,
            reservation_generation=1,
        )
        batch = provider_batch(request, target)
        run = (
            request.publication_id,
            request.owner_user_id,
            "YOUTUBE",
            target.fingerprint,
            target.reconciliation_request_id,
            0,
            None,
            "ACTIVE",
        )
        attempt = (
            request.sync_id,
            request.publication_id,
            request.owner_user_id,
            target.fingerprint,
            1,
            target.cursor_fingerprint,
            "RESERVED",
            1,
            True,
        )
        version_id = uuid4()
        connection = FakeConnection([
            None,
            row,
            run,
            attempt,
            stored_row(request, target, batch),
            (version_id,),
            (request.request_id,),
            (request.sync_id,),
            (request.request_id,),
        ])
        result = await CommentIngestionRepository(FakePool(connection)).record(
            request=request,
            target=target,
            batch=batch,
            authorization=make_authorization(target),
        )
        self.assertEqual(result.batch_fingerprint, batch.fingerprint)
        self.assertFalse(any(
            "INSERT INTO community_comment_versions" in query
            for query, _ in connection.calls
        ))
        self.assertTrue(any(
            "INSERT INTO comment_ingestion_batch_items" in query
            for query, _ in connection.calls
        ))

    async def test_get_existing_is_owner_scoped(self):
        request = make_request()
        row = target_row(request)
        target = CommentIngestionRepository._target(
            row, request=request, page_index=1, page_cursor=None,
            reservation_generation=1,
        )
        batch = provider_batch(request, target)
        connection = FakeConnection([stored_row(request, target, batch)])
        result = await CommentIngestionRepository(FakePool(connection)).get_existing(request)
        self.assertEqual(result.request_id, request.request_id)
        self.assertEqual(connection.calls[0][1], (request.request_id, request.owner_user_id))

    async def test_repository_rejects_forged_batch_before_sql(self):
        request = make_request()
        other = make_request()
        row = target_row(request)
        target = CommentIngestionRepository._target(
            row, request=request, page_index=1, page_cursor=None,
            reservation_generation=1,
        )
        forged = provider_batch(other, CommentIngestionRepository._target(
            target_row(other), request=other, page_index=1, page_cursor=None,
            reservation_generation=1,
        ))
        connection = FakeConnection()
        with self.assertRaises(ValueError):
            await CommentIngestionRepository(FakePool(connection)).record(
                request=request, target=target, batch=forged,
                authorization=make_authorization(target),
            )
        self.assertEqual(connection.calls, [])


if __name__ == "__main__":
    unittest.main()

