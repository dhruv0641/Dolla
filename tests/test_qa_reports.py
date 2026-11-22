from contextlib import asynccontextmanager
from datetime import datetime, timezone
import unittest
from uuid import UUID

from flowx_os.db.qa_reports import IntegrityReportConflict, IntegrityReportRepository
from flowx_os.domain.assets import AssetKind
from flowx_os.qa.integrity import IntegrityDecision, IntegrityReport


REPORT_ID = UUID("72e90214-18c7-4651-81e1-6fad3d04a89a")
ASSET_ID = UUID("4beec3b7-4053-4c44-8ebc-56df62d45b31")
CONTENT_ID = UUID("269d0d0d-5d79-4094-a5be-8e2b293add68")
BRAND_ID = UUID("55b3d224-c123-4ea2-ab96-f4c725ca4c13")
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
    values = {
        "asset_id": ASSET_ID, "content_id": CONTENT_ID,
        "expected_kind": AssetKind.FINAL_VIDEO, "profile_id": None,
        "artifact_fingerprint": "a" * 64,
        "decision": IntegrityDecision.PASS, "findings": (),
        "decode_verified": True, "observed_sha256_hex": "b" * 64,
        "evidence_fingerprint": "c" * 64,
    }
    values.update(updates)
    return IntegrityReport.model_validate(values)


def stored(value):
    return (
        REPORT_ID, value.model_dump(mode="json"),
        [finding.code.value for finding in value.findings],
        value.decision.value, "AUTO", NOW,
    )


class IntegrityReportRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_insert_is_owner_scoped_and_uses_no_score(self):
        value = report()
        connection = Connection([(1,), stored(value)])
        result = await IntegrityReportRepository(Pool(connection)).create_or_get(
            report_id=REPORT_ID, brand_id=BRAND_ID,
            owner_user_id="owner-1", report=value,
        )
        self.assertEqual(result.report, value)
        self.assertIn("owner_user_id", connection.calls[0][0])
        self.assertIn("retention_state = 'ACTIVE'", connection.calls[0][0])
        self.assertIn("NULL, %s::jsonb", connection.calls[1][0])
        self.assertNotIn("100", connection.calls[1][0])

    async def test_exact_replay_is_idempotent(self):
        value = report()
        connection = Connection([(1,), None, stored(value)])
        result = await IntegrityReportRepository(Pool(connection)).create_or_get(
            report_id=REPORT_ID, brand_id=BRAND_ID,
            owner_user_id="owner-1", report=value,
        )
        self.assertEqual(result.report_id, REPORT_ID)
        self.assertIn("FOR UPDATE OF q", connection.calls[2][0])

    async def test_rebinding_existing_report_fails_closed(self):
        value = report()
        other = UUID("dc17d77c-f772-48bf-8e54-c680c8982e37")
        different = list(stored(value))
        different[0] = other
        connection = Connection([(1,), None, tuple(different)])
        with self.assertRaises(IntegrityReportConflict):
            await IntegrityReportRepository(Pool(connection)).create_or_get(
                report_id=REPORT_ID, brand_id=BRAND_ID,
                owner_user_id="owner-1", report=value,
            )

    async def test_unsafe_owner_is_rejected_before_storage(self):
        connection = Connection([])
        with self.assertRaises(ValueError):
            await IntegrityReportRepository(Pool(connection)).create_or_get(
                report_id=REPORT_ID, brand_id=BRAND_ID,
                owner_user_id="owner\nspoof", report=report(),
            )
        self.assertEqual(connection.calls, [])


if __name__ == "__main__":
    unittest.main()
