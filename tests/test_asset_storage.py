import hashlib
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from flowx_os.assets.storage import AssetStorageConflict, AssetStorageError, ManagedAssetStore


ASSET_ID = UUID("f2c13904-9b62-4a5d-9459-617b87946132")
PNG = b"\x89PNG\r\n\x1a\n" + b"asset-payload"


class ManagedAssetStoreTests(unittest.TestCase):
    def test_stores_atomic_managed_object_with_verified_hash_and_stable_uri(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            source.write_bytes(PNG)
            store = ManagedAssetStore(root / "storage")

            first = store.store(asset_id=ASSET_ID, source_path=source, mime_type="image/png")
            second = store.store(asset_id=ASSET_ID, source_path=source, mime_type="image/png; charset=binary")

            self.assertEqual(first.path, second.path)
            self.assertEqual(first.storage_uri, f"managed://assets/{ASSET_ID.hex}/payload")
            self.assertEqual(first.sha256_hex, hashlib.sha256(PNG).hexdigest())
            self.assertEqual(first.size_bytes, len(PNG))
            self.assertEqual(first.path.read_bytes(), PNG)
            self.assertEqual(first.mime_type, "image/png")

    def test_same_asset_id_cannot_be_rebound_to_different_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "one.png"
            second = root / "two.png"
            first.write_bytes(PNG)
            second.write_bytes(b"\x89PNG\r\n\x1a\nother bytes")
            store = ManagedAssetStore(root / "storage")
            store.store(asset_id=ASSET_ID, source_path=first, mime_type="image/png")

            with self.assertRaises(AssetStorageConflict):
                store.store(asset_id=ASSET_ID, source_path=second, mime_type="image/png")

    def test_rejects_mime_mismatch_oversize_and_non_regular_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "asset.bin"
            source.write_bytes(PNG)
            store = ManagedAssetStore(root / "storage")

            with self.assertRaises(AssetStorageError):
                store.store(asset_id=ASSET_ID, source_path=source, mime_type="video/mp4")
            stored = store.store(asset_id=ASSET_ID, source_path=source, mime_type="image/png")
            self.assertEqual(stored.mime_type, "image/png")

            store = ManagedAssetStore(root / "small-storage", max_bytes=10)
            with self.assertRaises(AssetStorageError):
                store.store(asset_id=ASSET_ID, source_path=source, mime_type="image/png")

            small_store = ManagedAssetStore(root / "other-storage")
            with self.assertRaises(AssetStorageError):
                small_store.store(asset_id=ASSET_ID, source_path=root, mime_type="image/png")


if __name__ == "__main__":
    unittest.main()
