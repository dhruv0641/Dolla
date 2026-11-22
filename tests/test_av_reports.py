from contextlib import asynccontextmanager
from datetime import datetime, timezone
import unittest
from uuid import UUID

from flowx_os.db.av_reports import AvReportConflict, AvReportRepository
from flowx_os.qa.av_evaluation import (
    AvDecision,
    AvEvaluationReport,
    AvMeasurements,
    SubjectiveSignal,
    av_evidence_fingerprint,
)


REPORT_ID = UUID("d9853172-115f-4b29-8201-6938a452434c")
ASSET_ID = UUID("c63f3cd8-2612-411b-b4dd-505112c36cf5")
CONTENT_ID = UUID("c78092b8-a89a-4164-a9ea-9e0dc3d32fa7")
BRAND_ID = UUID("2f00d23a-78d8-408e-96cc-d2efbb332139")
NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


class Cursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class Connection:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, query, params=None):
        self.calls.append((query, params))
        return Cursor(self.rows.pop(0) if self.rows else None)


class Pool:
    def __init__(self, connection):
        self.value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.value


def report(**updates):
    from flowx_os.qa.av_evaluation import AvEvaluationPolicy
    policy = AvEvaluationPolicy()
    measured = AvMeasurements(
        evaluated_duration_ms=1000,
        black_duration_ms=0, black_ratio=0.0, black_intervals=0,
        freeze_duration_ms=0, freeze_ratio=0.0, freeze_intervals=0,
        silence_duration_ms=0, silence_ratio=0.0, silence_intervals=0,
        integrated_lufs=-16.0, true_peak_dbtp=-2.0,
    )
    fingerprint = av_evidence_fingerprint(
        asset_id=ASSET_ID, content_id=CONTENT_ID,
        integrity_evidence_fingerprint="a" * 64,
        policy=policy, findings=(), measurements=measured,
    )
    values = {
        "asset_id": ASSET_ID, "content_id": CONTENT_ID,
        "integrity_evidence_fingerprint": "a" * 64,
        "policy": policy, "decision": AvDecision.PASS, "findings": (),
        "measurements": measured,
        "subjective_signals_not_evaluated": tuple(SubjectiveSignal),
        "evidence_fingerprint": fingerprint,
    }
    values.update(updates)
    return AvEvaluationReport.model_validate(values)


def stored(value):
    return (
        REPORT_ID, value.model_dump(mode="json"), [],
        value.decision.value, "AUTO", NOW,
    )


class AvReportRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_insert_requires_owner_and_passing_integrity_fingerprint(self):
        value = report()
        connection = Connection([(1,), stored(value)])
        result = await AvReportRepository(Pool(connection)).create_or_get(
            report_id=REPORT_ID, brand_id=BRAND_ID,
            owner_user_id="owner-1", report=value,
        )
        self.assertEqual(result.report, value)
        self.assertIn("integrity.decision = 'PASS'", connection.calls[0][0])
        self.assertIn("owner_user_id", connection.calls[0][0])
        self.assertIn("WHERE version = 'av-v1'", connection.calls[1][0])

    async def test_exact_replay_is_idempotent(self):
        value = report()
        connection = Connection([(1,), None, stored(value)])
        result = await AvReportRepository(Pool(connection)).create_or_get(
            report_id=REPORT_ID, brand_id=BRAND_ID,
            owner_user_id="owner-1", report=value,
        )
        self.assertEqual(result.report_id, REPORT_ID)
        self.assertIn("FOR UPDATE OF q", connection.calls[2][0])

    async def test_rebinding_fails_closed(self):
        value = report()
        different = list(stored(value))
        different[0] = UUID("6568863b-0080-4245-a878-f8d414c2b506")
        connection = Connection([(1,), None, tuple(different)])
        with self.assertRaises(AvReportConflict):
            await AvReportRepository(Pool(connection)).create_or_get(
                report_id=REPORT_ID, brand_id=BRAND_ID,
                owner_user_id="owner-1", report=value,
            )

    async def test_unsafe_owner_is_rejected_before_storage(self):
        connection = Connection([])
        with self.assertRaises(ValueError):
            await AvReportRepository(Pool(connection)).create_or_get(
                report_id=REPORT_ID, brand_id=BRAND_ID,
                owner_user_id="owner\nspoof", report=report(),
            )
        self.assertEqual(connection.calls, [])


if __name__ == "__main__":
    unittest.main()
