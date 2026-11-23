from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import unittest
from uuid import uuid4

from flowx_os.community.analysis import (
    CommunityAnalysisError,
    CommunityAnalysisRequest,
    CommunityAnalyzer,
    CommunityCommentEvidence,
    CommunityEvidenceSnapshot,
)
from flowx_os.community.comments import CommentState
from flowx_os.db.community_analysis import CommunityAnalysisRepository
from flowx_os.publishing.reconciliation import PublicationPlatform


NOW = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, payload=None):
        self.payload = payload

    async def fetchone(self):
        return self.payload

    async def fetchall(self):
        return [] if self.payload is None else list(self.payload)


class FakeConnection:
    def __init__(self, payloads=()):
        self.payloads = list(payloads)
        self.calls = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, query, params=None):
        self.calls.append((query, params))
        return FakeCursor(self.payloads.pop(0) if self.payloads else None)


class FakePool:
    def __init__(self, connection):
        self.value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.value


def request(publication_id=None):
    return CommunityAnalysisRequest(
        uuid4(), "owner-1", publication_id or uuid4(), NOW,
    )


def run_row(value, *, status="COMPLETE"):
    return (
        uuid4(), value.publication_id, value.owner_user_id, "YOUTUBE",
        "a" * 64, status, NOW - timedelta(minutes=1),
    )


def comment_row(value, *, deleted=False):
    return (
        uuid4(), value.publication_id, "comment_deleted" if deleted else "comment_1",
        ("d" if deleted else "b") * 64, None if deleted else "Great tutorial",
        "DELETED" if deleted else "ACTIVE", NOW - timedelta(minutes=2),
    )


def evidence(value, run, rows):
    return CommunityEvidenceSnapshot(
        publication_id=value.publication_id, owner_user_id=value.owner_user_id,
        platform=PublicationPlatform(run[3]), ingestion_sync_id=run[0],
        ingestion_target_fingerprint=run[4], ingestion_completed_at=run[6],
        comments=tuple(CommunityCommentEvidence(
            version_id=row[0], publication_id=row[1], remote_comment_id=row[2],
            comment_fingerprint=row[3], text=row[4], state=CommentState(row[5]),
            provider_updated_at=row[6],
        ) for row in rows),
    )


def report_row(report):
    return (
        report.request_id, report.owner_user_id, report.publication_id,
        report.request_fingerprint, report.ingestion_sync_id,
        report.ingestion_target_fingerprint, report.source_snapshot_fingerprint,
        report.theme_taxonomy_version, report.safety_policy_version,
        report.status.value, report.total_comment_count,
        report.analyzed_comment_count, report.deleted_comment_count,
        report.review_required_count, len(report.clusters), report.requested_at,
        report.created_at, report.report_fingerprint,
        report.outbound_action_authorized,
    )


class CommunityAnalysisRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_snapshot_is_owner_scoped_and_requires_latest_complete_run(self):
        value = request()
        run = run_row(value)
        rows = [comment_row(value), comment_row(value, deleted=True)]
        connection = FakeConnection([run, rows])
        snapshot = await CommunityAnalysisRepository(FakePool(connection)).load_snapshot(
            value, maximum_comments=10,
        )
        self.assertEqual(snapshot.ingestion_sync_id, run[0])
        self.assertEqual(len(snapshot.comments), 2)
        query, params = connection.calls[0]
        self.assertIn("ORDER BY r.created_at DESC, r.sync_id DESC", query)
        self.assertEqual(params, (value.publication_id, value.owner_user_id))
        self.assertEqual(connection.calls[1][1], (value.publication_id, 11))

        incomplete = FakeConnection([run_row(value, status="ACTIVE")])
        with self.assertRaises(CommunityAnalysisError) as raised:
            await CommunityAnalysisRepository(FakePool(incomplete)).load_snapshot(
                value, maximum_comments=10,
            )
        self.assertEqual(raised.exception.code, "INGESTION_NOT_COMPLETE")

    async def test_snapshot_limit_fails_closed_without_truncation(self):
        value = request()
        run = run_row(value)
        rows = [comment_row(value), comment_row(value, deleted=True)]
        with self.assertRaises(CommunityAnalysisError) as raised:
            await CommunityAnalysisRepository(FakePool(FakeConnection([run, rows]))).load_snapshot(
                value, maximum_comments=1,
            )
        self.assertEqual(raised.exception.code, "COMMENT_LIMIT_EXCEEDED")

    async def test_persist_rechecks_locked_snapshot_and_writes_typed_children(self):
        value = request()
        run = run_row(value)
        rows = [comment_row(value), comment_row(value, deleted=True)]
        source = evidence(value, run, rows)
        report = CommunityAnalyzer._build_report(
            request=value, snapshot=source, now=NOW + timedelta(seconds=1),
        )
        payloads = [
            None, (value.publication_id,), run, rows, (value.request_id,),
            *[(item.comment_version_id,) for item in report.classifications],
            *[(item.theme.value,) for item in report.clusters],
        ]
        connection = FakeConnection(payloads)
        stored = await CommunityAnalysisRepository(FakePool(connection)).persist(
            value, source, report,
        )
        self.assertEqual(stored, report)
        sql = "\n".join(call[0] for call in connection.calls)
        self.assertIn("FOR UPDATE OF p", sql)
        self.assertIn("community_analysis_reports", sql)
        self.assertIn("community_comment_classifications", sql)
        self.assertIn("community_theme_clusters", sql)

    async def test_exact_existing_report_hydrates_without_reclassification(self):
        value = request()
        run = run_row(value)
        rows = [comment_row(value)]
        source = evidence(value, run, rows)
        report = CommunityAnalyzer._build_report(
            request=value, snapshot=source, now=NOW + timedelta(seconds=1),
        )
        classifications = [(
            item.comment_version_id, item.remote_comment_id, item.comment_fingerprint,
            item.theme.value, item.theme_rule_id, item.safety_category.value,
            item.safety_severity.value, list(item.safety_rule_ids),
            item.requires_human_review, item.classification_fingerprint,
        ) for item in report.classifications]
        clusters = [(
            item.theme.value, item.member_count, item.review_required_count,
            list(item.classification_fingerprints), item.cluster_fingerprint,
        ) for item in report.clusters]
        connection = FakeConnection([report_row(report), classifications, clusters])
        stored = await CommunityAnalysisRepository(FakePool(connection)).get_existing(value)
        self.assertEqual(stored, report)
        self.assertEqual(connection.calls[0][1], (value.request_id, value.owner_user_id))


if __name__ == "__main__":
    unittest.main()
