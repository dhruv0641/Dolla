from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import unittest
from uuid import uuid4

from flowx_os.analytics.cohorts import (
    CohortAnalysisRequest,
    CohortBand,
    CohortCandidate,
    CohortExclusionReason,
    CohortReportStatus,
    CreativeCohortAnalyzer,
    CreativeFactor,
    CreativeFactorDatum,
    CreativeMetadataSnapshot,
    FactorAvailability,
    FactorUnavailableReason,
)
from flowx_os.analytics.collection import (
    AnalyticsSource,
    CollectionWindow,
    MetricAvailability,
    MetricDatum,
    PlatformMetricObservation,
    StoredMetricObservation,
)
from flowx_os.analytics.metrics import load_metric_registry
from flowx_os.publishing.reconciliation import PublicationPlatform


NOW = datetime(2026, 11, 23, 10, tzinfo=timezone.utc)
PUBLISHED = NOW - timedelta(days=2)
REGISTRY = load_metric_registry(
    Path(__file__).resolve().parents[1] / "config" / "platform_metrics.v1.json"
)


def factor_values(niche: str):
    unavailable = {
        factor: CreativeFactorDatum(
            factor, FactorAvailability.UNAVAILABLE, None,
            unavailable_reason=FactorUnavailableReason.NOT_CAPTURED,
        )
        for factor in CreativeFactor
    }
    unavailable[CreativeFactor.NICHE] = CreativeFactorDatum(
        CreativeFactor.NICHE, FactorAvailability.OBSERVED, niche,
        evidence_ref="brand:niche:v1",
    )
    unavailable[CreativeFactor.PLATFORM] = CreativeFactorDatum(
        CreativeFactor.PLATFORM, FactorAvailability.OBSERVED, "YOUTUBE",
        evidence_ref="publication:platform:v1",
    )
    unavailable[CreativeFactor.POSTING_TIME_UTC] = CreativeFactorDatum(
        CreativeFactor.POSTING_TIME_UTC, FactorAvailability.OBSERVED,
        f"D{PUBLISHED.isoweekday()}-H{PUBLISHED.hour:02d}Z",
        evidence_ref="publication:published_at:v1",
    )
    return tuple(unavailable.values())


def snapshot(publication_id, niche: str, index: int):
    return CreativeMetadataSnapshot(
        snapshot_id=uuid4(), owner_user_id="owner-1", brand_id=uuid4(),
        content_id=uuid4(), publication_id=publication_id, artifact_version=1,
        script_version=1, storyboard_version=1, platform=PublicationPlatform.YOUTUBE,
        published_at=PUBLISHED, schema_version="creative-metadata-v1",
        source_fingerprint=f"{index + 1:064x}", factors=factor_values(niche),
        created_at=NOW,
    )


def stored_observation(publication_id, value: int, index: int):
    observation = PlatformMetricObservation(
        request_id=uuid4(), publication_id=publication_id,
        platform=PublicationPlatform.YOUTUBE, destination_id="channel_1",
        remote_object_id=f"video_{index}", window=CollectionWindow.TWENTY_FOUR_HOURS,
        window_started_at=PUBLISHED,
        window_ended_at=PUBLISHED + timedelta(hours=24),
        source=AnalyticsSource.YOUTUBE_ANALYTICS, observed_at=NOW,
        evidence_id=f"youtube:cohort:{index}", registry_version=REGISTRY.version,
        registry_fingerprint=REGISTRY.fingerprint,
        values=(MetricDatum("youtube.views", MetricAvailability.AVAILABLE, value),),
    )
    return StoredMetricObservation(
        observation=observation, owner_user_id="owner-1",
        target_fingerprint=f"{100 + index:064x}",
        storage_fingerprint=f"{200 + index:064x}", created_at=NOW,
    )


def request(**changes):
    values = dict(
        request_id=uuid4(), owner_user_id="owner-1",
        definition_version="cohort-v1", factor=CreativeFactor.NICHE,
        metric_id="youtube.views", window=CollectionWindow.TWENTY_FOUR_HOURS,
        registry_version=REGISTRY.version,
        registry_fingerprint=REGISTRY.fingerprint, minimum_group_size=3,
    )
    values.update(changes)
    return CohortAnalysisRequest(**values)


class CreativeCohortTests(unittest.TestCase):
    def test_descriptive_groups_use_median_and_disclose_sample_and_exclusions(self):
        candidates = []
        for index, (niche, value) in enumerate(
            (("education", 1), ("education", 2), ("education", 1000),
             ("finance", 10), ("finance", 11), ("finance", 12))
        ):
            publication_id = uuid4()
            candidates.append(CohortCandidate(
                publication_id, "owner-1", snapshot(publication_id, niche, index),
                stored_observation(publication_id, value, index),
            ))
        missing_id = uuid4()
        candidates.append(CohortCandidate(missing_id, "owner-1", None, None))

        report = CreativeCohortAnalyzer().analyze(
            request=request(), candidates=tuple(candidates), registry=REGISTRY,
        )

        self.assertEqual(report.status, CohortReportStatus.DESCRIPTIVE)
        self.assertEqual(report.interpretation, "DESCRIPTIVE_ASSOCIATION_ONLY_NOT_CAUSAL")
        self.assertEqual(report.candidate_count, 7)
        self.assertEqual(report.included_count, 6)
        self.assertEqual(dict(report.exclusions)[CohortExclusionReason.METADATA_UNAVAILABLE], 1)
        self.assertEqual([(item.label, item.sample_size) for item in report.cohorts], [
            ("education", 3), ("finance", 3),
        ])
        self.assertEqual(report.cohorts[0].median, Decimal("2"))
        self.assertEqual(len(report.sources), 6)

    def test_posting_time_uses_versioned_weekday_hour_projection(self):
        candidates = []
        for index in range(3):
            publication_id = uuid4()
            candidates.append(CohortCandidate(
                publication_id, "owner-1", snapshot(publication_id, "education", index),
                stored_observation(publication_id, index + 1, index),
            ))
        report = CreativeCohortAnalyzer().analyze(
            request=request(factor=CreativeFactor.POSTING_TIME_UTC),
            candidates=tuple(candidates), registry=REGISTRY,
        )
        self.assertEqual(report.cohorts[0].label, f"D{PUBLISHED.isoweekday()}-H{PUBLISHED.hour:02d}Z")
        self.assertEqual(report.cohorts[0].sample_size, 3)

    def test_missing_factor_and_metric_are_excluded_not_fabricated(self):
        publication_id = uuid4()
        metadata = snapshot(publication_id, "education", 1)
        factors = tuple(
            CreativeFactorDatum(
                item.factor, FactorAvailability.UNAVAILABLE, None,
                unavailable_reason=FactorUnavailableReason.SOURCE_UNAVAILABLE,
            ) if item.factor is CreativeFactor.NICHE else item
            for item in metadata.factors
        )
        metadata = replace(metadata, factors=factors)
        candidate = CohortCandidate(
            publication_id, "owner-1", metadata,
            stored_observation(publication_id, 3, 1),
        )
        report = CreativeCohortAnalyzer().analyze(
            request=request(), candidates=(candidate,), registry=REGISTRY,
        )
        self.assertEqual(report.included_count, 0)
        self.assertEqual(dict(report.exclusions)[CohortExclusionReason.FACTOR_UNAVAILABLE], 1)

    def test_small_groups_remain_ineligible_and_non_causal(self):
        candidates = []
        for index, niche in enumerate(("education", "education", "finance")):
            publication_id = uuid4()
            candidates.append(CohortCandidate(
                publication_id, "owner-1", snapshot(publication_id, niche, index),
                stored_observation(publication_id, index + 1, index),
            ))
        report = CreativeCohortAnalyzer().analyze(
            request=request(), candidates=tuple(candidates), registry=REGISTRY,
        )
        self.assertEqual(report.status, CohortReportStatus.INSUFFICIENT_COHORTS)
        self.assertTrue(all(not item.eligible for item in report.cohorts))

    def test_mixed_owner_platform_window_and_registry_fail_closed(self):
        publication_id = uuid4()
        candidate = CohortCandidate(
            publication_id, "owner-2", snapshot(publication_id, "education", 1),
            stored_observation(publication_id, 3, 1),
        )
        with self.assertRaisesRegex(ValueError, "owner"):
            CreativeCohortAnalyzer().analyze(
                request=request(), candidates=(candidate,), registry=REGISTRY,
            )
        observation = stored_observation(publication_id, 3, 1)
        changed = replace(
            observation.observation, window=CollectionWindow.ONE_HOUR,
            window_ended_at=PUBLISHED + timedelta(hours=1),
        )
        with self.assertRaisesRegex(ValueError, "lineage"):
            CreativeCohortAnalyzer().analyze(
                request=request(), candidates=(CohortCandidate(
                    publication_id, "owner-1", snapshot(publication_id, "education", 1),
                    replace(observation, observation=changed),
                ),), registry=REGISTRY,
            )

    def test_numeric_bands_are_explicit_bounded_and_non_overlapping(self):
        with self.assertRaisesRegex(ValueError, "request"):
            request(bands=(CohortBand("a", Decimal("0"), Decimal("10")),))
        with self.assertRaisesRegex(ValueError, "overlap"):
            request(
                factor=CreativeFactor.SCRIPT_WORD_COUNT,
                bands=(
                    CohortBand("short", Decimal("0"), Decimal("100")),
                    CohortBand("long", Decimal("90"), Decimal("200")),
                ),
            )

    def test_snapshot_rejects_missing_factor_and_forged_platform(self):
        publication_id = uuid4()
        with self.assertRaisesRegex(ValueError, "snapshot"):
            replace(snapshot(publication_id, "education", 1), factors=factor_values("education")[:-1])
        factors = tuple(
            CreativeFactorDatum(
                item.factor, item.availability,
                "INSTAGRAM" if item.factor is CreativeFactor.PLATFORM else item.value,
                evidence_ref=item.evidence_ref,
                unavailable_reason=item.unavailable_reason,
            )
            for item in factor_values("education")
        )
        with self.assertRaisesRegex(ValueError, "snapshot"):
            replace(snapshot(publication_id, "education", 1), factors=factors)


if __name__ == "__main__":
    unittest.main()
