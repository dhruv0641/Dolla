from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from uuid import uuid4

from flowx_os.analytics.collection import (
    AnalyticsCollectionError,
    AnalyticsSource,
    CollectionWindow,
    MetricAvailability,
    MetricDatum,
    MetricUnavailableReason,
    PlatformMetricObservation,
    StoredMetricObservation,
)
from flowx_os.analytics.metrics import load_metric_registry
from flowx_os.analytics.snapshots import (
    SnapshotWindowState,
    WindowedSnapshotCoordinator,
    WindowedSnapshotPlan,
    WindowedSnapshotSeries,
)
from flowx_os.publishing.reconciliation import PublicationPlatform


PUBLISHED = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
REGISTRY = load_metric_registry(
    Path(__file__).resolve().parents[1] / "config" / "platform_metrics.v1.json"
)


def plan() -> WindowedSnapshotPlan:
    return WindowedSnapshotPlan(
        publication_id=uuid4(), owner_user_id="owner-1", published_at=PUBLISHED,
        metric_ids=("youtube.likes", "youtube.views"),
    )


def stored(
    value: WindowedSnapshotPlan, window: CollectionWindow, *, partial=False,
    all_missing=False, destination="channel_1",
) -> StoredMetricObservation:
    request = value.request_for(window, registry=REGISTRY)
    values = (
        MetricDatum(
            metric_id="youtube.likes",
            availability=(MetricAvailability.UNAVAILABLE if partial else MetricAvailability.AVAILABLE),
            value=None if partial else 5,
            unavailable_reason=(MetricUnavailableReason.PERMISSION_DENIED if partial else None),
        ),
        MetricDatum(
            metric_id="youtube.views", availability=MetricAvailability.AVAILABLE,
            value=20,
        ),
    )
    if all_missing:
        values = tuple(
            MetricDatum(
                metric_id=metric_id,
                availability=MetricAvailability.UNAVAILABLE,
                value=None,
                unavailable_reason=MetricUnavailableReason.FIELD_NOT_RETURNED,
            )
            for metric_id in value.metric_ids
        )
    observation = PlatformMetricObservation(
        request_id=request.request_id, publication_id=value.publication_id,
        platform=PublicationPlatform.YOUTUBE, destination_id=destination,
        remote_object_id="video_1", window=window,
        window_started_at=PUBLISHED,
        window_ended_at=PUBLISHED + window.duration,
        source=AnalyticsSource.YOUTUBE_ANALYTICS,
        observed_at=PUBLISHED + window.duration + timedelta(minutes=1),
        evidence_id=f"youtube:window:{window.value}",
        registry_version=REGISTRY.version,
        registry_fingerprint=REGISTRY.fingerprint, values=values,
    )
    return StoredMetricObservation(
        observation=observation, owner_user_id=value.owner_user_id,
        target_fingerprint="a" * 64, storage_fingerprint="b" * 64,
        created_at=observation.observed_at,
    )


class FakeCollector:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    async def collect(self, request):
        self.calls.append(request)
        return self.result


class WindowedSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def test_all_five_windows_have_deterministic_requests_and_exact_boundaries(self):
        value = plan()
        windows = tuple(CollectionWindow)
        self.assertEqual(
            windows,
            (
                CollectionWindow.ONE_HOUR,
                CollectionWindow.TWENTY_FOUR_HOURS,
                CollectionWindow.SEVENTY_TWO_HOURS,
                CollectionWindow.SEVEN_DAYS,
                CollectionWindow.TWENTY_EIGHT_DAYS,
            ),
        )
        first = tuple(value.request_for(window, registry=REGISTRY) for window in windows)
        second = tuple(value.request_for(window, registry=REGISTRY) for window in windows)
        self.assertEqual(first, second)
        self.assertEqual(len({item.request_id for item in first}), 5)
        self.assertEqual(
            value.window_ends_at(CollectionWindow.TWENTY_EIGHT_DAYS),
            PUBLISHED + timedelta(days=28),
        )

    def test_due_requests_change_only_at_exact_fixed_boundaries(self):
        value = plan()
        self.assertEqual(value.due_requests(
            registry=REGISTRY, now=PUBLISHED + timedelta(hours=1) - timedelta(microseconds=1),
        ), ())
        one = value.due_requests(
            registry=REGISTRY, now=PUBLISHED + timedelta(hours=1),
        )
        self.assertEqual(tuple(item.window for item in one), (CollectionWindow.ONE_HOUR,))
        all_due = value.due_requests(
            registry=REGISTRY, now=PUBLISHED + timedelta(days=28),
        )
        self.assertEqual(tuple(item.window for item in all_due), tuple(CollectionWindow))
        with self.assertRaises(ValueError):
            value.due_requests(registry=REGISTRY, now=datetime(2026, 1, 1))

    def test_plan_rejects_derived_or_cross_platform_metric_sets(self):
        derived = WindowedSnapshotPlan(
            publication_id=uuid4(), owner_user_id="owner-1", published_at=PUBLISHED,
            metric_ids=("youtube.engagement_rate_by_views",),
        )
        cross = WindowedSnapshotPlan(
            publication_id=uuid4(), owner_user_id="owner-1", published_at=PUBLISHED,
            metric_ids=("instagram.likes", "youtube.likes"),
        )
        for value in (derived, cross):
            with self.assertRaises(ValueError):
                value.validate_registry(REGISTRY)

    def test_series_preserves_complete_partial_due_and_future_without_zero_fill(self):
        value = plan()
        one_hour = stored(value, CollectionWindow.ONE_HOUR)
        day = stored(value, CollectionWindow.TWENTY_FOUR_HOURS, partial=True)
        series = WindowedSnapshotSeries.build(
            plan=value, registry=REGISTRY,
            now=PUBLISHED + timedelta(days=4), records=(day, one_hour),
        )
        self.assertEqual(
            tuple(item.state for item in series.windows),
            (
                SnapshotWindowState.COMPLETE,
                SnapshotWindowState.PARTIAL,
                SnapshotWindowState.DUE,
                SnapshotWindowState.FUTURE,
                SnapshotWindowState.FUTURE,
            ),
        )
        self.assertEqual(series.windows[1].unavailable_metric_ids, ("youtube.likes",))
        self.assertIsNone(day.observation.values[0].value)

    def test_series_rejects_duplicate_or_changed_lineage(self):
        value = plan()
        one_hour = stored(value, CollectionWindow.ONE_HOUR)
        with self.assertRaises(ValueError):
            WindowedSnapshotSeries.build(
                plan=value, registry=REGISTRY, now=PUBLISHED + timedelta(days=30),
                records=(one_hour, one_hour),
            )
        changed = stored(value, CollectionWindow.TWENTY_FOUR_HOURS, destination="other")
        with self.assertRaises(ValueError):
            WindowedSnapshotSeries.build(
                plan=value, registry=REGISTRY, now=PUBLISHED + timedelta(days=30),
                records=(one_hour, changed),
            )

        original = one_hour.observation
        forged_observation = PlatformMetricObservation(
            request_id=original.request_id,
            publication_id=original.publication_id,
            platform=PublicationPlatform.INSTAGRAM,
            destination_id=original.destination_id,
            remote_object_id=original.remote_object_id,
            window=original.window,
            window_started_at=original.window_started_at,
            window_ended_at=original.window_ended_at,
            source=AnalyticsSource.INSTAGRAM_GRAPH,
            observed_at=original.observed_at,
            evidence_id="instagram:forged:abc",
            registry_version=original.registry_version,
            registry_fingerprint=original.registry_fingerprint,
            values=original.values,
        )
        forged = StoredMetricObservation(
            observation=forged_observation,
            owner_user_id=one_hour.owner_user_id,
            target_fingerprint=one_hour.target_fingerprint,
            storage_fingerprint=one_hour.storage_fingerprint,
            created_at=one_hour.created_at,
        )
        with self.assertRaises(ValueError):
            WindowedSnapshotSeries.build(
                plan=value, registry=REGISTRY,
                now=PUBLISHED + timedelta(days=30), records=(forged,),
            )

    def test_series_exposes_unresolved_due_read_for_operator_review(self):
        value = plan()
        series = WindowedSnapshotSeries.build(
            plan=value, registry=REGISTRY,
            now=PUBLISHED + timedelta(hours=25),
            unresolved_windows=(CollectionWindow.ONE_HOUR,),
        )
        self.assertEqual(series.windows[0].state, SnapshotWindowState.REQUIRES_REVIEW)
        self.assertEqual(series.windows[1].state, SnapshotWindowState.DUE)
        with self.assertRaises(ValueError):
            WindowedSnapshotSeries.build(
                plan=value, registry=REGISTRY,
                now=PUBLISHED + timedelta(minutes=30),
                unresolved_windows=(CollectionWindow.ONE_HOUR,),
            )

    def test_all_missing_snapshot_remains_partial_with_null_values(self):
        value = plan()
        record = stored(value, CollectionWindow.ONE_HOUR, all_missing=True)
        series = WindowedSnapshotSeries.build(
            plan=value, registry=REGISTRY,
            now=PUBLISHED + timedelta(hours=2), records=(record,),
        )
        self.assertEqual(series.windows[0].state, SnapshotWindowState.PARTIAL)
        self.assertEqual(
            series.windows[0].unavailable_metric_ids,
            ("youtube.likes", "youtube.views"),
        )
        self.assertTrue(all(item.value is None for item in record.observation.values))

    async def test_coordinator_refuses_early_window_and_delegates_exact_request_when_due(self):
        value = plan()
        record = stored(value, CollectionWindow.ONE_HOUR)
        fake = FakeCollector(record)
        early = WindowedSnapshotCoordinator(
            collector=fake, registry=REGISTRY,
            now=lambda: PUBLISHED + timedelta(minutes=59),
        )
        with self.assertRaises(AnalyticsCollectionError) as caught:
            await early.collect(plan=value, window=CollectionWindow.ONE_HOUR)
        self.assertEqual(caught.exception.code, "WINDOW_NOT_READY")
        self.assertEqual(fake.calls, [])

        due = WindowedSnapshotCoordinator(
            collector=fake, registry=REGISTRY,
            now=lambda: PUBLISHED + timedelta(hours=1),
        )
        self.assertIs(
            await due.collect(plan=value, window=CollectionWindow.ONE_HOUR),
            record,
        )
        self.assertEqual(
            fake.calls,
            [value.request_for(CollectionWindow.ONE_HOUR, registry=REGISTRY)],
        )


if __name__ == "__main__":
    unittest.main()
