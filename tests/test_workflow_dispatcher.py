import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flowx_os.db.outbox import LeaseLostError
from flowx_os.workflow.dispatcher import (
    LeasedJob,
    OutboxDispatcher,
    UnknownWorkflowHandler,
    WorkflowDispatchValidationError,
)


class FakeCursor:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount


class FakeConnection:
    def __init__(self, *, completion_rowcount=1):
        self.events = []
        self.queries = []
        self.completion_rowcount = completion_rowcount

    @asynccontextmanager
    async def transaction(self):
        self.events.append("begin")
        try:
            yield
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")

    async def execute(self, query, params=()):
        self.queries.append((query, params))
        return FakeCursor(rowcount=self.completion_rowcount)


class FakePool:
    def __init__(self, connection):
        self.value = connection
        self.events = []

    @asynccontextmanager
    async def connection(self):
        self.events.append("acquire")
        try:
            yield self.value
        finally:
            self.events.append("release")


def make_job(*, event_name="content.created", lease_owner="worker-1"):
    return LeasedJob(
        id=uuid4(), event_name=event_name, correlation_id=uuid4(), payload={"content_id": "c1"},
        attempt_count=1, lease_owner=lease_owner,
        lease_until=datetime.now(timezone.utc) + timedelta(minutes=2),
    )


class WorkflowDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_handler_and_job_acknowledgement_commit_in_one_transaction(self):
        connection = FakeConnection()
        pool = FakePool(connection)
        job = make_job()
        seen = []

        async def handler(db, leased_job):
            seen.append((db, leased_job.id))
            db.events.append("handler")
            await db.execute("INSERT INTO processed_events (job_id) VALUES (%s)", (leased_job.id,))

        await OutboxDispatcher(pool, {"content.created": handler}).dispatch(job, worker_id="worker-1")
        self.assertEqual(seen, [(connection, job.id)])
        self.assertEqual(connection.events, ["begin", "handler", "commit"])
        self.assertEqual(pool.events, ["acquire", "release"])
        self.assertEqual(len(connection.queries), 2)
        self.assertIn("SET status = 'DONE'", connection.queries[1][0])
        self.assertEqual(connection.queries[1][1], (job.id, "worker-1"))

    async def test_handler_failure_rolls_back_and_does_not_acknowledge(self):
        connection = FakeConnection()
        async def handler(_db, _job):
            raise RuntimeError("handler failed")
        with self.assertRaisesRegex(RuntimeError, "handler failed"):
            await OutboxDispatcher(FakePool(connection), {"content.created": handler}).dispatch(
                make_job(), worker_id="worker-1"
            )
        self.assertEqual(connection.events, ["begin", "rollback"])
        self.assertEqual(connection.queries, [])

    async def test_lease_loss_rolls_back_handler_database_writes(self):
        connection = FakeConnection(completion_rowcount=0)
        async def handler(db, _job):
            db.events.append("handler")
            await db.execute("INSERT INTO processed_events DEFAULT VALUES")
        with self.assertRaises(LeaseLostError):
            await OutboxDispatcher(FakePool(connection), {"content.created": handler}).dispatch(
                make_job(), worker_id="worker-1"
            )
        self.assertEqual(connection.events, ["begin", "handler", "rollback"])
        self.assertEqual(len(connection.queries), 2)

    async def test_wrong_worker_and_unknown_event_fail_before_database_work(self):
        connection = FakeConnection()
        dispatcher = OutboxDispatcher(FakePool(connection), {})
        with self.assertRaises(WorkflowDispatchValidationError):
            await dispatcher.dispatch(make_job(), worker_id="worker-2")
        with self.assertRaises(UnknownWorkflowHandler):
            await dispatcher.dispatch(make_job(event_name="unknown"), worker_id="worker-1")
        self.assertEqual(connection.events, [])
        self.assertEqual(connection.queries, [])

    async def test_registry_rejects_invalid_handler_configuration(self):
        with self.assertRaises(WorkflowDispatchValidationError):
            OutboxDispatcher(FakePool(FakeConnection()), {" ": lambda *_: None})
        with self.assertRaises(WorkflowDispatchValidationError):
            OutboxDispatcher(FakePool(FakeConnection()), {"content.created": object()})

    async def test_job_contract_requires_stable_ids_and_timezone_aware_lease(self):
        values = dict(
            id=uuid4(), event_name="content.created", correlation_id=uuid4(), payload={},
            attempt_count=1, lease_owner="worker-1", lease_until=datetime.now(),
        )
        with self.assertRaises(WorkflowDispatchValidationError):
            LeasedJob(**values)

    async def test_leased_job_maps_outbox_row_and_exposes_stable_idempotency_key(self):
        job = make_job()
        row = (job.id, job.event_name, job.correlation_id, job.payload,
               job.attempt_count, job.lease_owner, job.lease_until)
        mapped = LeasedJob.from_row(row)
        self.assertEqual(mapped, job)
        self.assertEqual(mapped.idempotency_key, job.id)
        with self.assertRaises(WorkflowDispatchValidationError):
            LeasedJob.from_row(row[:-1])


if __name__ == "__main__":
    unittest.main()
