from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from uuid import uuid4

from flowx_os.analytics.cohorts import (
    CohortAnalysisRequest,
    CohortCandidate,
    CreativeCohortAnalyzer,
    CreativeFactor,
)
from flowx_os.analytics.collection import CollectionWindow
from flowx_os.analytics.metrics import load_metric_registry
from flowx_os.db.cohorts import CreativeCohortConflict, CreativeCohortRepository
from tests.test_creative_cohorts import snapshot, stored_observation


NOW = datetime(2026, 11, 23, 10, tzinfo=timezone.utc)
REGISTRY = load_metric_registry(
    Path(__file__).resolve().parents[1] / "config" / "platform_metrics.v1.json"
)


class Cursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class Connection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, query, params=None):
        self.calls.append((query, params))
        return Cursor(self.rows.pop(0) if self.rows else None)


class Pool:
    def __init__(self, connection):
        self.connection_value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.connection_value


def analysis(publication_id):
    metadata = snapshot(publication_id, "education", 1)
    observation = stored_observation(publication_id, 10, 1)
    request = CohortAnalysisRequest(
        request_id=uuid4(), owner_user_id="owner-1",
        definition_version="cohort-v1", factor=CreativeFactor.NICHE,
        metric_id="youtube.views", window=CollectionWindow.TWENTY_FOUR_HOURS,
        registry_version=REGISTRY.version,
        registry_fingerprint=REGISTRY.fingerprint,
    )
    report = CreativeCohortAnalyzer().analyze(
        request=request,
        candidates=(CohortCandidate(
            publication_id, "owner-1", metadata, observation,
        ),), registry=REGISTRY,
    )
    return metadata, request, report


class CreativeCohortRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_locks_owned_source_and_inserts_exact_fingerprint(self):
        publication_id = uuid4()
        metadata, _, _ = analysis(publication_id)
        source = (
            metadata.owner_user_id, metadata.brand_id, metadata.content_id,
            metadata.artifact_version, metadata.script_version, metadata.storyboard_version,
            metadata.platform.value, metadata.published_at, metadata.source_fingerprint,
        )
        connection = Connection([None, source, (metadata.fingerprint,)])
        result = await CreativeCohortRepository(Pool(connection)).create_snapshot(metadata)
        self.assertEqual(result, metadata)
        self.assertEqual(connection.calls[0][1], (metadata.snapshot_id, "owner-1"))
        self.assertIn("FOR SHARE OF p, c, b, ch, sv", connection.calls[1][0])
        self.assertIn("ON CONFLICT DO NOTHING", connection.calls[2][0])
        self.assertIn(metadata.fingerprint, connection.calls[2][1])

    async def test_snapshot_replay_requires_exact_evidence(self):
        publication_id = uuid4()
        metadata, _, _ = analysis(publication_id)
        connection = Connection([("f" * 64,)])
        with self.assertRaises(CreativeCohortConflict):
            await CreativeCohortRepository(Pool(connection)).create_snapshot(metadata)
        self.assertEqual(len(connection.calls), 1)

    async def test_report_is_owner_scoped_idempotent_and_path_free(self):
        publication_id = uuid4()
        _, request, report = analysis(publication_id)
        connection = Connection([None, (request.fingerprint, report.fingerprint)])
        result = await CreativeCohortRepository(Pool(connection)).create_report(
            request=request, report=report,
        )
        self.assertEqual(result, report)
        self.assertEqual(connection.calls[0][1], (request.request_id, "owner-1"))
        query, params = connection.calls[1]
        self.assertIn("ON CONFLICT DO NOTHING", query)
        self.assertNotIn("secretref://", repr(params))
        self.assertNotIn("C:\\", repr(params))
        self.assertIn("INSERT INTO cohort_analysis_sources", connection.calls[2][0])
        self.assertEqual(connection.calls[2][1][1], publication_id)

    async def test_report_replay_rejects_different_result(self):
        publication_id = uuid4()
        _, request, report = analysis(publication_id)
        connection = Connection([(request.fingerprint, "f" * 64)])
        with self.assertRaises(CreativeCohortConflict):
            await CreativeCohortRepository(Pool(connection)).create_report(
                request=request, report=report,
            )


if __name__ == "__main__":
    unittest.main()
