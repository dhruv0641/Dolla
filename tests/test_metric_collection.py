from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from uuid import uuid4

from flowx_os.analytics.collection import (
    AnalyticsCollectionError,
    AnalyticsSource,
    CollectionWindow,
    MetricAvailability,
    MetricCollectionPolicy,
    MetricCollectionRequest,
    MetricCollectionStatus,
    MetricCollectionTarget,
    MetricDatum,
    MetricUnavailableReason,
    PlatformMetricCollector,
    PlatformMetricObservation,
    StoredMetricObservation,
)
from flowx_os.analytics.metrics import load_metric_registry
from flowx_os.publishing.reconciliation import PublicationPlatform


NOW = datetime(2026, 11, 23, 10, tzinfo=timezone.utc)
REGISTRY = load_metric_registry(
    Path(__file__).resolve().parents[1] / "config" / "platform_metrics.v1.json"
)


def request(*metric_ids: str) -> MetricCollectionRequest:
    return MetricCollectionRequest(
        request_id=uuid4(), publication_id=uuid4(), owner_user_id="owner-1",
        window=CollectionWindow.ONE_HOUR,
        metric_ids=tuple(metric_ids or ("youtube.views", "youtube.likes")),
    )


def target(value: MetricCollectionRequest) -> MetricCollectionTarget:
    published = NOW - timedelta(hours=2)
    return MetricCollectionTarget(
        request_id=value.request_id, publication_id=value.publication_id,
        owner_user_id=value.owner_user_id, platform=PublicationPlatform.YOUTUBE,
        publication_state_version=7, publication_request_fingerprint="a" * 64,
        channel_id=uuid4(), destination_id="channel_1",
        destination_fingerprint="b" * 64,
        credentials_ref="secretref://vault/youtube/owner-1",
        remote_object_id="video_1", published_at=published,
        window=value.window, window_started_at=published,
        window_ended_at=published + value.window.duration,
        source=AnalyticsSource.YOUTUBE_ANALYTICS,
        registry_version=REGISTRY.version,
        registry_fingerprint=REGISTRY.fingerprint,
        metric_ids=value.metric_ids,
    )


def observation(
    value: MetricCollectionRequest, exact: MetricCollectionTarget,
    *, values: tuple[MetricDatum, ...] | None = None,
    observed_at: datetime = NOW,
) -> PlatformMetricObservation:
    if values is None:
        values = tuple(
            MetricDatum(
                metric_id=metric_id, availability=MetricAvailability.AVAILABLE,
                value=index + 1,
            )
            for index, metric_id in enumerate(value.metric_ids)
        )
    return PlatformMetricObservation(
        request_id=value.request_id, publication_id=value.publication_id,
        platform=exact.platform, destination_id=exact.destination_id,
        remote_object_id=exact.remote_object_id, window=exact.window,
        window_started_at=exact.window_started_at,
        window_ended_at=exact.window_ended_at, source=exact.source,
        observed_at=observed_at, evidence_id="youtube:request:abc",
        registry_version=exact.registry_version,
        registry_fingerprint=exact.registry_fingerprint, values=values,
    )


def stored(value: MetricCollectionRequest, exact: MetricCollectionTarget) -> StoredMetricObservation:
    return StoredMetricObservation(
        observation=observation(value, exact), owner_user_id=value.owner_user_id,
        target_fingerprint=exact.fingerprint, created_at=NOW,
    )


class FakeStore:
    def __init__(self, *, existing=None, exact=None):
        self.existing = existing
        self.exact = exact
        self.calls = []

    async def get_existing(self, value):
        self.calls.append(("get", value))
        return self.existing

    async def reserve(self, value, *, registry):
        self.calls.append(("reserve", value, registry))
        return self.exact

    async def record(self, *, request, target, observation, registry):
        self.calls.append(("record", request, target, observation, registry))
        return StoredMetricObservation(
            observation=observation, owner_user_id=request.owner_user_id,
            target_fingerprint=target.fingerprint, created_at=NOW,
        )


class FakeProvider:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def collect(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def collector(store, provider=None, *, enabled=True, now=NOW):
    return PlatformMetricCollector(
        store=store, provider=provider, registry=REGISTRY,
        policy=MetricCollectionPolicy(enabled=enabled), now=lambda: now,
    )


class MetricCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_default_and_missing_provider_fail_before_remote_read(self):
        value = request()
        exact = target(value)
        provider = FakeProvider(observation(value, exact))
        with self.assertRaises(AnalyticsCollectionError) as disabled:
            await collector(FakeStore(exact=exact), provider, enabled=False).collect(value)
        self.assertEqual(disabled.exception.code, "CAPABILITY_DISABLED")
        self.assertEqual(provider.calls, [])

        with self.assertRaises(AnalyticsCollectionError) as missing:
            await collector(FakeStore(exact=exact), None).collect(value)
        self.assertEqual(missing.exception.code, "PROVIDER_UNAVAILABLE")

    async def test_exact_replay_returns_stored_evidence_even_when_disabled(self):
        value = request()
        exact = target(value)
        record = stored(value, exact)
        store = FakeStore(existing=record, exact=exact)
        self.assertIs(await collector(store, enabled=False).collect(value), record)
        self.assertEqual([call[0] for call in store.calls], ["get"])

        conflicting = MetricCollectionRequest(
            request_id=value.request_id, publication_id=value.publication_id,
            owner_user_id=value.owner_user_id, window=value.window,
            metric_ids=("youtube.views",),
        )
        with self.assertRaises(AnalyticsCollectionError) as caught:
            await collector(FakeStore(existing=record), enabled=False).collect(conflicting)
        self.assertEqual(caught.exception.code, "REPLAY_CONFLICT")

    async def test_collects_exact_bounded_identity_and_records_explicit_values(self):
        value = request()
        exact = target(value)
        remote = observation(value, exact)
        provider = FakeProvider(remote)
        store = FakeStore(exact=exact)
        result = await collector(store, provider).collect(value)
        self.assertEqual(result.observation.fingerprint, remote.fingerprint)
        self.assertEqual(result.observation.status, MetricCollectionStatus.OK)
        self.assertEqual(provider.calls[0]["credentials_ref"], exact.credentials_ref)
        self.assertEqual(provider.calls[0]["metric_ids"], value.metric_ids)
        self.assertEqual([call[0] for call in store.calls], ["get", "reserve", "record"])

    async def test_unavailable_value_requires_reason_and_is_never_zero_filled(self):
        value = request()
        exact = target(value)
        values = (
            MetricDatum(
                metric_id="youtube.likes", availability=MetricAvailability.UNAVAILABLE,
                value=None, unavailable_reason=MetricUnavailableReason.PERMISSION_DENIED,
            ),
            MetricDatum(
                metric_id="youtube.views", availability=MetricAvailability.AVAILABLE,
                value=0,
            ),
        )
        result = await collector(
            FakeStore(exact=exact), FakeProvider(observation(value, exact, values=values)),
        ).collect(value)
        self.assertEqual(result.observation.status, MetricCollectionStatus.PARTIAL)
        self.assertIsNone(result.observation.values[0].value)
        self.assertEqual(result.observation.values[1].value, 0)
        with self.assertRaises(ValueError):
            MetricDatum(
                metric_id="youtube.likes", availability=MetricAvailability.UNAVAILABLE,
                value=0, unavailable_reason=MetricUnavailableReason.PERMISSION_DENIED,
            )

    async def test_missing_extra_or_wrong_identity_evidence_is_rejected(self):
        value = request()
        exact = target(value)
        missing = observation(value, exact, values=(
            MetricDatum(
                metric_id="youtube.views", availability=MetricAvailability.AVAILABLE,
                value=2,
            ),
        ))
        with self.assertRaises(AnalyticsCollectionError) as caught:
            await collector(FakeStore(exact=exact), FakeProvider(missing)).collect(value)
        self.assertEqual(caught.exception.code, "OBSERVATION_MISMATCH")

        wrong = PlatformMetricObservation(
            request_id=value.request_id, publication_id=value.publication_id,
            platform=exact.platform, destination_id="other_channel",
            remote_object_id=exact.remote_object_id, window=exact.window,
            window_started_at=exact.window_started_at,
            window_ended_at=exact.window_ended_at, source=exact.source,
            observed_at=NOW, evidence_id="youtube:request:abc",
            registry_version=exact.registry_version,
            registry_fingerprint=exact.registry_fingerprint,
            values=observation(value, exact).values,
        )
        with self.assertRaises(AnalyticsCollectionError) as caught:
            await collector(FakeStore(exact=exact), FakeProvider(wrong)).collect(value)
        self.assertEqual(caught.exception.code, "OBSERVATION_MISMATCH")

    async def test_invalid_units_derived_metrics_and_stale_evidence_fail_closed(self):
        value = request()
        exact = target(value)
        wrong_unit = observation(value, exact, values=(
            MetricDatum(
                metric_id="youtube.likes", availability=MetricAvailability.AVAILABLE,
                value=1.5,
            ),
            MetricDatum(
                metric_id="youtube.views", availability=MetricAvailability.AVAILABLE,
                value=2,
            ),
        ))
        with self.assertRaises(AnalyticsCollectionError) as caught:
            await collector(FakeStore(exact=exact), FakeProvider(wrong_unit)).collect(value)
        self.assertEqual(caught.exception.code, "OBSERVATION_INVALID")

        derived_request = request("youtube.engagement_rate_by_views")
        derived_target = target(derived_request)
        with self.assertRaises(AnalyticsCollectionError) as caught:
            await collector(
                FakeStore(exact=derived_target),
                FakeProvider(observation(derived_request, derived_target)),
            ).collect(derived_request)
        self.assertEqual(caught.exception.code, "METRIC_NOT_COLLECTIBLE")

        stale = observation(value, exact, observed_at=NOW - timedelta(hours=1))
        with self.assertRaises(AnalyticsCollectionError) as caught:
            await collector(FakeStore(exact=exact), FakeProvider(stale)).collect(value)
        self.assertEqual(caught.exception.code, "OBSERVATION_STALE")

    async def test_incomplete_window_and_provider_failure_do_not_record(self):
        value = request()
        exact = target(value)
        store = FakeStore(exact=exact)
        provider = FakeProvider(observation(value, exact))
        with self.assertRaises(AnalyticsCollectionError) as caught:
            await collector(
                store, provider, now=exact.window_ended_at - timedelta(minutes=5),
            ).collect(value)
        self.assertEqual(caught.exception.code, "WINDOW_NOT_READY")
        self.assertEqual(provider.calls, [])
        self.assertNotIn("record", [call[0] for call in store.calls])

        for private in (
            RuntimeError("token=private"),
            AnalyticsCollectionError("PROVIDER_FAILURE", "token=private"),
        ):
            with self.assertRaises(AnalyticsCollectionError) as caught:
                await collector(FakeStore(exact=exact), FakeProvider(error=private)).collect(value)
            self.assertEqual(caught.exception.code, "PROVIDER_FAILURE")
            self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

