import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID

from flowx_os.db.content import (
    ContentRepository,
    InvalidContentTransition,
    OwnedBrandNotFound,
    OwnedContentNotFound,
)
from flowx_os.domain.content_state import ContentStatus


class FakeCursor:
    def __init__(self, one=None, many=None):
        self.one = one
        self.many = many or []

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
        return self.responses.pop(0)


class FakePool:
    def __init__(self, connection):
        self.value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.value


class ContentRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_brand_list_scopes_query_to_owner(self):
        now = datetime(2026, 11, 18, tzinfo=timezone.utc)
        row = (UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01"), "Studio", "owner-1",
               "Asia/Kolkata", "", "", now, now)
        connection = FakeConnection([FakeCursor(many=[row])])
        result = await ContentRepository(FakePool(connection)).list_brands(owner_user_id="owner-1")
        query, params = connection.queries[0]
        self.assertIn("WHERE owner_user_id = %s", query)
        self.assertEqual(params, ("owner-1",))
        self.assertEqual(result[0].owner_user_id, "owner-1")

    async def test_content_insert_selects_only_owned_brand(self):
        content_id = UUID("64135a38-e28b-4e22-bebf-c1906761b681")
        brand_id = UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01")
        now = datetime(2026, 11, 18, tzinfo=timezone.utc)
        row = (content_id, brand_id, "Launch", "Idea", None, None,
               "en-IN", 32, 3, "IDEA", now)
        connection = FakeConnection([FakeCursor(one=row)])
        result = await ContentRepository(FakePool(connection)).create_content(
            brand_id=brand_id, owner_user_id="owner-1", title="Launch", idea_text="Idea",
            topic=None, audience_segment=None, language="en-IN", target_duration_seconds=32,
            priority=3,
        )
        query, params = connection.queries[0]
        self.assertIn("b.id = %s AND b.owner_user_id = %s", query)
        self.assertEqual(params[-2:], (brand_id, "owner-1"))
        self.assertEqual(result.brand_id, brand_id)

    async def test_foreign_brand_is_reported_as_not_found_without_leaking_owner(self):
        connection = FakeConnection([FakeCursor(one=None)])
        with self.assertRaises(OwnedBrandNotFound):
            await ContentRepository(FakePool(connection)).create_content(
                brand_id=UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01"),
                owner_user_id="owner-1", title="Launch", idea_text="Idea", topic=None,
                audience_segment=None, language="en-IN", target_duration_seconds=32, priority=3,
            )

    async def test_transition_locks_owned_content_and_updates_expected_state(self):
        content_id = UUID("64135a38-e28b-4e22-bebf-c1906761b681")
        brand_id = UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01")
        now = datetime(2026, 11, 18, tzinfo=timezone.utc)
        updated = (content_id, brand_id, "Launch", "Idea", None, None,
                   "en-IN", 32, 3, "RESEARCHED", now)
        connection = FakeConnection([FakeCursor(one=("IDEA",)), FakeCursor(one=updated)])
        result = await ContentRepository(FakePool(connection)).transition_content(
            brand_id=brand_id, content_id=content_id, owner_user_id="owner-1",
            target_status=ContentStatus.RESEARCHED,
        )
        select_sql, select_params = connection.queries[0]
        update_sql, update_params = connection.queries[1]
        self.assertIn("b.owner_user_id = %s", select_sql)
        self.assertIn("FOR UPDATE OF c", select_sql)
        self.assertEqual(select_params, (content_id, brand_id, "owner-1"))
        self.assertIn("AND c.status = %s", update_sql)
        self.assertEqual(update_params[-1], "IDEA")
        self.assertEqual(result.typed_status, ContentStatus.RESEARCHED)

    async def test_transition_rejects_invalid_edge_without_mutating(self):
        connection = FakeConnection([FakeCursor(one=("IDEA",))])
        with self.assertRaises(InvalidContentTransition):
            await ContentRepository(FakePool(connection)).transition_content(
                brand_id=UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01"),
                content_id=UUID("64135a38-e28b-4e22-bebf-c1906761b681"),
                owner_user_id="owner-1", target_status=ContentStatus.PUBLISHED,
            )
        self.assertEqual(len(connection.queries), 1)

    async def test_transition_hides_foreign_owned_content(self):
        connection = FakeConnection([FakeCursor(one=None)])
        with self.assertRaises(OwnedContentNotFound):
            await ContentRepository(FakePool(connection)).transition_content(
                brand_id=UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01"),
                content_id=UUID("64135a38-e28b-4e22-bebf-c1906761b681"),
                owner_user_id="other-owner", target_status=ContentStatus.RESEARCHED,
            )

    async def test_generic_transition_cannot_change_workflow_managed_states(self):
        for target in (ContentStatus.SCHEDULED, ContentStatus.PARTIALLY_PUBLISHED, ContentStatus.PUBLISHED):
            with self.subTest(target=target):
                connection = FakeConnection([FakeCursor(one=("READY",))])
                with self.assertRaises(InvalidContentTransition):
                    await ContentRepository(FakePool(connection)).transition_content(
                        brand_id=UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01"),
                        content_id=UUID("64135a38-e28b-4e22-bebf-c1906761b681"),
                        owner_user_id="owner-1", target_status=target,
                    )
                self.assertEqual(len(connection.queries), 1)


if __name__ == "__main__":
    unittest.main()
