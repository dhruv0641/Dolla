import json
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID

from flowx_os.db.content import OwnedContentNotFound, RepositoryUnavailable
from flowx_os.db.storyboards import (
    InvalidStoryboardTimeline,
    StoryboardRepository,
    StoryboardVersionConflict,
)
from flowx_os.domain.content_state import InvalidContentTransition
from flowx_os.domain.storyboard import StoryboardTimeline


CONTENT_ID = UUID("64135a38-e28b-4e22-bebf-c1906761b681")
BRAND_ID = UUID("b6bb37b4-a27f-4de4-9277-45a6449aef01")
NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)
TIMELINE = StoryboardTimeline.model_validate({
    "title": "A falling apple",
    "scenes": [
        {"scene_number": 1, "start_ms": 0, "end_ms": 4_000, "beat": "Setup", "visual_prompt": "Tree"},
        {"scene_number": 2, "start_ms": 4_000, "end_ms": 8_000, "beat": "Turn", "visual_prompt": "Apple"},
    ],
})


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
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakePool:
    def __init__(self, connection):
        self.connection_value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.connection_value


class StoryboardRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def record_row(self, version=1):
        return (CONTENT_ID, version, TIMELINE.title, TIMELINE.total_duration_ms,
                TIMELINE.model_dump(mode="json"), NOW)

    def repository(self, responses):
        connection = FakeConnection(responses)
        return StoryboardRepository(FakePool(connection)), connection

    async def test_save_is_owner_scoped_append_only_and_transitions_content(self):
        repo, connection = self.repository([
            FakeCursor(one=(0, 8, "SCRIPT_READY")),
            FakeCursor(one=self.record_row()),
            FakeCursor(),
            FakeCursor(),
            FakeCursor(one=(1, "STORYBOARD_READY")),
        ])
        result = await repo.save_version(
            brand_id=BRAND_ID, content_id=CONTENT_ID, owner_user_id="owner-1",
            expected_version=0, storyboard=TIMELINE,
        )
        self.assertEqual(result.version, 1)
        self.assertEqual(result.total_duration_ms, 8_000)
        self.assertIn("b.owner_user_id = %s", connection.queries[0][0])
        self.assertIn("FOR UPDATE OF c", connection.queries[0][0])
        self.assertEqual(connection.queries[0][1], (CONTENT_ID, BRAND_ID, "owner-1"))
        self.assertIn("INSERT INTO storyboard_versions", connection.queries[1][0])
        self.assertIn("INSERT INTO scenes", connection.queries[2][0])
        self.assertEqual(connection.queries[2][1][-1], 1)
        self.assertIn("SET storyboard_version = %s", connection.queries[-1][0])
        self.assertEqual(connection.queries[-1][1][1], "STORYBOARD_READY")

    async def test_stale_expected_version_conflicts_before_any_write(self):
        repo, connection = self.repository([FakeCursor(one=(2, 8, "STORYBOARD_READY"))])
        with self.assertRaises(StoryboardVersionConflict) as caught:
            await repo.save_version(
                brand_id=BRAND_ID, content_id=CONTENT_ID, owner_user_id="owner-1",
                expected_version=1, storyboard=TIMELINE,
            )
        self.assertEqual(caught.exception.current_version, 2)
        self.assertEqual(len(connection.queries), 1)

    async def test_duration_mismatch_and_invalid_state_do_not_write(self):
        for stored_version, target, status, expected_error in [
            (0, 7, "SCRIPT_READY", InvalidStoryboardTimeline),
            (0, 8, "GENERATING", InvalidContentTransition),
        ]:
            with self.subTest(status=status):
                repo, connection = self.repository([FakeCursor(one=(stored_version, target, status))])
                with self.assertRaises(expected_error):
                    await repo.save_version(
                        brand_id=BRAND_ID, content_id=CONTENT_ID, owner_user_id="owner-1",
                        expected_version=0, storyboard=TIMELINE,
                    )
                self.assertEqual(len(connection.queries), 1)

    async def test_foreign_content_is_hidden_and_storage_errors_are_sanitized(self):
        repo, connection = self.repository([FakeCursor(one=None)])
        with self.assertRaises(OwnedContentNotFound):
            await repo.save_version(
                brand_id=BRAND_ID, content_id=CONTENT_ID, owner_user_id="other-owner",
                expected_version=0, storyboard=TIMELINE,
            )
        self.assertEqual(len(connection.queries), 1)

        repo, _ = self.repository([RuntimeError("private database text")])
        with self.assertRaises(RepositoryUnavailable) as caught:
            await repo.list_versions(brand_id=BRAND_ID, content_id=CONTENT_ID, owner_user_id="owner-1")
        self.assertNotIn("private", str(caught.exception))

    async def test_version_history_validates_persisted_snapshots(self):
        repo, connection = self.repository([
            FakeCursor(one=(1,)),
            FakeCursor(many=[self.record_row()]),
        ])
        result = await repo.list_versions(brand_id=BRAND_ID, content_id=CONTENT_ID, owner_user_id="owner-1")
        self.assertEqual([item.version for item in result], [1])
        self.assertEqual(result[0].storyboard, TIMELINE)
        self.assertIn("ORDER BY sv.version", connection.queries[1][0])

        repo, _ = self.repository([FakeCursor(one=(1,)), FakeCursor(many=[(
            CONTENT_ID, 1, "bad", 4_000, json.dumps({"invalid": True}), NOW,
        )])])
        with self.assertRaises(RepositoryUnavailable):
            await repo.list_versions(brand_id=BRAND_ID, content_id=CONTENT_ID, owner_user_id="owner-1")


if __name__ == "__main__":
    unittest.main()
