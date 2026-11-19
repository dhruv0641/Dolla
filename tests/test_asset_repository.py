import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID

from flowx_os.db.assets import AssetConflict, AssetRepository, InvalidAssetLineage
from flowx_os.db.content import OwnedContentNotFound, RepositoryUnavailable
from flowx_os.domain.assets import AssetKind, AssetMetadata


ASSET_ID = UUID("f2c13904-9b62-4a5d-9459-617b87946132")
CONTENT_ID = UUID("64135a38-e28b-4e22-bebf-c1906761b681")
BRAND_ID = UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01")
SCENE_ID = UUID("1de51411-a9b3-4596-b752-eeb3cc647941")
JOB_ID = UUID("d468282b-9f29-4da4-b32c-2dc80749fe61")
NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
HASH = "a" * 64
URI = f"managed://assets/{ASSET_ID.hex}/payload"


class FakeCursor:
    def __init__(self, one=None, many=None):
        self.one = one
        self.many = list(many or [])

    async def fetchone(self):
        return self.one

    async def fetchall(self):
        return self.many


class FakeConnection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query, params=None):
        self.queries.append((query, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakePool:
    def __init__(self, responses):
        self.connection_value = FakeConnection(responses)

    @asynccontextmanager
    async def connection(self):
        yield self.connection_value


def metadata(**updates):
    data = {
        "asset_id": ASSET_ID,
        "content_id": CONTENT_ID,
        "kind": AssetKind.RAW_FLOW_CLIP,
        "storage_uri": URI,
        "sha256_hex": HASH,
        "mime_type": "video/mp4",
        "size_bytes": 21,
        "media_metadata": {"width": 1080},
        "scene_id": SCENE_ID,
        "source_job_id": JOB_ID,
    }
    data.update(updates)
    return AssetMetadata.model_validate(data)


def row(value=None):
    value = value or metadata()
    return (
        value.asset_id, value.content_id, value.scene_id, value.kind.value,
        value.storage_uri, value.sha256_hex, value.mime_type, value.size_bytes,
        value.media_metadata, value.source_job_id, NOW,
    )


class AssetRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_checks_owner_scene_job_and_returns_verified_record(self):
        pool = FakePool([
            FakeCursor(one=(1,)),
            FakeCursor(one=(1,)),
            FakeCursor(one=(1,)),
            FakeCursor(one=row()),
        ])
        repo = AssetRepository(pool)

        result = await repo.register(brand_id=BRAND_ID, owner_user_id="owner-1", metadata=metadata())

        self.assertEqual(result.metadata, metadata())
        self.assertEqual(result.created_at, NOW)
        self.assertIn("b.owner_user_id = %s", pool.connection_value.queries[0][0])
        self.assertIn("ON CONFLICT (id) DO NOTHING", pool.connection_value.queries[3][0])
        self.assertEqual(pool.connection_value.queries[2][1], (JOB_ID, SCENE_ID, CONTENT_ID))

    async def test_repeated_same_asset_id_is_idempotent_but_rebinding_conflicts(self):
        for existing_metadata, expected in [(metadata(), None), (metadata(sha256_hex="b" * 64), AssetConflict)]:
            pool = FakePool([
                FakeCursor(one=(1,)), FakeCursor(one=(1,)), FakeCursor(one=(1,)),
                FakeCursor(), FakeCursor(one=row(existing_metadata)),
            ])
            repo = AssetRepository(pool)
            if expected:
                with self.assertRaises(expected):
                    await repo.register(brand_id=BRAND_ID, owner_user_id="owner-1", metadata=metadata())
            else:
                result = await repo.register(brand_id=BRAND_ID, owner_user_id="owner-1", metadata=metadata())
                self.assertEqual(result.metadata, metadata())

    async def test_owner_scope_and_scene_mismatch_fail_closed(self):
        repo = AssetRepository(FakePool([FakeCursor(one=None)]))
        with self.assertRaises(OwnedContentNotFound):
            await repo.register(brand_id=BRAND_ID, owner_user_id="other-owner", metadata=metadata())

        pool = FakePool([FakeCursor(one=(1,)), FakeCursor(one=None)])
        with self.assertRaises(InvalidAssetLineage):
            await AssetRepository(pool).register(
                brand_id=BRAND_ID, owner_user_id="owner-1", metadata=metadata(),
            )
        self.assertEqual(len(pool.connection_value.queries), 2)

    async def test_asset_history_is_owner_scoped_and_ordered(self):
        pool = FakePool([
            FakeCursor(one=(1,)), FakeCursor(one=(1,)), FakeCursor(many=[row()]),
        ])
        results = await AssetRepository(pool).list_for_content(
            brand_id=BRAND_ID, content_id=CONTENT_ID,
            owner_user_id="owner-1", scene_id=SCENE_ID,
        )
        self.assertEqual([item.metadata.asset_id for item in results], [ASSET_ID])
        self.assertIn("ORDER BY a.created_at, a.id", pool.connection_value.queries[2][0])
        self.assertIn("a.scene_id = %s", pool.connection_value.queries[2][0])

    async def test_database_errors_are_sanitized(self):
        repo = AssetRepository(FakePool([RuntimeError("private database details")]))
        with self.assertRaises(RepositoryUnavailable) as caught:
            await repo.list_for_content(brand_id=BRAND_ID, content_id=CONTENT_ID, owner_user_id="owner-1")
        self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
