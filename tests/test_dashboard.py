import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from flowx_os.db.dashboard import DashboardRepository, DashboardUnavailable


class FakeCursor:
    def __init__(self, row): self.row = row
    async def fetchone(self): return self.row


class FakeConnection:
    def __init__(self, row): self.row = row; self.queries = []
    @asynccontextmanager
    async def transaction(self): yield
    async def execute(self, query, params=None): self.queries.append((query, params)); return FakeCursor(self.row)


class FakePool:
    def __init__(self, row): self.connection_value = FakeConnection(row)
    @asynccontextmanager
    async def connection(self): yield self.connection_value


class DashboardRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_is_owner_scoped_bounded_and_serializes_timestamp(self):
        generated = datetime(2026, 11, 24, tzinfo=timezone.utc)
        pool = FakePool(({"generated_at": generated, "owner_user_id": "owner-1", "content": []},))
        result = await DashboardRepository(pool).snapshot(owner_user_id=" owner-1 ")
        query, params = pool.connection_value.queries[0]
        self.assertEqual(params, ("owner-1",))
        self.assertIn("flowx_dashboard_content", query)
        self.assertIn("flowx_dashboard_brands", query)
        self.assertIn("LIMIT 200", query)
        self.assertNotIn("credentials_ref", query)
        self.assertEqual(result["generated_at"], "2026-11-24T00:00:00+00:00")

    async def test_invalid_owner_fails_before_database_access(self):
        pool = FakePool(({},))
        with self.assertRaises(ValueError):
            await DashboardRepository(pool).snapshot(owner_user_id=" ")
        self.assertEqual(pool.connection_value.queries, [])

    async def test_missing_document_fails_closed(self):
        with self.assertRaises(DashboardUnavailable):
            await DashboardRepository(FakePool(None)).snapshot(owner_user_id="owner-1")


class DashboardMigrationTests(unittest.TestCase):
    def test_dashboard_views_are_sanitized_and_security_barrier_enabled(self):
        from pathlib import Path
        sql = (Path(__file__).resolve().parents[1] / "migrations" / "0033_authenticated_dashboard_views.sql").read_text(encoding="utf-8")
        self.assertEqual(sql.count("WITH (security_barrier = true)"), 18)
        for view in ("flowx_dashboard_flow_accounts", "flowx_dashboard_channels", "flowx_dashboard_assets"):
            definition = sql.split(f"CREATE VIEW {view}", 1)[1].split("CREATE VIEW", 1)[0]
            self.assertNotIn("credentials_ref", definition)
            self.assertNotIn("storage_uri", definition)

        brands_sql = (Path(__file__).resolve().parents[1] / "migrations" / "0034_dashboard_brands_view.sql").read_text(encoding="utf-8")
        self.assertIn("WITH (security_barrier = true)", brands_sql)
        self.assertNotIn("credentials_ref", brands_sql)


if __name__ == "__main__": unittest.main()
