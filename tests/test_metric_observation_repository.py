from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import unittest
from uuid import uuid4

from flowx_os.analytics.collection import (
    AnalyticsSource,
    CollectionWindow,
    MetricAvailability,
    MetricCollectionRequest,
    MetricDatum,
    PlatformMetricObservation,
)
from flowx_os.analytics.metrics import load_metric_registry
from flowx_os.db.analytics import (
    MetricObservationConflict,
    MetricObservationRepository,
)
from pathlib import Path


NOW = datetime(2026, 11, 23, 10, tzinfo=timezone.utc)
REGISTRY = load_metric_registry(
    Path(__file__).resolve().parents[1] / "config" / "platform_metrics.v1.json"
)


class FakeCursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, query, params=None):
        self.calls.append((query, params))
        return FakeCursor(self.rows.pop(0) if self.rows else None)


class FakePool:
    def __init__(self, connection):
        self.value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.value


def request():
    return MetricCollectionRequest(
        request_id=uuid4(), publication_id=uuid4(), owner_user_id="owner-1",
        window=CollectionWindow.ONE_HOUR,
        metric_ids=("youtube.likes", "youtube.views"),
    )


def target_row(value, *, version=3, remote="video_1"):
    destination = "channel_1"
    credentials = "secretref://os/youtube-owner-1"
    return (
        value.publication_id, value.owner_user_id, "YOUTUBE", version,
        "a" * 64, uuid4(), destination,
        hashlib.sha256(f"{destination}|{credentials}".encode()).hexdigest(),
        credentials, remote, NOW - timedelta(hours=2),
    )


def observation(value, exact, *, likes=1):
    return PlatformMetricObservation(
        request_id=value.request_id, publication_id=value.publication_id,
        platform=exact.platform, destination_id=exact.destination_id,
        remote_object_id=exact.remote_object_id, window=exact.window,
        window_started_at=exact.window_started_at,
        window_ended_at=exact.window_ended_at,
        source=AnalyticsSource.YOUTUBE_ANALYTICS, observed_at=NOW,
        evidence_id="youtube:request:abc", registry_version=REGISTRY.version,
        registry_fingerprint=REGISTRY.fingerprint,
        values=(
            MetricDatum("youtube.likes", MetricAvailability.AVAILABLE, likes),
            MetricDatum("youtube.views", MetricAvailability.AVAILABLE, 12),
        ),
    )


def attempt_row(value, exact, *, status="RESERVED"):
    return (
        value.publication_id, value.owner_user_id, value.fingerprint,
        exact.fingerprint, value.window.value, list(value.metric_ids),
        REGISTRY.version, REGISTRY.fingerprint, status,
    )


def record_row(value, exact, remote):
    return (
        value.request_id, value.publication_id, value.owner_user_id,
        exact.platform.value, exact.destination_id, exact.remote_object_id,
        exact.window.value, exact.window_started_at, exact.window_ended_at,
        exact.source.value, remote.observed_at, remote.evidence_id,
        REGISTRY.version, REGISTRY.fingerprint,
        [item.canonical() for item in remote.values],
        exact.fingerprint, "c" * 64, NOW,
    )


class MetricObservationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_reservation_is_owner_scoped_and_requires_verified_publication(self):
        value = request()
        row = target_row(value)
        connection = FakeConnection([row, None, (value.request_id,)])
        exact = await MetricObservationRepository(FakePool(connection)).reserve(
            value, registry=REGISTRY,
        )
        query, params = connection.calls[0]
        self.assertEqual(params, (value.publication_id, value.owner_user_id))
        self.assertIn("p.status = 'PUBLISHED'", query)
        self.assertIn("ch.enabled = true", query)
        self.assertIn("permissions_status = 'VALID'", query)
        self.assertIn("FOR UPDATE OF p", query)
        self.assertEqual(exact.remote_object_id, "video_1")
        self.assertIn("analytics_metric_collection_attempts", connection.calls[2][0])
        self.assertNotIn(exact.credentials_ref, connection.calls[2][1])

    async def test_reserved_replay_returns_same_target_without_duplicate_insert(self):
        value = request()
        row = target_row(value)
        exact = MetricObservationRepository._target(row, request=value, registry=REGISTRY)
        connection = FakeConnection([row, attempt_row(value, exact)])
        replay = await MetricObservationRepository(FakePool(connection)).reserve(
            value, registry=REGISTRY,
        )
        self.assertEqual(replay, exact)
        self.assertFalse(any("INSERT INTO analytics_metric_collection_attempts" in q for q, _ in connection.calls))

    async def test_get_existing_is_owner_scoped_and_parses_explicit_values(self):
        value = request()
        exact = MetricObservationRepository._target(
            target_row(value), request=value, registry=REGISTRY,
        )
        remote = observation(value, exact)
        connection = FakeConnection([record_row(value, exact, remote)])
        stored = await MetricObservationRepository(FakePool(connection)).get_existing(value)
        self.assertEqual(stored.observation.fingerprint, remote.fingerprint)
        self.assertEqual(connection.calls[0][1], (value.request_id, value.owner_user_id))

    async def test_record_rechecks_locked_target_and_persists_no_credentials(self):
        value = request()
        row = target_row(value)
        exact = MetricObservationRepository._target(row, request=value, registry=REGISTRY)
        remote = observation(value, exact)
        returned = record_row(value, exact, remote)
        connection = FakeConnection([
            None, row, attempt_row(value, exact), returned, (value.request_id,),
        ])
        stored = await MetricObservationRepository(FakePool(connection)).record(
            request=value, target=exact, observation=remote, registry=REGISTRY,
        )
        self.assertEqual(stored.observation.fingerprint, remote.fingerprint)
        insert_query, insert_params = connection.calls[3]
        self.assertIn("ON CONFLICT (request_id) DO NOTHING", insert_query)
        self.assertEqual(insert_query.count("%s"), len(insert_params))
        self.assertNotIn(exact.credentials_ref, insert_params)
        self.assertNotIn(remote.fingerprint, insert_params)
        self.assertIn("status = 'RECORDED'", connection.calls[4][0])

    async def test_changed_locked_target_and_changed_replay_conflict(self):
        value = request()
        row = target_row(value)
        exact = MetricObservationRepository._target(row, request=value, registry=REGISTRY)
        remote = observation(value, exact)
        changed_row = target_row(value, version=4)
        connection = FakeConnection([None, changed_row])
        with self.assertRaises(MetricObservationConflict):
            await MetricObservationRepository(FakePool(connection)).record(
                request=value, target=exact, observation=remote, registry=REGISTRY,
            )
        self.assertFalse(any("INSERT INTO analytics_metric_observations" in q for q, _ in connection.calls))

        stored = record_row(value, exact, observation(value, exact, likes=99))
        connection = FakeConnection([stored])
        with self.assertRaises(MetricObservationConflict):
            await MetricObservationRepository(FakePool(connection)).record(
                request=value, target=exact, observation=remote, registry=REGISTRY,
            )

    async def test_same_request_for_different_publication_conflicts(self):
        value = request()
        exact = MetricObservationRepository._target(
            target_row(value), request=value, registry=REGISTRY,
        )
        remote = observation(value, exact)
        row = list(record_row(value, exact, remote))
        row[1] = uuid4()
        with self.assertRaises(MetricObservationConflict):
            await MetricObservationRepository(
                FakePool(FakeConnection([tuple(row)]))
            ).get_existing(value)

    async def test_repository_rejects_wrong_units_before_sql(self):
        value = request()
        exact = MetricObservationRepository._target(
            target_row(value), request=value, registry=REGISTRY,
        )
        remote = PlatformMetricObservation(
            request_id=value.request_id, publication_id=value.publication_id,
            platform=exact.platform, destination_id=exact.destination_id,
            remote_object_id=exact.remote_object_id, window=exact.window,
            window_started_at=exact.window_started_at,
            window_ended_at=exact.window_ended_at, source=exact.source,
            observed_at=NOW, evidence_id="youtube:request:abc",
            registry_version=REGISTRY.version,
            registry_fingerprint=REGISTRY.fingerprint,
            values=(
                MetricDatum("youtube.likes", MetricAvailability.AVAILABLE, 1.5),
                MetricDatum("youtube.views", MetricAvailability.AVAILABLE, 12),
            ),
        )
        connection = FakeConnection()
        with self.assertRaises(ValueError):
            await MetricObservationRepository(FakePool(connection)).record(
                request=value, target=exact, observation=remote, registry=REGISTRY,
            )
        self.assertEqual(connection.calls, [])


if __name__ == "__main__":
    unittest.main()
