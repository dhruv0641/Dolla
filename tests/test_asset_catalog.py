import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flowx_os.db.asset_catalog import AssetCatalogRepository, AssetRetentionBlocked
from flowx_os.db.content import OwnedContentNotFound
from tests.test_asset_repository import (
    ASSET_ID, BRAND_ID, CONTENT_ID, FakeCursor, FakePool, NOW, row,
)


class UpdateCursor(FakeCursor):
    rowcount = 1


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_enforces_owner_and_bounded_keyset(self):
        other = row()
        pool = FakePool([FakeCursor(many=[other, other])])
        result = await AssetCatalogRepository(pool).search(
            owner_user_id="owner", brand_id=BRAND_ID, limit=1,
        )
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.next_cursor, (NOW, ASSET_ID))
        query, params = pool.connection_value.queries[0]
        self.assertIn("b.owner_user_id = %s", query)
        self.assertIn("a.retention_state = 'ACTIVE'", query)
        self.assertEqual(params, ("owner", BRAND_ID, 2))
        with self.assertRaises(ValueError):
            await AssetCatalogRepository(pool).search(owner_user_id="owner", limit=101)

    async def test_retention_rejects_foreign_asset_and_active_content(self):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        pool = FakePool([FakeCursor(one=None)])
        with self.assertRaises(OwnedContentNotFound):
            await AssetCatalogRepository(pool).tombstone(
                asset_id=ASSET_ID, owner_user_id="owner", created_before=cutoff,
                reason="operator archive",
            )
        query, params = pool.connection_value.queries[0]
        self.assertIn("b.owner_user_id = %s", query)
        self.assertIn("FOR UPDATE OF a, c", query)
        self.assertEqual(params, (ASSET_ID, "owner"))

        pool = FakePool([FakeCursor(one=("ACTIVE", NOW, CONTENT_ID, "PUBLISHED"))])
        with self.assertRaises(AssetRetentionBlocked):
            await AssetCatalogRepository(pool).tombstone(
                asset_id=ASSET_ID, owner_user_id="owner", created_before=cutoff,
                reason="operator archive",
            )
        self.assertEqual(len(pool.connection_value.queries), 1)

    async def test_retention_blocks_refs_and_is_idempotent(self):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        pool = FakePool([
            FakeCursor(one=("ACTIVE", NOW, CONTENT_ID, "ARCHIVED")),
            FakeCursor(one=(True,)),
        ])
        with self.assertRaises(AssetRetentionBlocked):
            await AssetCatalogRepository(pool).tombstone(
                asset_id=ASSET_ID, owner_user_id="owner", created_before=cutoff,
                reason="operator archive",
            )
        self.assertEqual(len(pool.connection_value.queries), 2)
        pool = FakePool([FakeCursor(one=("TOMBSTONED", NOW, CONTENT_ID, "ARCHIVED"))])
        self.assertFalse(await AssetCatalogRepository(pool).tombstone(
            asset_id=ASSET_ID, owner_user_id="owner", created_before=cutoff,
            reason="operator archive",
        ))

    async def test_retention_updates_only_eligible_owned_asset(self):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        pool = FakePool([
            FakeCursor(one=("ACTIVE", NOW, CONTENT_ID, "ARCHIVED")),
            FakeCursor(one=(False,)), UpdateCursor(),
        ])
        self.assertTrue(await AssetCatalogRepository(pool).tombstone(
            asset_id=ASSET_ID, owner_user_id="owner", created_before=cutoff,
            reason="operator archive",
        ))
        query, params = pool.connection_value.queries[-1]
        self.assertIn("retention_state = 'TOMBSTONED'", query)
        self.assertEqual(params, ("operator archive", "owner", ASSET_ID))

    async def test_retention_requires_explicit_past_cutoff(self):
        with self.assertRaises(ValueError):
            await AssetCatalogRepository(FakePool([])).tombstone(
                asset_id=uuid4(), owner_user_id="owner",
                created_before=datetime.now(timezone.utc) + timedelta(minutes=1),
                reason="operator archive",
            )


if __name__ == "__main__":
    unittest.main()
