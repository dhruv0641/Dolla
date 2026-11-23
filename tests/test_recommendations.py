from dataclasses import replace
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
from flowx_os.analytics.recommendations import (
    AllocationStrategy,
    AssociationDirection,
    ExperimentPlanner,
    ExperimentProposalRequest,
    ExperimentProposalStatus,
    RecommendationEngine,
    RecommendationError,
    RecommendationRequest,
    StopRule,
)
from tests.test_creative_cohorts import snapshot, stored_observation


NOW = datetime(2026, 11, 23, 18, tzinfo=timezone.utc)
REGISTRY = load_metric_registry(
    Path(__file__).resolve().parents[1] / "config" / "platform_metrics.v1.json"
)


def descriptive_analysis():
    analysis_request = CohortAnalysisRequest(
        request_id=uuid4(), owner_user_id="owner-1",
        definition_version="cohort-v1", factor=CreativeFactor.NICHE,
        metric_id="youtube.views", window=CollectionWindow.TWENTY_FOUR_HOURS,
        registry_version=REGISTRY.version,
        registry_fingerprint=REGISTRY.fingerprint,
        minimum_group_size=3,
    )
    candidates = []
    for index, (label, value) in enumerate((
        ("education", 10), ("education", 12), ("education", 14),
        ("finance", 20), ("finance", 22), ("finance", 24),
    )):
        publication_id = uuid4()
        candidates.append(CohortCandidate(
            publication_id, "owner-1", snapshot(publication_id, label, index),
            stored_observation(publication_id, value, index),
        ))
    report = CreativeCohortAnalyzer().analyze(
        request=analysis_request, candidates=tuple(candidates), registry=REGISTRY,
    )
    return analysis_request, report


def recommendation_evidence(**request_changes):
    analysis_request, report = descriptive_analysis()
    values = dict(
        recommendation_id=uuid4(), owner_user_id="owner-1",
        report_request_id=analysis_request.request_id,
        report_fingerprint=report.fingerprint,
        definition_version="recommendation-v1",
        control_label="education", treatment_label="finance", created_at=NOW,
    )
    values.update(request_changes)
    request = RecommendationRequest(**values)
    recommendation = RecommendationEngine().propose(
        request=request, analysis_request=analysis_request,
        report=report, registry=REGISTRY,
    )
    return analysis_request, report, request, recommendation


class RecommendationTests(unittest.TestCase):
    def test_recommendation_cites_exact_report_sources_and_discloses_limits(self):
        analysis_request, report, request, recommendation = recommendation_evidence()

        self.assertEqual(recommendation.request_fingerprint, request.fingerprint)
        self.assertEqual(recommendation.report_request_fingerprint, analysis_request.fingerprint)
        self.assertEqual(recommendation.report_fingerprint, report.fingerprint)
        self.assertEqual(recommendation.sources, report.sources)
        self.assertEqual(recommendation.disclosed_cohorts, report.cohorts)
        self.assertEqual(recommendation.exclusions, report.exclusions)
        self.assertEqual(recommendation.direction, AssociationDirection.TREATMENT_MEDIAN_HIGHER)
        self.assertIn("NOT_CAUSAL", recommendation.interpretation)
        self.assertIn("NO_GUARANTEED_WINNER", recommendation.interpretation)
        self.assertEqual(recommendation.metric_id, "youtube.views")
        self.assertEqual(recommendation.platform.value, "YOUTUBE")
        self.assertEqual(recommendation.window.value, "24H")

    def test_mismatched_owner_report_and_weak_evidence_fail_closed(self):
        analysis_request, report = descriptive_analysis()
        wrong_owner = RecommendationRequest(
            recommendation_id=uuid4(), owner_user_id="owner-2",
            report_request_id=analysis_request.request_id,
            report_fingerprint=report.fingerprint,
            definition_version="recommendation-v1",
            control_label="education", treatment_label="finance", created_at=NOW,
        )
        with self.assertRaisesRegex(RecommendationError, "unavailable or mismatched"):
            RecommendationEngine().propose(
                request=wrong_owner, analysis_request=analysis_request,
                report=report, registry=REGISTRY,
            )
        bad_fingerprint = RecommendationRequest(
            recommendation_id=uuid4(), owner_user_id="owner-1",
            report_request_id=analysis_request.request_id,
            report_fingerprint="f" * 64,
            definition_version="recommendation-v1",
            control_label="education", treatment_label="finance", created_at=NOW,
        )
        with self.assertRaisesRegex(RecommendationError, "unavailable or mismatched"):
            RecommendationEngine().propose(
                request=bad_fingerprint, analysis_request=analysis_request,
                report=report, registry=REGISTRY,
            )

        small_request = replace(analysis_request, request_id=uuid4(), minimum_group_size=4)
        candidates = []
        for index, label in enumerate(("education", "education", "finance", "finance")):
            publication_id = uuid4()
            candidates.append(CohortCandidate(
                publication_id, "owner-1", snapshot(publication_id, label, index),
                stored_observation(publication_id, index + 1, index),
            ))
        weak_report = CreativeCohortAnalyzer().analyze(
            request=small_request, candidates=tuple(candidates), registry=REGISTRY,
        )
        weak = replace(
            bad_fingerprint, report_request_id=small_request.request_id,
            report_fingerprint=weak_report.fingerprint,
        )
        with self.assertRaisesRegex(RecommendationError, "unavailable or mismatched"):
            RecommendationEngine().propose(
                request=weak, analysis_request=small_request,
                report=weak_report, registry=REGISTRY,
            )

    def test_experiment_is_one_variable_fixed_sample_and_inert(self):
        _, _, _, recommendation = recommendation_evidence()
        request = ExperimentProposalRequest(
            proposal_id=uuid4(), owner_user_id="owner-1",
            recommendation_id=recommendation.recommendation_id,
            recommendation_fingerprint=recommendation.fingerprint,
            definition_version="experiment-v1", minimum_sample_per_arm=10,
            target_sample_per_arm=20, created_at=NOW + timedelta(minutes=1),
        )
        proposal = ExperimentPlanner().propose(
            request=request, recommendation=recommendation,
        )
        data = proposal.canonical()

        self.assertEqual(data["single_variable"], CreativeFactor.NICHE.value)
        self.assertEqual(proposal.allocation, AllocationStrategy.BALANCED_FIXED_1_TO_1)
        self.assertEqual(
            proposal.stop_rule, StopRule.FIXED_SAMPLE_NO_EARLY_EFFICACY_STOP,
        )
        self.assertEqual(proposal.control_target_size, 20)
        self.assertEqual(proposal.treatment_target_size, 20)
        self.assertEqual(
            proposal.status, ExperimentProposalStatus.DRAFT_REQUIRES_HUMAN_APPROVAL,
        )
        self.assertTrue(data["human_approval_required"])
        for key in (
            "execution_authorized", "generation_authorized", "spend_authorized",
            "account_connection_authorized", "scheduling_authorized",
            "upload_authorized", "publishing_authorized",
        ):
            self.assertFalse(data[key])
        self.assertFalse(hasattr(ExperimentPlanner, "execute"))

    def test_allocation_safety_and_replay_inputs_cannot_be_weakened(self):
        _, _, _, recommendation = recommendation_evidence()
        with self.assertRaisesRegex(RecommendationError, "request"):
            ExperimentProposalRequest(
                proposal_id=uuid4(), owner_user_id="owner-1",
                recommendation_id=recommendation.recommendation_id,
                recommendation_fingerprint=recommendation.fingerprint,
                definition_version="experiment-v1", minimum_sample_per_arm=10,
                target_sample_per_arm=9, created_at=NOW,
            )
        request = ExperimentProposalRequest(
            proposal_id=uuid4(), owner_user_id="owner-1",
            recommendation_id=recommendation.recommendation_id,
            recommendation_fingerprint=recommendation.fingerprint,
            definition_version="experiment-v1", minimum_sample_per_arm=3,
            target_sample_per_arm=3, created_at=NOW + timedelta(minutes=1),
        )
        proposal = ExperimentPlanner().propose(
            request=request, recommendation=recommendation,
        )
        with self.assertRaisesRegex(RecommendationError, "proposal"):
            replace(proposal, treatment_target_size=4)
        with self.assertRaisesRegex(RecommendationError, "proposal"):
            replace(proposal, safety_rules=("CONTINUE_ON_UNKNOWN_SPEND",))
        with self.assertRaisesRegex(RecommendationError, "mismatched"):
            ExperimentPlanner().propose(
                request=replace(request, recommendation_fingerprint="e" * 64),
                recommendation=recommendation,
            )


if __name__ == "__main__":
    unittest.main()
