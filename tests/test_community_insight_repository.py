from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import unittest
from uuid import uuid4

from flowx_os.community.analysis import CommunityTheme
from flowx_os.community.insights import CommunityInsightPolicy, CommunityInsightRequest, CommunityInsightService
from flowx_os.db.community_insights import CommunityInsightRepository

NOW = datetime(2026, 11, 24, 3, 0, tzinfo=timezone.utc)

class FakeCursor:
    def __init__(self, payload=None): self.payload = payload
    async def fetchone(self): return self.payload
    async def fetchall(self): return [] if self.payload is None else list(self.payload)

class FakeConnection:
    def __init__(self, payloads=()): self.payloads, self.calls = list(payloads), []
    @asynccontextmanager
    async def transaction(self): yield self
    async def execute(self, query, params=None):
        self.calls.append((query, params))
        return FakeCursor(self.payloads.pop(0) if self.payloads else None)

class FakePool:
    def __init__(self, connection): self.value = connection
    @asynccontextmanager
    async def connection(self): yield self.value

def cluster_row(report_id):
    values = ("d" * 63 + "0", "d" * 63 + "1")
    fingerprint = hashlib.sha256("|".join((str(report_id), "FEATURE_REQUEST", "2", "0", ",".join(values))).encode()).hexdigest()
    return ("FEATURE_REQUEST", 2, 0, list(values), fingerprint)

def report_row(publication_id, owner="owner-1"):
    report_id = uuid4()
    return (owner, publication_id, report_id, "a" * 64, "b" * 64,
            NOW - timedelta(minutes=1), 2, 0)

class CommunityInsightRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_source_is_owner_scoped_and_uses_latest_inert_analysis(self):
        publication_id = uuid4()
        request = CommunityInsightRequest(uuid4(), "owner-1", publication_id, NOW)
        report = report_row(publication_id)
        connection = FakeConnection([report, [cluster_row(report[2])]])
        source = await CommunityInsightRepository(FakePool(connection)).load_source(request)
        self.assertEqual(source.analysis_request_id, report[2])
        self.assertEqual(source.clusters[0].theme, CommunityTheme.FEATURE_REQUEST)
        query, params = connection.calls[0]
        self.assertIn("ORDER BY r.created_at DESC,r.request_id DESC LIMIT 1", query)
        self.assertIn("r.outbound_action_authorized=false", query)
        self.assertEqual(params, (publication_id, "owner-1"))

    async def test_persist_rechecks_source_under_publication_lock(self):
        publication_id = uuid4()
        request = CommunityInsightRequest(uuid4(), "owner-1", publication_id, NOW)
        report = report_row(publication_id)
        source = await CommunityInsightRepository(
            FakePool(FakeConnection([report, [cluster_row(report[2])]]))
        ).load_source(request)
        class MemoryStore:
            async def get_existing(self, value): return None
            async def load_source(self, value): return source
            async def persist(self, value, loaded, record): return record
        record = await CommunityInsightService(
            MemoryStore(), CommunityInsightPolicy(enabled=True),
        ).propose(request, now=NOW)
        connection = FakeConnection([
            None, (publication_id,), report, [cluster_row(report[2])],
            tuple(range(20)), ("FEATURE_REQUEST",),
        ])
        persisted = await CommunityInsightRepository(FakePool(connection)).persist(request, source, record)
        self.assertEqual(persisted, record)
        self.assertIn("FOR UPDATE OF p", connection.calls[1][0])
        self.assertIn("FOR SHARE OF r", connection.calls[2][0])
        self.assertIn("community_research_proposals", connection.calls[-1][0])

if __name__ == "__main__": unittest.main()
