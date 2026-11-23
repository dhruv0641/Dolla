from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import unittest
from uuid import uuid4

from flowx_os.db.publication_reconciliation import (
    PublicationReconciliationConflict,
    PublicationReconciliationRepository,
)
from flowx_os.publishing.reconciliation import (
    PlatformPublicationObservation,
    PlatformReconciliationRequest,
    PublicationPlatform,
    ReconciliationVerdict,
    RemotePublicationState,
    PlatformReconciliationError,
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
        self.value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.value


def request():
    return PlatformReconciliationRequest(uuid4(), uuid4(), "owner-1")


def target_row(value, *, status="PUBLISHED", version=3, remote="video_1"):
    destination = "channel_1"
    credentials = "secretref://os/youtube-owner-1"
    return (
        value.publication_id, value.owner_user_id, "YOUTUBE", status, version,
        "a" * 64, uuid4(), destination, credentials,
        hashlib.sha256(f"{destination}|{credentials}".encode()).hexdigest(),
        remote, None if remote is None else f"https://www.youtube.com/watch?v={remote}",
    )


def observation(value, target):
    return PlatformPublicationObservation(
        request_id=value.request_id,
        publication_id=value.publication_id,
        platform=PublicationPlatform.YOUTUBE,
        destination_id=target.destination_id,
        remote_object_id=target.remote_object_id,
        state=RemotePublicationState.PUBLISHED,
        observed_at=datetime.now(timezone.utc),
        evidence_id="youtube:etag:abc",
        remote_url=f"https://www.youtube.com/watch?v={target.remote_object_id}",
    )


def record_row(value, target, remote, *, verdict="IN_SYNC"):
    now = datetime.now(timezone.utc)
    return (
        value.request_id, value.publication_id, "YOUTUBE", target.local_status,
        remote.state.value, verdict, verdict != "IN_SYNC", target.fingerprint,
        remote.fingerprint, target.destination_id, remote.remote_object_id,
        remote.remote_url, remote.evidence_id, remote.observed_at, now,
    )


class PublicationReconciliationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_reserve_is_owner_scoped_and_requires_current_channel(self):
        value = request()
        connection = FakeConnection([
            target_row(value), None, (0,), (value.request_id,),
        ])
        target = await PublicationReconciliationRepository(
            FakePool(connection)
        ).reserve(value, maximum_attempts=25)
        query, params = connection.calls[0]
        self.assertEqual(target.platform, PublicationPlatform.YOUTUBE)
        self.assertEqual(params, (value.publication_id, value.owner_user_id))
        self.assertIn("ch.enabled = true", query)
        self.assertIn("permissions_status = 'VALID'", query)
        self.assertIn("publication_contract = 'YOUTUBE_V1'", query)
        self.assertIn("FOR UPDATE OF p", query)
        self.assertIn("publication_reconciliation_attempts", connection.calls[3][0])

    async def test_get_existing_is_owner_scoped_and_parses_immutable_record(self):
        value = request()
        target = PublicationReconciliationRepository._target(target_row(value))
        remote = observation(value, target)
        connection = FakeConnection([record_row(value, target, remote)])
        record = await PublicationReconciliationRepository(
            FakePool(connection)
        ).get_existing(value)
        self.assertEqual(record.verdict, ReconciliationVerdict.IN_SYNC)
        self.assertEqual(connection.calls[0][1], (value.request_id, value.owner_user_id))

    async def test_record_rechecks_locked_snapshot_before_insert(self):
        value = request()
        target = PublicationReconciliationRepository._target(target_row(value))
        remote = observation(value, target)
        changed = target_row(value, status="PROCESSING", version=4)
        connection = FakeConnection([None, changed])
        with self.assertRaises(PublicationReconciliationConflict):
            await PublicationReconciliationRepository(FakePool(connection)).record(
                request=value, target=target, observation=remote,
                verdict=ReconciliationVerdict.IN_SYNC,
            )
        self.assertFalse(any(
            "INSERT INTO publication_reconciliations" in query
            for query, _ in connection.calls
        ))

    async def test_record_inserts_only_sanitized_snapshot_and_returns_record(self):
        value = request()
        row = target_row(value)
        target = PublicationReconciliationRepository._target(row)
        remote = observation(value, target)
        returned = record_row(value, target, remote)
        attempt = (
            value.publication_id, value.owner_user_id, target.fingerprint, 1, "RESERVED",
        )
        connection = FakeConnection([
            None, row, attempt, returned, (value.request_id,),
        ])
        record = await PublicationReconciliationRepository(FakePool(connection)).record(
            request=value, target=target, observation=remote,
            verdict=ReconciliationVerdict.IN_SYNC,
        )
        self.assertEqual(record.observation_fingerprint, remote.fingerprint)
        insert = connection.calls[3]
        self.assertIn("ON CONFLICT (request_id) DO NOTHING", insert[0])
        self.assertNotIn(target.credentials_ref, insert[1])
        self.assertIn("status = 'RECORDED'", connection.calls[4][0])

    async def test_changed_idempotent_replay_conflicts(self):
        value = request()
        target = PublicationReconciliationRepository._target(target_row(value))
        remote = observation(value, target)
        stored = list(record_row(value, target, remote))
        stored[8] = "b" * 64
        connection = FakeConnection([tuple(stored)])
        with self.assertRaises(PublicationReconciliationConflict):
            await PublicationReconciliationRepository(FakePool(connection)).record(
                request=value, target=target, observation=remote,
                verdict=ReconciliationVerdict.IN_SYNC,
            )

    async def test_same_request_for_different_publication_conflicts(self):
        value = request()
        target = PublicationReconciliationRepository._target(target_row(value))
        remote = observation(value, target)
        row = list(record_row(value, target, remote))
        row[1] = uuid4()
        connection = FakeConnection([tuple(row)])
        with self.assertRaises(PublicationReconciliationConflict):
            await PublicationReconciliationRepository(FakePool(connection)).get_existing(value)

    async def test_new_request_is_rejected_at_persisted_attempt_bound(self):
        value = request()
        connection = FakeConnection([target_row(value), None, (3,)])
        with self.assertRaises(PlatformReconciliationError) as caught:
            await PublicationReconciliationRepository(FakePool(connection)).reserve(
                value, maximum_attempts=3,
            )
        self.assertEqual(caught.exception.code, "OBSERVATION_LIMIT_REACHED")
        self.assertFalse(any(
            "INSERT INTO publication_reconciliation_attempts" in query
            for query, _ in connection.calls
        ))

    async def test_reserved_request_is_not_observed_again(self):
        value = request()
        row = target_row(value)
        target = PublicationReconciliationRepository._target(row)
        attempt = (
            value.publication_id, value.owner_user_id, target.fingerprint, 1, "RESERVED",
        )
        connection = FakeConnection([row, attempt])
        with self.assertRaises(PlatformReconciliationError) as caught:
            await PublicationReconciliationRepository(FakePool(connection)).reserve(
                value, maximum_attempts=25,
            )
        self.assertEqual(caught.exception.code, "REQUEST_OUTCOME_UNKNOWN")

    async def test_repository_rejects_forged_identity_or_verdict_before_sql(self):
        value = request()
        target = PublicationReconciliationRepository._target(target_row(value))
        remote = observation(value, target)
        forged = PlatformPublicationObservation(
            request_id=uuid4(), publication_id=value.publication_id,
            platform=target.platform, destination_id=target.destination_id,
            remote_object_id=target.remote_object_id,
            state=RemotePublicationState.PUBLISHED,
            observed_at=remote.observed_at, evidence_id=remote.evidence_id,
            remote_url=remote.remote_url,
        )
        connection = FakeConnection()
        repository = PublicationReconciliationRepository(FakePool(connection))
        with self.assertRaises(ValueError):
            await repository.record(
                request=value, target=target, observation=forged,
                verdict=ReconciliationVerdict.IN_SYNC,
            )
        deleted = PlatformPublicationObservation(
            request_id=value.request_id, publication_id=value.publication_id,
            platform=target.platform, destination_id=target.destination_id,
            remote_object_id=target.remote_object_id,
            state=RemotePublicationState.DELETED,
            observed_at=remote.observed_at, evidence_id=remote.evidence_id,
        )
        with self.assertRaises(ValueError):
            await repository.record(
                request=value, target=target, observation=deleted,
                verdict=ReconciliationVerdict.IN_SYNC,
            )
        self.assertEqual(connection.calls, [])


if __name__ == "__main__":
    unittest.main()
