from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import unittest
from uuid import UUID, uuid4

from flowx_os.publishing.reconciliation import PublicationPlatform
from flowx_os.publishing.scheduling import PublicationDeliveryState
from flowx_os.workflow.dispatcher import DispatchOutcome, LeasedJob
from flowx_os.workflow.publication_dispatch import (
    PUBLICATION_DISPATCH_EVENT,
    PublicationDispatchCommand,
    PublicationDispatchFailure,
    ScheduledPublicationDispatcher,
)


NOW = datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, *, rowcount=1, row=None):
        self.rowcount = rowcount
        self.row = row

    async def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, *, failure_status="DEAD"):
        self.calls = []
        self.failure_status = failure_status

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, query, params=()):
        self.calls.append((query, params))
        if "RETURNING status, attempt_count, run_after" in query:
            return FakeCursor(row=(
                self.failure_status, params[-2], NOW + timedelta(seconds=5),
            ))
        return FakeCursor(rowcount=1)


class FakePool:
    def __init__(self, connection):
        self.connection_value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.connection_value


def job():
    publication_id = uuid4()
    schedule_id = uuid4()
    return LeasedJob(
        id=uuid4(), event_name=PUBLICATION_DISPATCH_EVENT,
        correlation_id=publication_id,
        payload={
            "schema_version": 1, "schedule_id": str(schedule_id),
            "publication_id": str(publication_id), "platform": "YOUTUBE",
        },
        attempt_count=1, lease_owner="publication-worker-1",
        lease_until=NOW + timedelta(minutes=2), max_attempts=5,
    )


def command(value):
    return PublicationDispatchCommand(
        outbox_job_id=value.id, schedule_id=uuid4() if "schedule_id" not in value.payload else UUID(value.payload["schedule_id"]),
        publication_id=value.correlation_id, owner_user_id="owner-1",
        platform=PublicationPlatform.YOUTUBE,
        state=PublicationDeliveryState.SCHEDULED, scheduled_at_utc=NOW,
    )


class FakeStore:
    def __init__(self, value):
        self.value = value
        self.calls = []

    async def load_due_dispatch(self, *, job, envelope):
        self.calls.append((job, envelope))
        return self.value


class ScheduledPublicationDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_due_event_invokes_exact_platform_executor_and_acknowledges(self):
        value = job()
        stored = command(value)
        stored = PublicationDispatchCommand(
            outbox_job_id=value.id,
            schedule_id=uuid4(),
            publication_id=value.correlation_id,
            owner_user_id=stored.owner_user_id, platform=stored.platform,
            state=stored.state, scheduled_at_utc=stored.scheduled_at_utc,
        )
        value = LeasedJob(
            id=value.id, event_name=value.event_name, correlation_id=value.correlation_id,
            payload={**value.payload, "schedule_id": str(stored.schedule_id)},
            attempt_count=value.attempt_count, lease_owner=value.lease_owner,
            lease_until=value.lease_until, max_attempts=value.max_attempts,
        )
        seen = []

        async def execute(exact):
            seen.append(exact)

        connection = FakeConnection()
        outcome = await ScheduledPublicationDispatcher(
            pool=FakePool(connection), store=FakeStore(stored),
            executors={PublicationPlatform.YOUTUBE: execute},
        ).dispatch(value, worker_id=value.lease_owner)

        self.assertEqual(outcome, DispatchOutcome.DONE)
        self.assertEqual(seen, [stored])
        self.assertIn("SET status = 'DONE'", connection.calls[0][0])

    async def test_unknown_executor_outcome_is_not_retried_blindly(self):
        value = job()
        stored = command(value)

        async def execute(_command):
            raise RuntimeError("provider response contained a secret")

        connection = FakeConnection(failure_status="DEAD")
        outcome = await ScheduledPublicationDispatcher(
            pool=FakePool(connection), store=FakeStore(stored),
            executors={PublicationPlatform.YOUTUBE: execute},
        ).dispatch(value, worker_id=value.lease_owner)

        self.assertEqual(outcome, DispatchOutcome.DEAD)
        self.assertEqual(connection.calls[0][1][3], "publication_outcome_unknown")
        self.assertNotIn("secret", str(connection.calls))

    async def test_classified_pre_provider_failure_can_retry_but_ambiguity_cannot(self):
        for failure, status, expected in (
            (PublicationDispatchFailure("authorization_unavailable", retryable=True),
             "READY", DispatchOutcome.RETRY_SCHEDULED),
            (PublicationDispatchFailure("provider_outcome_unknown", retryable=True, ambiguous=True),
             "DEAD", DispatchOutcome.DEAD),
        ):
            with self.subTest(code=failure.code):
                value = job()

                async def execute(_command, error=failure):
                    raise error

                connection = FakeConnection(failure_status=status)
                outcome = await ScheduledPublicationDispatcher(
                    pool=FakePool(connection), store=FakeStore(command(value)),
                    executors={PublicationPlatform.YOUTUBE: execute},
                ).dispatch(value, worker_id=value.lease_owner)
                self.assertEqual(outcome, expected)
                self.assertEqual(connection.calls[0][1][3], failure.code)

    async def test_invalid_payload_and_missing_executor_fail_closed(self):
        value = job()
        invalid = LeasedJob(
            id=value.id, event_name=value.event_name,
            correlation_id=value.correlation_id, payload={"schema_version": 1},
            attempt_count=value.attempt_count, lease_owner=value.lease_owner,
            lease_until=value.lease_until, max_attempts=value.max_attempts,
        )
        connection = FakeConnection()
        outcome = await ScheduledPublicationDispatcher(
            pool=FakePool(connection), store=FakeStore(command(value)), executors={},
        ).dispatch(invalid, worker_id=invalid.lease_owner)
        self.assertEqual(outcome, DispatchOutcome.DEAD)
        self.assertEqual(connection.calls[0][1][3], "publication_dispatch_invalid")

        connection = FakeConnection()
        outcome = await ScheduledPublicationDispatcher(
            pool=FakePool(connection), store=FakeStore(command(value)), executors={},
        ).dispatch(value, worker_id=value.lease_owner)
        self.assertEqual(outcome, DispatchOutcome.DEAD)
        self.assertEqual(connection.calls[0][1][3], "publication_executor_unavailable")


if __name__ == "__main__":
    unittest.main()
