import json
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from flowx_os.db import (
    JobNotDeadLetteredError,
    LeaseLostError,
    OutboxValidationError,
    complete_job,
    enqueue_job,
    lease_due_jobs,
    list_dead_jobs,
    record_job_failure,
    requeue_dead_job,
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

    async def test_enqueue_accepts_aware_schedule_and_rejects_naive_schedule(self):
        scheduled = datetime(2026, 11, 18, 4, 0, tzinfo=timezone.utc)
        connection = FakeConnection([FakeCursor(row=(uuid4(),))])
        await enqueue_job(
            connection, idempotency_key=uuid4(), event_name="content.created",
            correlation_id=uuid4(), payload={}, run_after=scheduled,
        )
        self.assertEqual(connection.calls[0][1][-1], scheduled)
        with self.assertRaises(OutboxValidationError):
            await enqueue_job(
                FakeConnection(), idempotency_key=uuid4(), event_name="content.created",
                correlation_id=uuid4(), payload={}, run_after=datetime(2026, 11, 18),
            )

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
        self.assertIn("status = 'DEAD'", query)
        self.assertEqual(params[0].tzinfo, timezone.utc)
        self.assertEqual(params[5], "worker-1")

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
            await complete_job(
                connection, job_id=uuid4(), worker_id="stale-worker", attempt_count=2
            )
        self.assertIn("lease_until > now()", connection.calls[0][0])
        self.assertIn("attempt_count = %s", connection.calls[0][0])
        self.assertEqual(connection.calls[0][1][-1], 2)

    async def test_retry_records_safe_code_and_exponential_backoff(self):
        connection = FakeConnection([FakeCursor(row=("READY", 2, datetime.now(timezone.utc)))])
        result = await record_job_failure(
            connection, job_id=uuid4(), worker_id="worker-1", attempt_count=2,
            max_attempts=5, error_code="handler_error", retryable=True,
        )
        self.assertEqual(result.status, "READY")
        self.assertEqual(connection.calls[0][1][2], 10)
        self.assertEqual(connection.calls[0][1][3], "handler_error")
        self.assertIn("lease_until > now()", connection.calls[0][0])

    async def test_retryable_failure_at_limit_becomes_dead(self):
        connection = FakeConnection([FakeCursor(row=("DEAD", 5, datetime.now(timezone.utc)))])
        result = await record_job_failure(
            connection, job_id=uuid4(), worker_id="worker-1", attempt_count=5,
            max_attempts=5, error_code="handler_error", retryable=True,
        )
        self.assertEqual(result.status, "DEAD")
        self.assertEqual(connection.calls[0][1][:2], ("DEAD", False))

    async def test_failure_refuses_to_store_exception_text(self):
        connection = FakeConnection()
        with self.assertRaises(OutboxValidationError):
            await record_job_failure(
                connection, job_id=uuid4(), worker_id="worker-1", attempt_count=1,
                max_attempts=5, error_code="secret token abc", retryable=True,
            )
        self.assertEqual(connection.calls, [])

    async def test_failure_requires_a_current_live_lease(self):
        connection = FakeConnection([FakeCursor()])
        with self.assertRaises(LeaseLostError):
            await record_job_failure(
                connection, job_id=uuid4(), worker_id="worker-1", attempt_count=1,
                max_attempts=5, error_code="handler_error", retryable=True,
            )

    async def test_dead_letter_listing_omits_payload(self):
        row = (uuid4(), "content.created", uuid4(), 5, 5, "handler_error", datetime.now(timezone.utc))
        connection = FakeConnection([FakeCursor(rows=[row])])
        letters = await list_dead_jobs(connection)
        self.assertEqual(letters[0].id, row[0])
        self.assertNotIn("payload", connection.calls[0][0].lower())

    async def test_operator_requeue_only_changes_dead_job(self):
        job_id = uuid4()
        connection = FakeConnection([FakeCursor(row=(job_id,))])
        self.assertEqual(await requeue_dead_job(connection, job_id=job_id), job_id)
        self.assertIn("status = 'DEAD'", connection.calls[0][0])
        with self.assertRaises(JobNotDeadLetteredError):
            await requeue_dead_job(FakeConnection([FakeCursor()]), job_id=job_id)


if __name__ == "__main__":
    unittest.main()
