from contextlib import asynccontextmanager
from uuid import uuid4
import unittest
from datetime import datetime, timedelta, timezone

from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.generation_jobs import FlowGenerationJobRepository
from flowx_os.flow_mcp import JobSubmissionRequest
from flowx_os.flow_mcp import PersistedJobResumeContext


class FakeCursor:
    def __init__(self, row=None, rowcount=1):
        self.row = row
        self.rowcount = rowcount

    async def fetchone(self):
        return self.row

    async def fetchall(self):
        return []


class FakeConnection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, query, params=None):
        self.calls.append((query, params))
        row = self.rows.pop(0) if self.rows else None
        return FakeCursor(row)


class FakePool:
    def __init__(self, connection):
        self._connection = connection

    @asynccontextmanager
    async def connection(self):
        yield self._connection


def request():
    return JobSubmissionRequest(
        scene_id=uuid4(), request_id=uuid4(), owner_user_id="owner-1", attempt_index=1,
        model="veo-3.1-lite", prompt="A scene", duration_seconds=8, quoted_credits=2,
        arguments={"auto_confirm": True, "prompt": "A scene", "model": "veo-3.1-lite", "duration": 8,
                   "ratio": "9:16",
                   "project_url": "https://labs.google/fx/tools/flow", "output_dir": "C:/flow-output"},
        settings={"aspect_ratio": "9:16"},
    )


class FlowGenerationJobRepositoryTests(unittest.IsolatedAsyncioTestCase):
    NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)

    @classmethod
    def eligible_row(cls, reservation_id, account_id, credits=2, **overrides):
        values = {
            "quoted_at": cls.NOW - timedelta(minutes=1),
            "quote_expires_at": cls.NOW + timedelta(minutes=5),
            "health": "HEALTHY", "paused": False, "compliant": True,
            "daily": 20, "monthly": 50,
            "reconciled": cls.NOW - timedelta(minutes=1),
            "daily_reset": cls.NOW + timedelta(hours=8),
            "cycle_start": cls.NOW - timedelta(days=2), "max_inflight": 1,
        }
        values.update(overrides)
        return (reservation_id, account_id, credits, values["quoted_at"], values["quote_expires_at"],
                values["health"], values["paused"], values["compliant"], values["daily"],
                values["monthly"], values["reconciled"], values["daily_reset"],
                values["cycle_start"], values["max_inflight"])

    async def test_atomic_claim_checks_owner_reservation_and_inserts_before_send(self):
        reservation_id, account_id, job_id = uuid4(), uuid4(), uuid4()
        connection = FakeConnection([
            self.eligible_row(reservation_id, account_id), (1, 2), None, (job_id, "RESERVED", None),
        ])
        result = await FlowGenerationJobRepository(FakePool(connection), now=lambda: self.NOW).claim_or_get(
            account_ref="flow-account", request=request(), fingerprint="a" * 64,
        )
        self.assertEqual((result.job_id, result.status, result.created), (job_id, "RESERVED", True))
        self.assertIn("owner_user_id", connection.calls[0][0])
        self.assertIn("reservation.state = 'RESERVED'", connection.calls[0][0])
        self.assertIn("ON CONFLICT (idempotency_fingerprint) DO NOTHING", connection.calls[3][0])
        self.assertIn("status)", connection.calls[3][0])

    async def test_existing_claim_never_creates_another_generation_row(self):
        reservation_id, account_id, job_id = uuid4(), uuid4(), uuid4()
        task_request = request()
        connection = FakeConnection([
            self.eligible_row(reservation_id, account_id), (1, 2),
            (job_id, account_id, task_request.scene_id, reservation_id, 1, "REMOTE_SUBMISSION_UNKNOWN", None),
        ])
        result = await FlowGenerationJobRepository(FakePool(connection), now=lambda: self.NOW).claim_or_get(
            account_ref="flow-account", request=task_request, fingerprint="b" * 64,
        )
        self.assertFalse(result.created)
        self.assertEqual(result.status, "REMOTE_SUBMISSION_UNKNOWN")
        self.assertEqual(len(connection.calls), 3)

    async def test_missing_reservation_fails_closed_before_insert(self):
        connection = FakeConnection([None])
        with self.assertRaises(RepositoryUnavailable):
            await FlowGenerationJobRepository(FakePool(connection)).claim_or_get(
                account_ref="flow-account", request=request(), fingerprint="c" * 64,
            )
        self.assertEqual(len(connection.calls), 1)

    async def test_status_updates_only_transition_reserved_claims(self):
        connection = FakeConnection()
        repository = FlowGenerationJobRepository(FakePool(connection))
        job_id = uuid4()
        await repository.mark_submitted(job_id=job_id, external_job_id="remote-1")
        await repository.mark_remote_submission_unknown(job_id=job_id)
        self.assertIn("status = 'SUBMITTED'", connection.calls[0][0])
        self.assertIn("status = 'REMOTE_SUBMISSION_UNKNOWN'", connection.calls[1][0])

    async def test_resume_context_is_loaded_only_from_persisted_job_request(self):
        job_id = uuid4()
        connection = FakeConnection([("remote-1", "https://labs.google/fx/tools/flow",
                                      "original prompt", "C:/flow-output")])
        result = await FlowGenerationJobRepository(FakePool(connection)).get_resume_context(
            job_id=job_id, account_ref="flow-account", owner_user_id="owner-1",
        )
        self.assertEqual(result, PersistedJobResumeContext(
            "remote-1", "https://labs.google/fx/tools/flow", "original prompt", "C:/flow-output",
        ))
        self.assertIn("request_json->'arguments'->>'prompt'", connection.calls[0][0])
        self.assertIn("'REMOTE_SUBMISSION_UNKNOWN'", connection.calls[0][0])
        self.assertIn("account.alias = %s", connection.calls[0][0])
        self.assertIn("account.owner_user_id = %s", connection.calls[0][0])

    async def test_missing_or_incomplete_resume_context_stays_unavailable(self):
        for row in [None, (None, "https://labs.google/fx/tools/flow", "prompt", "C:/out")]:
            connection = FakeConnection([row])
            result = await FlowGenerationJobRepository(FakePool(connection)).get_resume_context(
                job_id=uuid4(), account_ref="flow-account", owner_user_id="owner-1",
            )
            self.assertIsNone(result)

    async def test_expired_quote_or_paused_account_cannot_claim_before_submit(self):
        for overrides in [
            {"quote_expires_at": self.NOW - timedelta(seconds=1)},
            {"paused": True},
        ]:
            reservation_id, account_id = uuid4(), uuid4()
            connection = FakeConnection([self.eligible_row(reservation_id, account_id, **overrides)])
            with self.subTest(overrides=overrides), self.assertRaises(RepositoryUnavailable):
                await FlowGenerationJobRepository(FakePool(connection), now=lambda: self.NOW).claim_or_get(
                    account_ref="flow-account", request=request(), fingerprint="d" * 64,
                )
            self.assertEqual(len(connection.calls), 1)


if __name__ == "__main__":
    unittest.main()
