from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest
from uuid import uuid4

from flowx_os.community.analysis import CommunityTheme, ThemeCluster
from flowx_os.community.insights import (
    CommunityInsightError, CommunityInsightPolicy, CommunityInsightRequest,
    CommunityInsightService, CommunityInsightSource, ResearchPriority,
)

NOW = datetime(2026, 11, 24, 2, 30, tzinfo=timezone.utc)


def cluster(theme, count=2, review=0, character="a"):
    fingerprints = tuple(sorted(character * 64 for _ in range(count)))
    # Repeated classification fingerprints cannot occur in a real cluster, but
    # ThemeCluster validates only ordering/count; use unique tails for count > 1.
    fingerprints = tuple((character * 63) + str(index) for index in range(count))
    fingerprints = tuple(sorted(fingerprints))
    import hashlib
    cluster_id = hashlib.sha256("|".join((
        str(REQUEST_ID), theme.value, str(count), str(review), ",".join(fingerprints),
    )).encode()).hexdigest()
    return ThemeCluster(theme, count, review, fingerprints, cluster_id)


REQUEST_ID = uuid4()


def source(publication_id, owner="owner-1"):
    return CommunityInsightSource(
        owner_user_id=owner, publication_id=publication_id,
        analysis_request_id=REQUEST_ID, analysis_report_fingerprint="b" * 64,
        source_snapshot_fingerprint="c" * 64,
        analysis_created_at=NOW - timedelta(minutes=1), total_comment_count=5,
        review_required_count=1,
        clusters=tuple(sorted((
            cluster(CommunityTheme.FEATURE_REQUEST, 3, 0, "d"),
            cluster(CommunityTheme.COMPLAINT, 2, 1, "e"),
        ), key=lambda item: item.theme.value)),
    )


class FakeStore:
    def __init__(self, value, existing=None):
        self.value = value
        self.existing = existing
        self.loads = 0
        self.persisted = None

    async def get_existing(self, request):
        return self.existing

    async def load_source(self, request):
        self.loads += 1
        return self.value

    async def persist(self, request, value, record):
        self.persisted = record
        return record


class CommunityInsightTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_fails_before_source_read(self):
        publication_id = uuid4()
        store = FakeStore(source(publication_id))
        request = CommunityInsightRequest(uuid4(), "owner-1", publication_id, NOW)
        with self.assertRaises(CommunityInsightError) as raised:
            await CommunityInsightService(store).propose(request, now=NOW)
        self.assertEqual(raised.exception.code, "INSIGHTS_DISABLED")
        self.assertEqual(store.loads, 0)

    async def test_builds_bounded_review_only_inert_proposals(self):
        publication_id = uuid4()
        store = FakeStore(source(publication_id))
        request = CommunityInsightRequest(uuid4(), "owner-1", publication_id, NOW)
        result = await CommunityInsightService(
            store, CommunityInsightPolicy(enabled=True),
        ).propose(request, now=NOW)
        self.assertEqual(len(result.proposals), 2)
        by_theme = {item.theme: item for item in result.proposals}
        self.assertEqual(by_theme[CommunityTheme.COMPLAINT].priority, ResearchPriority.HIGH)
        self.assertEqual(by_theme[CommunityTheme.FEATURE_REQUEST].priority, ResearchPriority.MEDIUM)
        self.assertTrue(all(item.requires_human_review for item in result.proposals))
        self.assertTrue(all(not item.research_execution_authorized for item in result.proposals))
        self.assertFalse(result.external_browsing_authorized)
        self.assertFalse(result.model_execution_authorized)
        self.assertFalse(result.provider_action_authorized)
        self.assertFalse(result.account_action_authorized)
        self.assertFalse(result.publishing_authorized)
        self.assertFalse(result.spend_authorized)
        self.assertFalse(result.flow_authorized)
        self.assertEqual(store.persisted, result)

    async def test_exact_replay_avoids_source_read(self):
        publication_id = uuid4()
        value = source(publication_id)
        request = CommunityInsightRequest(uuid4(), "owner-1", publication_id, NOW)
        first = await CommunityInsightService(
            FakeStore(value), CommunityInsightPolicy(enabled=True),
        ).propose(request, now=NOW)
        replay_store = FakeStore(value, existing=first)
        replay = await CommunityInsightService(
            replay_store, CommunityInsightPolicy(enabled=True),
        ).propose(request, now=NOW + timedelta(minutes=1))
        self.assertIs(replay, first)
        self.assertEqual(replay_store.loads, 0)

    async def test_cross_owner_stale_and_future_sources_fail_closed(self):
        publication_id = uuid4()
        request = CommunityInsightRequest(uuid4(), "owner-1", publication_id, NOW)
        with self.assertRaises(CommunityInsightError) as owner_error:
            await CommunityInsightService(
                FakeStore(source(publication_id, "owner-2")),
                CommunityInsightPolicy(enabled=True),
            ).propose(request, now=NOW)
        self.assertEqual(owner_error.exception.code, "SOURCE_IDENTITY_MISMATCH")
        future = replace(source(publication_id), analysis_created_at=NOW + timedelta(seconds=1))
        with self.assertRaises(CommunityInsightError) as stale_error:
            await CommunityInsightService(
                FakeStore(future), CommunityInsightPolicy(enabled=True),
            ).propose(request, now=NOW)
        self.assertEqual(stale_error.exception.code, "REQUEST_PRECEDES_SOURCE")

    async def test_store_cannot_change_exact_result(self):
        publication_id = uuid4()
        value = source(publication_id)
        request = CommunityInsightRequest(uuid4(), "owner-1", publication_id, NOW)

        class BadStore(FakeStore):
            async def persist(self, request, value, record):
                return replace(record, owner_user_id="owner-2")

        with self.assertRaises((CommunityInsightError, ValueError)):
            await CommunityInsightService(
                BadStore(value), CommunityInsightPolicy(enabled=True),
            ).propose(request, now=NOW)


if __name__ == "__main__":
    unittest.main()
