from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import unittest
from uuid import uuid4

from flowx_os.db.publication_scheduling import (
    PublicationScheduleConflict,
    PublicationScheduleNotAllowed,
    PublicationScheduleRepository,
)
from flowx_os.publishing.scheduling import (
    PublicationApprovalDecision,
    PublicationApprovalRequest,
    PublicationDeliveryState,
    PublicationSchedulePolicy,
    PublicationScheduleRequest,
    PublicationSchedulingError,
)
from flowx_os.workflow.dispatcher import LeasedJob
from flowx_os.workflow.publication_dispatch import PublicationDispatchEnvelope


NOW = datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc)


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


def approval_request():
    return PublicationApprovalRequest(
        request_id=uuid4(), approval_id=uuid4(), publication_id=uuid4(),
        owner_user_id="owner-1", approver_user_id="owner-1",
        decision=PublicationApprovalDecision.APPROVE,
        valid_until=NOW + timedelta(days=3), reason="Reviewed exact export and channel",
    )


def schedule_request(approval):
    return PublicationScheduleRequest(
        request_id=uuid4(), schedule_id=uuid4(),
        publication_id=approval.publication_id, approval_id=approval.approval_id,
        owner_user_id=approval.owner_user_id,
        local_scheduled_at=datetime(2026, 11, 24, 12, 30),
        timezone_name="Asia/Kolkata",
    )


def target_row(approval, *, remote_upload=None):
    return (
        approval.publication_id, approval.owner_user_id, "YOUTUBE", "DRAFT",
        "YOUTUBE_V1", "b" * 64, 0, uuid4(), uuid4(), uuid4(), 4,
        "a" * 64, "Asia/Kolkata", True, "VALID", True, True,
        remote_upload, None, None, None,
    )


def approval_row(approval, target):
    return (
        approval.approval_id, approval.request_id, approval.publication_id,
        approval.owner_user_id, approval.decision.value, approval.valid_until,
        approval.reason, "YOUTUBE", target[7], target[8], target[9], target[10],
        target[6], target[11], NOW,
    )


def schedule_row(request, target, outbox_id):
    return (
        request.schedule_id, request.request_id, request.publication_id,
        request.approval_id, request.owner_user_id, "YOUTUBE", target[8],
        target[7], target[9], target[10], request.local_scheduled_at,
        request.timezone_name, request.fold, request.utc_offset_minutes,
        request.scheduled_at_utc, PublicationDeliveryState.SCHEDULED.value,
        outbox_id, NOW,
    )


class PublicationScheduleRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_due_dispatch_requires_exact_current_lease_and_evidence(self):
        publication_id = uuid4()
        schedule_id = uuid4()
        outbox_id = uuid4()
        leased = LeasedJob(
            id=outbox_id, event_name="publication.dispatch_due",
            correlation_id=publication_id,
            payload={
                "schema_version": 1, "schedule_id": str(schedule_id),
                "publication_id": str(publication_id), "platform": "YOUTUBE",
            },
            attempt_count=1, lease_owner="worker-1",
            lease_until=NOW + timedelta(minutes=2), max_attempts=5,
        )
        envelope = PublicationDispatchEnvelope.from_job(leased)
        connection = FakeConnection([(
            outbox_id, schedule_id, publication_id, "owner-1", "YOUTUBE",
            "SCHEDULED", NOW,
        )])

        result = await PublicationScheduleRepository(FakePool(connection)).load_due_dispatch(
            job=leased, envelope=envelope,
        )

        self.assertEqual(result.outbox_job_id, outbox_id)
        query, params = connection.calls[0]
        self.assertIn("o.status = 'LEASED'", query)
        self.assertIn("o.lease_until > now()", query)
        self.assertIn("r.state = 'DISPATCH_RESERVED' OR a.valid_until > now()", query)
        self.assertIn("pr.requires_human_review = true", query)
        self.assertEqual(params, (
            schedule_id, publication_id, "YOUTUBE", outbox_id, "worker-1", 1,
        ))

    async def test_approval_locks_and_snapshots_exact_pristine_publication(self):
        request = approval_request()
        target = target_row(request)
        row = approval_row(request, target)
        connection = FakeConnection([None, target, row])

        result = await PublicationScheduleRepository(FakePool(connection)).record_approval(request)

        self.assertEqual(result.approval_id, request.approval_id)
        self.assertEqual(result.channel_id, target[8])
        self.assertIn("FOR UPDATE OF p, ch", connection.calls[1][0])
        self.assertIn("INSERT INTO publication_delivery_approvals", connection.calls[2][0])
        self.assertNotIn(request.reason, connection.calls[2][0])

    async def test_approval_fails_closed_after_remote_identity_exists(self):
        request = approval_request()
        connection = FakeConnection([None, target_row(request, remote_upload="upload-1")])

        with self.assertRaises(PublicationScheduleNotAllowed):
            await PublicationScheduleRepository(FakePool(connection)).record_approval(request)

        self.assertFalse(any(
            "INSERT INTO publication_delivery_approvals" in query
            for query, _ in connection.calls
        ))

    async def test_schedule_is_atomic_with_outbox_and_exact_delivery_reservation(self):
        approval = approval_request()
        request = schedule_request(approval)
        target = target_row(approval)
        outbox_id = uuid4()
        result_row = schedule_row(request, target, outbox_id)
        connection = FakeConnection([
            None, target, approval_row(approval, target), (0,), None,
            (outbox_id,), result_row,
        ])
        policy = PublicationSchedulePolicy(enabled=True, maximum_per_local_day=3)

        result = await PublicationScheduleRepository(FakePool(connection)).schedule(
            request, now=NOW, policy=policy,
        )

        self.assertEqual(result.schedule_id, request.schedule_id)
        self.assertEqual(result.outbox_job_id, outbox_id)
        self.assertIn("event_name", connection.calls[5][0])
        self.assertEqual(connection.calls[5][1][5], request.scheduled_at_utc)
        self.assertIn("INSERT INTO publication_delivery_reservations", connection.calls[6][0])
        self.assertEqual(connection.calls[6][1][16], request.scheduled_at_utc)

    async def test_schedule_enforces_cap_before_outbox_and_replay_conflicts(self):
        approval = approval_request()
        request = schedule_request(approval)
        target = target_row(approval)
        connection = FakeConnection([
            None, target, approval_row(approval, target), (3,),
        ])
        with self.assertRaises(PublicationSchedulingError) as caught:
            await PublicationScheduleRepository(FakePool(connection)).schedule(
                request, now=NOW,
                policy=PublicationSchedulePolicy(enabled=True, maximum_per_local_day=3),
            )
        self.assertEqual(caught.exception.code, "DAILY_CAP_REACHED")
        self.assertFalse(any("INSERT INTO outbox_jobs" in query for query, _ in connection.calls))

        existing = schedule_row(request, target, uuid4())
        conflicting = PublicationScheduleRequest(
            request_id=request.request_id, schedule_id=uuid4(),
            publication_id=request.publication_id, approval_id=request.approval_id,
            owner_user_id=request.owner_user_id,
            local_scheduled_at=request.local_scheduled_at,
            timezone_name=request.timezone_name,
        )
        with self.assertRaises(PublicationScheduleConflict):
            await PublicationScheduleRepository(
                FakePool(FakeConnection([existing]))
            ).schedule(
                conflicting, now=NOW, policy=PublicationSchedulePolicy(enabled=True),
            )

        replay_connection = FakeConnection([existing])
        replayed = await PublicationScheduleRepository(
            FakePool(replay_connection)
        ).schedule(
            request, now=NOW + timedelta(days=365),
            policy=PublicationSchedulePolicy(enabled=True),
        )
        self.assertEqual(replayed.schedule_id, request.schedule_id)
        self.assertEqual(len(replay_connection.calls), 1)

    async def test_public_replay_lookups_are_owner_scoped_and_exact(self):
        approval = approval_request()
        target = target_row(approval)
        approval_connection = FakeConnection([approval_row(approval, target)])
        stored_approval = await PublicationScheduleRepository(
            FakePool(approval_connection)
        ).get_approval(approval)
        self.assertEqual(stored_approval.approval_id, approval.approval_id)
        self.assertIn("owner_user_id = %s", approval_connection.calls[0][0])

        request = schedule_request(approval)
        existing = schedule_row(request, target, uuid4())
        schedule_connection = FakeConnection([existing])
        stored_schedule = await PublicationScheduleRepository(
            FakePool(schedule_connection)
        ).get_schedule(request)
        self.assertEqual(stored_schedule.schedule_id, request.schedule_id)
        self.assertIn("owner_user_id = %s", schedule_connection.calls[0][0])


if __name__ == "__main__":
    unittest.main()
