import copy
import json
from pathlib import Path
import tempfile
import unittest

from flowx_os.analytics.metrics import (
    MetricDefinitionError,
    MetricKind,
    MetricUnit,
    MissingValuePolicy,
    load_metric_registry,
)
from flowx_os.publishing.reconciliation import PublicationPlatform


REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "platform_metrics.v1.json"


class MetricDefinitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_metric_registry(REGISTRY_PATH)
        self.payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    def write(self, payload) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "registry.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_checked_in_registry_is_versioned_complete_and_stable(self):
        self.assertEqual(self.registry.version, "platform-metrics-v1")
        self.assertEqual(len(self.registry.definitions), 22)
        self.assertEqual(
            self.registry.fingerprint,
            "b994293e90e26358aa2ad15628be4a7b6fac7f53e035bf189b76c16452f6a7e5",
        )
        self.assertEqual(
            {item.platform for item in self.registry.definitions},
            set(PublicationPlatform),
        )
        self.assertTrue(all(
            item.platform_only
            and item.missing_value_policy is MissingValuePolicy.UNAVAILABLE
            for item in self.registry.definitions
        ))

    def test_platform_view_semantics_and_units_are_not_equated(self):
        youtube = self.registry.require("youtube.views")
        instagram = self.registry.require("instagram.total_views")
        facebook = self.registry.require("facebook.reel_initial_plays")
        self.assertEqual(
            (youtube.raw_name, instagram.raw_name, facebook.raw_name),
            ("views", "total_views_count", "blue_reels_play_count"),
        )
        self.assertTrue(all(item.unit is MetricUnit.COUNT for item in (youtube, instagram, facebook)))
        self.assertTrue(all(item.platform_only for item in (youtube, instagram, facebook)))
        self.assertEqual(
            self.registry.require("facebook.reel_average_watch_ms").unit,
            MetricUnit.MILLISECONDS,
        )
        self.assertEqual(
            self.registry.require("youtube.watch_time_minutes").unit,
            MetricUnit.MINUTES,
        )

    def test_derived_metrics_bind_raw_inputs_denominator_and_calculation_version(self):
        value = self.registry.require("youtube.engagement_rate_by_views")
        self.assertIs(value.kind, MetricKind.DERIVED)
        self.assertEqual(value.denominator, "youtube.views")
        self.assertEqual(value.calculation_version, "engagement-rate-v1")
        self.assertEqual(
            value.inputs,
            ("youtube.likes", "youtube.comments", "youtube.shares", "youtube.views"),
        )
        self.assertTrue(all(
            self.registry.require(metric_id).kind is MetricKind.RAW
            for metric_id in value.inputs
        ))

    def test_fingerprint_is_independent_of_registry_entry_order(self):
        payload = copy.deepcopy(self.payload)
        payload["metrics"].reverse()
        self.assertEqual(
            load_metric_registry(self.write(payload)).fingerprint,
            self.registry.fingerprint,
        )

    def test_unknown_fields_duplicates_and_cross_platform_inputs_fail_closed(self):
        unknown = copy.deepcopy(self.payload)
        unknown["metrics"][0]["unexpected"] = True
        duplicate = copy.deepcopy(self.payload)
        duplicate["metrics"].append(copy.deepcopy(duplicate["metrics"][0]))
        cross_platform = copy.deepcopy(self.payload)
        derived = next(
            item for item in cross_platform["metrics"]
            if item["metric_id"] == "youtube.engagement_rate_by_views"
        )
        derived["inputs"][0] = "instagram.likes"
        for value in (unknown, duplicate, cross_platform):
            with self.assertRaises(MetricDefinitionError):
                load_metric_registry(self.write(value))

    def test_unsafe_sources_missing_policy_and_false_equivalence_are_rejected(self):
        for field, value in (
            ("source_reference", "https://example.com/private"),
            ("missing_value_policy", "ZERO"),
            ("platform_only", False),
            ("label", "unsafe\u202evalue"),
        ):
            payload = copy.deepcopy(self.payload)
            payload["metrics"][0][field] = value
            with self.assertRaises(MetricDefinitionError):
                load_metric_registry(self.write(payload))

    def test_malformed_json_and_unknown_metric_are_safe_errors(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "bad.json"
        path.write_text("{", encoding="utf-8")
        with self.assertRaises(MetricDefinitionError):
            load_metric_registry(path)
        with self.assertRaisesRegex(MetricDefinitionError, "unavailable"):
            self.registry.require("youtube.not_real")


if __name__ == "__main__":
    unittest.main()
