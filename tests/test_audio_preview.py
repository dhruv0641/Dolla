import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx

from flowx_os.api.main import create_app
from flowx_os.assets.audio_preview import AudioPreviewError, AudioPreviewService, parse_byte_range
from flowx_os.assets.storage import ManagedAssetStore
from flowx_os.auth.tokens import TokenVerifier
from flowx_os.db.assets import AssetRecord
from flowx_os.domain.assets import AssetKind, AssetMetadata


KEY = b"audio-preview-test-key-long-enough"
BRAND_ID = UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01")
CONTENT_ID = UUID("64135a38-e28b-4e22-bebf-c1906761b681")
NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


def _token(roles=("operator",)):
    def encoded(value):
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    now = int(time.time())
    header = encoded(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = encoded(json.dumps({
        "iss": "flowx-test", "aud": "flowx-api", "sub": "owner-1",
        "roles": list(roles), "iat": now - 1, "nbf": now - 1, "exp": now + 60,
    }).encode())
    signing_input = f"{header}.{claims}"
    signature = encoded(hmac.new(KEY, signing_input.encode("ascii"), hashlib.sha256).digest())
    return f"{signing_input}.{signature}"


def managed_audio(root: Path):
    source = root / "preview.wav"
    source.write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + bytes(range(256)) * 20)
    stored = ManagedAssetStore(root).store(
        asset_id=uuid4(), source_path=source, mime_type="audio/wav",
    )
    metadata = AssetMetadata(
        asset_id=stored.asset_id, content_id=CONTENT_ID, kind=AssetKind.NARRATION,
        storage_uri=stored.storage_uri, sha256_hex=stored.sha256_hex,
        mime_type=stored.mime_type, size_bytes=stored.size_bytes,
        media_metadata={"duration_ms": 1000, "timeline_start_ms": 0},
    )
    return stored, AssetRecord(metadata, NOW)


class FakeCatalog:
    def __init__(self, record):
        self.record = record
        self.lookups = []
        self.retirements = []

    async def get_active_audio(self, **kwargs):
        self.lookups.append(kwargs)
        return self.record

    async def tombstone(self, **kwargs):
        self.retirements.append(kwargs)
        return True


class FakeAssets:
    def __init__(self, records):
        self.records = records
        self.owners = []

    async def list_for_content(self, **kwargs):
        self.owners.append(kwargs["owner_user_id"])
        return self.records


class AudioPreviewTests(unittest.IsolatedAsyncioTestCase):
    def test_single_ranges_are_bounded_and_canonical(self):
        self.assertEqual(parse_byte_range("bytes=10-19", total=100, maximum_bytes=50), (10, 19, True))
        self.assertEqual(parse_byte_range("bytes=-10", total=100, maximum_bytes=50), (90, 99, True))
        self.assertEqual(parse_byte_range(None, total=100, maximum_bytes=100), (0, 99, False))
        for value in ("bytes=5-4", "bytes=100-", "bytes=0-1,4-5", "items=0-1"):
            with self.subTest(value=value), self.assertRaises(AudioPreviewError):
                parse_byte_range(value, total=100, maximum_bytes=50)
        with self.assertRaises(AudioPreviewError) as caught:
            parse_byte_range(None, total=101, maximum_bytes=100)
        self.assertEqual(caught.exception.code, "RANGE_REQUIRED")

    async def test_service_verifies_full_object_and_returns_only_selected_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stored, record = managed_audio(root)
            catalog = FakeCatalog(record)
            service = AudioPreviewService(
                storage_root=root, store=catalog, maximum_preview_bytes=1024,
            )
            result = await service.preview(
                asset_id=stored.asset_id, brand_id=BRAND_ID, content_id=CONTENT_ID,
                owner_user_id="owner-1", range_header="bytes=12-31",
            )
            expected = stored.path.read_bytes()[12:32]
            self.assertEqual(result.data, expected)
            self.assertEqual((result.selected_range.start, result.selected_range.end), (12, 31))
            self.assertTrue(result.partial)
            self.assertEqual(catalog.lookups[0]["owner_user_id"], "owner-1")

            stored.path.write_bytes(stored.path.read_bytes()[:-1] + b"x")
            with self.assertRaises(AudioPreviewError) as caught:
                await service.preview(
                    asset_id=stored.asset_id, brand_id=BRAND_ID, content_id=CONTENT_ID,
                    owner_user_id="owner-1", range_header="bytes=0-10",
                )
            self.assertEqual(caught.exception.code, "AUDIO_INTEGRITY_MISMATCH")

    async def test_api_inventory_preview_and_retirement_are_owner_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stored, record = managed_audio(root)
            image_id = uuid4()
            image_metadata = AssetMetadata(
                asset_id=image_id, content_id=CONTENT_ID, kind=AssetKind.THUMBNAIL,
                storage_uri=f"managed://assets/{image_id.hex}/payload",
                sha256_hex="c" * 64, mime_type="image/png", size_bytes=10,
            )
            assets = FakeAssets([record, AssetRecord(image_metadata, NOW)])
            catalog = FakeCatalog(record)
            verifier = TokenVerifier(KEY, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
            with patch("flowx_os.api.main.AssetRepository", return_value=assets), patch(
                "flowx_os.api.main.AssetCatalogRepository", return_value=catalog,
            ):
                app = create_app(
                    token_verifier=verifier, database_pool=object(), storage_root=root,
                )
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test",
                    headers={"Authorization": f"Bearer {_token()}"},
                ) as client:
                    base = f"/api/v1/brands/{BRAND_ID}/content/{CONTENT_ID}/audio-assets"
                    inventory = await client.get(base)
                    preview = await client.get(
                        f"{base}/{stored.asset_id}/preview", headers={"Range": "bytes=0-31"},
                    )
                    retired = await client.post(
                        f"{base}/{stored.asset_id}/retire",
                        json={
                            "created_before": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                            "reason": "operator archive",
                        },
                    )
            self.assertEqual(inventory.status_code, 200)
            self.assertEqual(len(inventory.json()), 1)
            self.assertNotIn("storage_uri", inventory.text)
            self.assertNotIn("sha256", inventory.text)
            self.assertEqual((preview.status_code, len(preview.content)), (206, 32))
            self.assertEqual(preview.headers["content-range"], f"bytes 0-31/{stored.size_bytes}")
            self.assertEqual(preview.headers["cache-control"], "private, no-store")
            self.assertEqual(retired.json(), {"retired": True})
            self.assertEqual(assets.owners, ["owner-1"])
            self.assertTrue(all(call["owner_user_id"] == "owner-1" for call in catalog.lookups))
            self.assertEqual(catalog.retirements[0]["owner_user_id"], "owner-1")

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test",
                headers={"Authorization": f"Bearer {_token(('reviewer',))}"},
            ) as reviewer:
                denied = await reviewer.post(
                    f"{base}/{stored.asset_id}/retire",
                    json={
                        "created_before": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                        "reason": "operator archive",
                    },
                )
            self.assertEqual(denied.status_code, 403)


if __name__ == "__main__":
    unittest.main()
