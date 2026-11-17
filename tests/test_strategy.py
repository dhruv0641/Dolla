import unittest
from uuid import uuid4

from flowx_os.agents.schemas import EvidenceReference
from flowx_os.agents.strategy import (
    IdeaBlocker,
    IdeaCandidate,
    IdeaScoreStatus,
    IdeaScoringError,
    IdeaScoringErrorCode,
    IdeaScoringProfile,
    IdeaSignals,
    IdeaWeights,
    rank_ideas,
    score_idea,
)


def make_candidate(title="Idea", *, score=80.0, evidence=True, blockers=(), idea_id=None):
    refs = ([EvidenceReference(
        citation_id=uuid4(), source_url="https://example.org/source",
        source_title="Source", excerpt="Supporting excerpt",
    )] if evidence else [])
    return IdeaCandidate(
        idea_id=idea_id or uuid4(), title=title, concept=f"Concept for {title}",
        signals=IdeaSignals(
            originality=score, audience_fit=score, evidence_strength=score if evidence else 0.0,
            production_feasibility=score, brand_alignment=score,
        ),
        evidence=refs, blockers=list(blockers),
    )


class StrategyScoringTests(unittest.TestCase):
    def test_default_weights_are_normalized_and_scoring_is_explainable(self):
        candidate = make_candidate(score=80.0)
        result = score_idea(candidate)
        self.assertAlmostEqual(sum(result.model_dump()["contributions"][i]["weight"] for i in range(5)), 1.0)
        self.assertEqual(result.score, 80.0)
        self.assertEqual(result.status, IdeaScoreStatus.READY_FOR_REVIEW)
        self.assertEqual(result.profile_version, 1)
        self.assertEqual(len(result.contributions), 5)

    def test_weighted_score_uses_configured_profile_version(self):
        profile = IdeaScoringProfile(
            version=3,
            weights=IdeaWeights(
                originality=0.10, audience_fit=0.30, evidence_strength=0.30,
                production_feasibility=0.10, brand_alignment=0.20,
            ),
        )
        candidate = IdeaCandidate(
            idea_id=uuid4(), title="Weighted", concept="Weighted idea",
            signals=IdeaSignals(
                originality=100, audience_fit=80, evidence_strength=60,
                production_feasibility=50, brand_alignment=90,
            ),
            evidence=make_candidate().evidence,
        )
        result = score_idea(candidate, profile)
        self.assertEqual(result.score, 75.0)
        self.assertEqual(result.profile_version, 3)
        self.assertEqual(
            [item.weighted_score for item in result.contributions], [10.0, 24.0, 18.0, 5.0, 18.0]
        )

    def test_missing_evidence_is_not_hidden_by_other_high_scores(self):
        candidate = make_candidate(evidence=False, score=100.0)
        result = score_idea(candidate)
        self.assertEqual(result.score, 75.0)
        self.assertEqual(result.status, IdeaScoreStatus.NEEDS_EVIDENCE)
        self.assertEqual(result.evidence_source_count, 0)

    def test_profile_can_explicitly_disable_minimum_source_gate(self):
        candidate = make_candidate(evidence=False, score=100.0)
        profile = IdeaScoringProfile(minimum_evidence_sources=0)
        result = score_idea(candidate, profile)
        self.assertEqual(result.status, IdeaScoreStatus.READY_FOR_REVIEW)
        self.assertEqual(result.evidence_source_count, 0)

    def test_evidence_signal_cannot_be_nonzero_without_sources(self):
        candidate = make_candidate(evidence=False)
        candidate = IdeaCandidate.model_copy(candidate, update={
            "signals": IdeaSignals(
                originality=80, audience_fit=80, evidence_strength=50,
                production_feasibility=80, brand_alignment=80,
            ),
        })
        with self.assertRaises(IdeaScoringError) as raised:
            score_idea(candidate)
        self.assertEqual(raised.exception.code, IdeaScoringErrorCode.INVALID_CANDIDATE)

    def test_json_candidate_accepts_string_ids_and_blocker_codes(self):
        citation_id = str(uuid4())
        candidate = IdeaCandidate.model_validate({
            "idea_id": str(uuid4()), "title": "JSON idea", "concept": "JSON concept",
            "signals": {
                "originality": 50, "audience_fit": 50, "evidence_strength": 10,
                "production_feasibility": 50, "brand_alignment": 50,
            },
            "evidence": [{
                "citation_id": citation_id, "source_url": "https://example.org/source",
                "source_title": "Source", "excerpt": "Supported excerpt",
            }],
            "blockers": ["rights_review"],
        })
        self.assertEqual(candidate.blockers, [IdeaBlocker.RIGHTS_REVIEW])

    def test_blockers_override_score_and_threshold_is_explained_by_status(self):
        blocked = score_idea(make_candidate(blockers=[IdeaBlocker.RIGHTS_REVIEW], score=100.0))
        self.assertEqual(blocked.status, IdeaScoreStatus.BLOCKED)
        low_profile = IdeaScoringProfile(minimum_eligible_score=90.0)
        below = score_idea(make_candidate(score=80.0), low_profile)
        self.assertEqual(below.status, IdeaScoreStatus.BELOW_THRESHOLD)

    def test_profile_is_revalidated_even_when_constructed_unsafely(self):
        bad_weights = IdeaWeights.model_construct(
            originality=0.1, audience_fit=0.1, evidence_strength=0.1,
            production_feasibility=0.1, brand_alignment=0.1,
        )
        bad_profile = IdeaScoringProfile.model_construct(
            version=1, weights=bad_weights, minimum_eligible_score=50.0,
            minimum_evidence_sources=1,
        )
        with self.assertRaises(IdeaScoringError) as raised:
            score_idea(make_candidate(), bad_profile)
        self.assertEqual(raised.exception.code, IdeaScoringErrorCode.INVALID_PROFILE)

    def test_ranking_is_stable_and_ready_candidates_precede_unverified_candidates(self):
        ready_z = make_candidate("Zulu", score=80, idea_id=uuid4())
        ready_a = make_candidate("Alpha", score=80, idea_id=uuid4())
        needs_evidence = make_candidate("Needs evidence", score=100, evidence=False)
        first = rank_ideas([needs_evidence, ready_z, ready_a])
        second = rank_ideas([ready_a, ready_z, needs_evidence])
        self.assertEqual([item.idea_id for item in first], [item.idea_id for item in second])
        self.assertEqual(first[0].title, "Alpha")
        self.assertEqual(first[-1].status, IdeaScoreStatus.NEEDS_EVIDENCE)

    def test_duplicate_candidate_ids_fail_ranking(self):
        idea_id = uuid4()
        with self.assertRaises(IdeaScoringError) as raised:
            rank_ideas([make_candidate("One", idea_id=idea_id), make_candidate("Two", idea_id=idea_id)])
        self.assertEqual(raised.exception.code, IdeaScoringErrorCode.DUPLICATE_IDEA_ID)


if __name__ == "__main__":
    unittest.main()
