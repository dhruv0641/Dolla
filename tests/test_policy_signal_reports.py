from contextlib import asynccontextmanager
from datetime import datetime, timezone
import unittest
from uuid import UUID

from flowx_os.db.policy_signal_reports import (
    PolicySignalReportConflict,
    PolicySignalReportRepository,
)
from flowx_os.qa.policy_signals import PolicySignalService
from tests.test_policy_signals import av_report, review, review_context


REPORT_ID = UUID("c7c264ee-9e78-47f7-88e5-a19d75ee0bb7")
BRAND_ID = UUID("2f00d23a-78d8-408e-96cc-d2efbb332139")
NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


class Cursor:
    def __init__(self, row=None): self.row = row
    async def fetchone(self): return self.row


class Connection:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    @asynccontextmanager
    async def transaction(self): yield self

    async def execute(self, query, params=None):
        self.calls.append((query, params))
        return Cursor(self.rows.pop(0) if self.rows else None)


class Pool:
    def __init__(self, connection): self.value = connection

    @asynccontextmanager
    async def connection(self): yield self.value


def signal_report():
    context = review_context()
    return PolicySignalService().evaluate(
        av_report=av_report(), context=context, review=review(context),
        rights_authority_refs=("rights:original-work",),
    )


def stored(value):
    return (REPORT_ID, value.model_dump(mode="json"), [],
            value.decision.value, "AUTO", NOW)


class PolicySignalReportRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_insert_requires_owner_and_exact_passing_av_fingerprint(self):
        value = signal_report()
        connection = Connection([(1,), stored(value)])
        result = await PolicySignalReportRepository(Pool(connection)).create_or_get(
            report_id=REPORT_ID, brand_id=BRAND_ID,
            owner_user_id="owner-1", report=value,
        )
        self.assertEqual(result.report, value)
        self.assertIn("av.decision = 'PASS'", connection.calls[0][0])
        self.assertIn("owner_user_id", connection.calls[0][0])
        self.assertIn("WHERE version = 'signals-v1'", connection.calls[1][0])

    async def test_exact_replay_is_idempotent(self):
        value = signal_report()
        connection = Connection([(1,), None, stored(value)])
        result = await PolicySignalReportRepository(Pool(connection)).create_or_get(
            report_id=REPORT_ID, brand_id=BRAND_ID,
            owner_user_id="owner-1", report=value,
        )
        self.assertEqual(result.report_id, REPORT_ID)
        self.assertIn("FOR UPDATE OF q", connection.calls[2][0])

    async def test_rebinding_fails_closed(self):
        value = signal_report()
        different = list(stored(value))
        different[0] = UUID("6568863b-0080-4245-a878-f8d414c2b506")
        connection = Connection([(1,), None, tuple(different)])
        with self.assertRaises(PolicySignalReportConflict):
            await PolicySignalReportRepository(Pool(connection)).create_or_get(
                report_id=REPORT_ID, brand_id=BRAND_ID,
                owner_user_id="owner-1", report=value,
            )

    async def test_unsafe_owner_is_rejected_before_storage(self):
        connection = Connection([])
        with self.assertRaises(ValueError):
            await PolicySignalReportRepository(Pool(connection)).create_or_get(
                report_id=REPORT_ID, brand_id=BRAND_ID,
                owner_user_id="owner\nspoof", report=signal_report(),
            )
        self.assertEqual(connection.calls, [])


if __name__ == "__main__":
    unittest.main()
