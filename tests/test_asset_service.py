import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from flowx_os.assets.service import AssetIngestService
from flowx_os.db.assets import AssetRecord
from flowx_os.db.content import OwnedContentNotFound
from flowx_os.domain.assets import AssetKind


ASSET_ID = UUID("f2c13904-9b62-4a5d-9459-617b87946132")
CONTENT_ID = UUID("64135a38-e28b-4e22-bebf-c1906761b681")
BRAND_ID = UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01")
NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
PNG = b"\x89PNG\r\n\x1a\n" + b"asset-payload"


class RecordingRepository:
    def __init__(self):
        self.calls = []
        self.lineage_checks = []

    async def assert_lineage(self, **kwargs):
        self.lineage_checks.append(kwargs)

    async def register(self, *, brand_id, owner_user_id, metadata):
        self.calls.append((brand_id, owner_user_id, metadata))
        return AssetRecord(metadata, NOW)


class DenyingRepository(RecordingRepository):
    async def assert_lineage(self, **kwargs):
        raise OwnedContentNotFound("content not found")


class AssetIngestServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_stores_verified_bytes_then_registers_exact_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            source.write_bytes(PNG)
            repository = RecordingRepository()
            service = AssetIngestService(storage_root=root / "managed", repository=repository)

            result = await service.ingest(
                asset_id=ASSET_ID,
                source_path=source,
                mime_type="image/png",
                brand_id=BRAND_ID,
                content_id=CONTENT_ID,
                owner_user_id="owner-1",
                kind=AssetKind.THUMBNAIL,
                media_metadata={"width": 1080},
            )

            self.assertEqual(result.metadata.sha256_hex, repository.calls[0][2].sha256_hex)
            self.assertEqual(repository.calls[0][0:2], (BRAND_ID, "owner-1"))
            self.assertEqual(repository.lineage_checks[0]["content_id"], CONTENT_ID)
            self.assertEqual(repository.calls[0][2].storage_uri, f"managed://assets/{ASSET_ID.hex}/payload")
            self.assertEqual((root / "managed" / "assets" / ASSET_ID.hex / "payload").read_bytes(), PNG)

    async def test_invalid_kind_or_lineage_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            source.write_bytes(PNG)
            repository = RecordingRepository()
            service = AssetIngestService(storage_root=root / "managed", repository=repository)
            with self.assertRaises(ValueError):
                await service.ingest(
                    asset_id=ASSET_ID,
                    source_path=source,
                    mime_type="image/png",
                    brand_id=BRAND_ID,
                    content_id=CONTENT_ID,
                    owner_user_id="owner-1",
                    kind=AssetKind.NARRATION,
                )
            self.assertEqual(repository.calls, [])
            self.assertEqual(repository.lineage_checks, [])
            self.assertFalse((root / "managed" / "assets" / ASSET_ID.hex / "payload").exists())

    async def test_unauthorized_lineage_is_rejected_before_file_placement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            source.write_bytes(PNG)
            service = AssetIngestService(
                storage_root=root / "managed", repository=DenyingRepository(),
            )
            with self.assertRaises(OwnedContentNotFound):
                await service.ingest(
                    asset_id=ASSET_ID,
                    source_path=source,
                    mime_type="image/png",
                    brand_id=BRAND_ID,
                    content_id=CONTENT_ID,
                    owner_user_id="unauthorized",
                    kind=AssetKind.THUMBNAIL,
                )
            self.assertFalse((root / "managed" / "assets" / ASSET_ID.hex / "payload").exists())


if __name__ == "__main__":
    unittest.main()
