import json
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from flowx_os.db import (
    LeaseLostError,
    OutboxValidationError,
    complete_job,
    enqueue_job,
    lease_due_jobs,
)


class FakeCursor:
    def __init__(self, row=None, rows=None, rowcount=1):
        self.row = row
        self.rows = rows or []
        self.rowcount = rowcount

    async def fetchone(self):
        return self.row

    async def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursors=None):
        self.cursors = list(cursors or [])
        self.calls = []

    async def execute(self, query, params=()):
        self.calls.append((query, params))
        return self.cursors.pop(0) if self.cursors else FakeCursor()


class OutboxTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_uses_idempotency_key_and_parameterized_json(self):
        job_id, key, correlation = uuid4(), uuid4(), uuid4()
        connection = FakeConnection([FakeCursor(row=(job_id,))])
        result = await enqueue_job(
            connection, idempotency_key=key, event_name="content.created",
            correlation_id=correlation, payload={"id": str(job_id)},
        )
        self.assertEqual(result, job_id)
        query, params = connection.calls[0]
        self.assertIn("ON CONFLICT (idempotency_key) DO NOTHING", query)
        self.assertEqual(params[0], key)
        self.assertEqual(json.loads(params[3]), {"id": str(job_id)})

    async def test_duplicate_enqueue_returns_existing_job(self):
        job_id = uuid4()
        connection = FakeConnection([FakeCursor(), FakeCursor(row=(job_id,))])
        result = await enqueue_job(
            connection, idempotency_key=uuid4(), event_name="content.created",
            correlation_id=uuid4(), payload={},
        )
        self.assertEqual(result, job_id)
        self.assertEqual(len(connection.calls), 2)

    async def test_lease_query_uses_skip_locked_and_utc_time(self):
        connection = FakeConnection([FakeCursor(rows=[("job",)])])
        now = datetime(2026, 11, 18, 1, 0, tzinfo=timezone.utc)
        rows = await lease_due_jobs(connection, worker_id="worker-1", now=now)
        self.assertEqual(rows, [("job",)])
        query, params = connection.calls[0]
        self.assertIn("FOR UPDATE SKIP LOCKED", query)
        self.assertEqual(params[0].tzinfo, timezone.utc)
        self.assertEqual(params[3], "worker-1")

    async def test_lease_rejects_naive_clock_without_query(self):
        connection = FakeConnection()
        with self.assertRaisesRegex(OutboxValidationError, "timezone-aware"):
            await lease_due_jobs(
                connection, worker_id="worker-1", now=datetime(2026, 11, 18, 1, 0)
            )
        self.assertEqual(connection.calls, [])

    async def test_complete_requires_current_lease_owner(self):
        connection = FakeConnection([FakeCursor(rowcount=0)])
        with self.assertRaises(LeaseLostError):
            await complete_job(connection, job_id=uuid4(), worker_id="stale-worker")
        self.assertIn("lease_until > now()", connection.calls[0][0])


if __name__ == "__main__":
    unittest.main()
