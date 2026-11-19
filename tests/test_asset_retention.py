import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flowx_os.assets.retention import AssetPurgeError, AssetPurgeService
from flowx_os.assets.storage import AssetStorageConflict, ManagedAssetStore
from flowx_os.db.asset_catalog import AssetCatalogRepository, AssetRetentionBlocked
from flowx_os.db.assets import AssetRecord
from flowx_os.domain.assets import AssetKind, AssetMetadata
from tests.test_asset_repository import ASSET_ID, CONTENT_ID, FakeCursor, FakePool, NOW, row
from tests.test_asset_catalog import UpdateCursor


class CatalogRetentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_requires_archived_unreferenced_tombstone(self):
        pool = FakePool([FakeCursor(one=(*row(), "TOMBSTONED", "ARCHIVED")), FakeCursor(one=(False,)), UpdateCursor()])
        record = await AssetCatalogRepository(pool).prepare_purge(asset_id=ASSET_ID, owner_user_id="owner")
        self.assertEqual(record.metadata.asset_id, ASSET_ID)
        self.assertIn("PURGE_PENDING", pool.connection_value.queries[-1][0])
        self.assertIn("b.owner_user_id = %s", pool.connection_value.queries[0][0])
        pool = FakePool([FakeCursor(one=(*row(), "TOMBSTONED", "ARCHIVED")), FakeCursor(one=(True,))])
        with self.assertRaises(AssetRetentionBlocked):
            await AssetCatalogRepository(pool).prepare_purge(asset_id=ASSET_ID, owner_user_id="owner")

    async def test_mark_purged_requires_pending(self):
        pool = FakePool([FakeCursor(one=("PURGE_PENDING",)), UpdateCursor()])
        self.assertTrue(await AssetCatalogRepository(pool).mark_purged(asset_id=ASSET_ID, owner_user_id="owner"))
        self.assertIn("purged_at = now()", pool.connection_value.queries[-1][0])
        pool = FakePool([FakeCursor(one=("TOMBSTONED",))])
        with self.assertRaises(AssetRetentionBlocked):
            await AssetCatalogRepository(pool).mark_purged(asset_id=ASSET_ID, owner_user_id="owner")


class FakeCatalog:
    def __init__(self, record):
        self.record = record
        self.completed = False

    async def prepare_purge(self, **kwargs):
        return self.record

    async def mark_purged(self, **kwargs):
        self.completed = True
        return True


class FailOnceCatalog(FakeCatalog):
    def __init__(self, record):
        super().__init__(record)
        self.fail_once = True

    async def mark_purged(self, **kwargs):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("database unavailable")
        return await super().mark_purged(**kwargs)


class PhysicalPurgeTests(unittest.IsolatedAsyncioTestCase):
    def _asset(self, root):
        source = root / "source.txt"
        source.write_text("retention fixture", encoding="utf-8")
        stored = ManagedAssetStore(root).store(asset_id=uuid4(), source_path=source, mime_type="text/plain")
        metadata = AssetMetadata(
            asset_id=stored.asset_id, content_id=CONTENT_ID, kind=AssetKind.OTHER,
            storage_uri=stored.storage_uri, sha256_hex=stored.sha256_hex,
            mime_type=stored.mime_type, size_bytes=stored.size_bytes,
        )
        return stored.path, AssetRecord(metadata, datetime.now(timezone.utc))

    async def test_verified_unlink_then_database_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, record = self._asset(root)
            catalog = FakeCatalog(record)
            self.assertTrue(await AssetPurgeService(storage_root=root, catalog=catalog).purge(
                asset_id=record.metadata.asset_id, owner_user_id="owner"))
            self.assertFalse(path.exists())
            self.assertTrue(catalog.completed)
            self.assertTrue(path.with_name(".purge-intent").exists())

    async def test_hash_mismatch_keeps_pending_and_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, record = self._asset(root)
            path.write_text("retention changed", encoding="utf-8")
            catalog = FakeCatalog(record)
            with self.assertRaises(AssetPurgeError):
                await AssetPurgeService(storage_root=root, catalog=catalog).purge(
                    asset_id=record.metadata.asset_id, owner_user_id="owner")
            self.assertTrue(path.exists())
            self.assertFalse(catalog.completed)

    async def test_missing_payload_keeps_pending_for_reconciliation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, record = self._asset(root)
            path.unlink()
            catalog = FakeCatalog(record)
            with self.assertRaises(AssetPurgeError):
                await AssetPurgeService(storage_root=root, catalog=catalog).purge(
                    asset_id=record.metadata.asset_id, owner_user_id="owner")
            self.assertFalse(catalog.completed)

    async def test_retry_after_unlink_and_database_failure_uses_intent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, record = self._asset(root)
            catalog = FailOnceCatalog(record)
            service = AssetPurgeService(storage_root=root, catalog=catalog)
            with self.assertRaises(RuntimeError):
                await service.purge(asset_id=record.metadata.asset_id, owner_user_id="owner")
            self.assertFalse(path.exists())
            self.assertTrue(path.with_name(".purge-intent").exists())
            self.assertTrue(await service.purge(asset_id=record.metadata.asset_id, owner_user_id="owner"))
            self.assertTrue(catalog.completed)
            self.assertTrue(path.with_name(".purge-intent").exists())
            source = root / "source.txt"
            with self.assertRaises(AssetStorageConflict):
                ManagedAssetStore(root).store(
                    asset_id=record.metadata.asset_id, source_path=source,
                    mime_type="text/plain",
                )

    async def test_partial_intent_never_authorizes_missing_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, record = self._asset(root)
            path.with_name(".purge-intent").write_bytes(b"partial")
            catalog = FakeCatalog(record)
            with self.assertRaises(AssetPurgeError):
                await AssetPurgeService(storage_root=root, catalog=catalog).purge(
                    asset_id=record.metadata.asset_id, owner_user_id="owner")
            self.assertTrue(path.exists())
            self.assertFalse(catalog.completed)


if __name__ == "__main__":
    unittest.main()
