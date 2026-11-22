"""Tests for review and analyst agent validation boundaries."""

from datetime import datetime, timezone
from unittest import IsolatedAsyncioTestCase
from uuid import uuid4

from flowx_os.agents.analyst import (
    AnalystAssessment,
    AnalystContext,
    AnalystError,
    AnalystErrorCode,
    ContentAnalystWorkflow,
)
from flowx_os.agents.research import RetrievedSource
from flowx_os.agents.review import (
    ContentReviewWorkflow,
    ReviewAssessment,
    ReviewContext,
    ReviewDisposition,
    ReviewError,
    ReviewErrorCode,
    ReviewSeverity,
    review_context_fingerprint,
)
from flowx_os.agents.schemas import EvidenceReference, ScriptDraft, StoryboardDraft, StoryboardScene
from flowx_os.agents.script_storyboard import ScriptStoryboardDraft


def retrieved_source(*, text="Our report found a 20 percent increase in visits."):
    return RetrievedSource(
        evidence=EvidenceReference(
            citation_id=uuid4(), source_url="https://example.org/metrics",
            source_title="Quarterly report",
            excerpt="Our report found a 20 percent increase in visits.",
        ),
        retrieved_at=datetime.now(timezone.utc), text=text,
    )


def review_context():
    source = retrieved_source()
    draft = ScriptStoryboardDraft(
        script=ScriptDraft(
            title="More local visits", hook="A local trend is changing.",
            narration="Our report found a 20 percent increase in visits.",
            call_to_action="Read the report.", evidence=[source.evidence],
        ),
        storyboard=StoryboardDraft(
            title="More local visits",
            scenes=[StoryboardScene(
                scene_number=1, duration_seconds=10, visual_prompt="A simple bar chart.",
                narration="Our report found a 20 percent increase in visits.", evidence=[source.evidence],
            )],
        ),
    )
    return ReviewContext(
        content_id=uuid4(), prompt_id="content-review", prompt_version=1,
        policy_version=1, draft=draft, sources=[source],
    )


def review_assessment(context, **overrides):
    value = {
        "disposition": ReviewDisposition.READY_FOR_HUMAN_REVIEW,
        "score": 87.0,
        "summary": "The draft is ready for a person to review.",
        "findings": [{
            "category": "factuality", "severity": "info",
            "summary": "The central claim is linked to the supplied report.",
            "recommendation": "Retain the citation and verify the original report during approval.",
            "evidence_ids": [context.sources[0].evidence.citation_id],
        }],
    }
    value.update(overrides)
    return value


class FakeReviewer:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.calls = []

    async def review(self, context):
        self.calls.append(context)
        if self.error:
            raise self.error
        return self.output(context) if callable(self.output) else self.output


def analyst_context():
    return AnalystContext(
        prompt_id="performance-analysis", prompt_version=1,
        brand_goal="Increase useful visits without reducing viewer trust.",
        observations=[
            {
                "observation_id": uuid4(), "metric": "views", "value": 1000.0,
                "unit": "views", "captured_at": datetime.now(timezone.utc), "sample_count": 1000,
            },
            {
                "observation_id": uuid4(), "metric": "avg_watch_seconds", "value": 15.5,
                "unit": "seconds", "captured_at": datetime.now(timezone.utc), "sample_count": 1000,
            },
        ],
    )


def analyst_assessment(context, *, ids=None):
    return {
        "summary": "Views were measured for this observation window.",
        "findings": [{
            "title": "Watch time needs comparison",
            "observed_fact": "Average watch time was 15.5 seconds.",
            "interpretation": "A baseline is needed before calling the result strong or weak.",
            "recommendation": "Compare against a consistent prior content cohort.",
            "confidence": 0.7,
            "observation_ids": ids or [context.observations[1].observation_id],
        }],
        "data_limitations": ["No comparable baseline was supplied."],
    }


class FakeAnalyst:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.calls = []

    async def analyze(self, context):
        self.calls.append(context)
        if self.error:
            raise self.error
        return self.output(context) if callable(self.output) else self.output


class ReviewWorkflowTests(IsolatedAsyncioTestCase):
    async def test_valid_assessment_never_approves_content(self):
        context = review_context()
        provider = FakeReviewer(lambda value: review_assessment(value))
        result = await ContentReviewWorkflow(provider).run(context)
        self.assertEqual(result.assessment.disposition, ReviewDisposition.READY_FOR_HUMAN_REVIEW)
        self.assertEqual(result.context_fingerprint, review_context_fingerprint(context))
        self.assertTrue(result.human_approval_required)
        self.assertEqual(result.approval_state, "pending_human")
        self.assertFalse(result.content_approved)

    async def test_critical_finding_cannot_be_marked_ready(self):
        active = review_context()
        data = review_assessment(active, findings=[{
            "category": "safety", "severity": "critical", "summary": "Review required.",
            "recommendation": "Resolve the issue.", "evidence_ids": [],
        }])
        with self.assertRaises(ReviewError) as raised:
            await ContentReviewWorkflow(FakeReviewer(data)).run(active)
        self.assertEqual(raised.exception.code, ReviewErrorCode.INVALID_ASSESSMENT)

    async def test_factuality_findings_require_supplied_evidence(self):
        active = review_context()
        data = review_assessment(active, findings=[{
            "category": "factuality", "severity": "warning", "summary": "Check claim.",
            "recommendation": "Add supporting evidence.", "evidence_ids": [],
        }])
        with self.assertRaises(ReviewError) as raised:
            await ContentReviewWorkflow(FakeReviewer(data)).run(active)
        self.assertEqual(raised.exception.code, ReviewErrorCode.INVALID_ASSESSMENT)

    async def test_unknown_evidence_reference_is_rejected(self):
        active = review_context()
        data = review_assessment(active, findings=[{
            "category": "factuality", "severity": "warning", "summary": "Check claim.",
            "recommendation": "Verify source.", "evidence_ids": [uuid4()],
        }])
        with self.assertRaises(ReviewError) as raised:
            await ContentReviewWorkflow(FakeReviewer(data)).run(active)
        self.assertEqual(raised.exception.code, ReviewErrorCode.UNKNOWN_EVIDENCE)

    async def test_provider_cannot_mutate_trusted_evidence_ids(self):
        class MutatingReviewer:
            async def review(self, context):
                injected = retrieved_source()
                context.sources.append(injected)
                return review_assessment(context, findings=[{
                    "category": "factuality", "severity": "warning", "summary": "Check claim.",
                    "recommendation": "Verify source.", "evidence_ids": [injected.evidence.citation_id],
                }])

        with self.assertRaises(ReviewError) as raised:
            await ContentReviewWorkflow(MutatingReviewer()).run(review_context())
        self.assertEqual(raised.exception.code, ReviewErrorCode.UNKNOWN_EVIDENCE)

    async def test_invalid_input_and_provider_errors_are_safe(self):
        active = review_context()
        provider = FakeReviewer(error=RuntimeError("secret review provider detail"))
        with self.assertRaises(ReviewError) as raised:
            await ContentReviewWorkflow(provider).run({"bad": "payload"})
        self.assertEqual(raised.exception.code, ReviewErrorCode.INVALID_CONTEXT)
        with self.assertRaises(ReviewError) as raised:
            await ContentReviewWorkflow(provider).run(active)
        self.assertEqual(raised.exception.code, ReviewErrorCode.PROVIDER_FAILED)
        self.assertNotIn("secret", str(raised.exception))


class AnalystWorkflowTests(IsolatedAsyncioTestCase):
    async def test_valid_analysis_only_references_supplied_observations(self):
        context = analyst_context()
        result = await ContentAnalystWorkflow(FakeAnalyst(lambda value: analyst_assessment(value))).run(context)
        self.assertTrue(result.all_observation_references_verified)
        self.assertTrue(result.human_interpretation_required)
        self.assertEqual(result.assessment.findings[0].observation_ids[0], context.observations[1].observation_id)

    async def test_unknown_observation_is_rejected(self):
        context = analyst_context()
        provider = FakeAnalyst(lambda value: analyst_assessment(value, ids=[uuid4()]))
        with self.assertRaises(AnalystError) as raised:
            await ContentAnalystWorkflow(provider).run(context)
        self.assertEqual(raised.exception.code, AnalystErrorCode.UNKNOWN_OBSERVATION)

    async def test_invalid_metric_window_and_duplicate_ids_fail_before_provider(self):
        provider = FakeAnalyst({})
        context = analyst_context()
        payload = context.model_dump(mode="python")
        payload["observations"][0]["metric"] = "views; DROP TABLE"
        with self.assertRaises(AnalystError) as raised:
            await ContentAnalystWorkflow(provider).run(payload)
        self.assertEqual(raised.exception.code, AnalystErrorCode.INVALID_CONTEXT)
        self.assertEqual(provider.calls, [])
        payload = context.model_dump(mode="python")
        payload["observations"][1]["observation_id"] = payload["observations"][0]["observation_id"]
        with self.assertRaises(AnalystError) as raised:
            await ContentAnalystWorkflow(provider).run(payload)
        self.assertEqual(raised.exception.code, AnalystErrorCode.INVALID_CONTEXT)
        payload = context.model_dump(mode="python")
        payload["observations"][0]["captured_at"] = datetime.now()
        with self.assertRaises(AnalystError) as raised:
            await ContentAnalystWorkflow(provider).run(payload)
        self.assertEqual(raised.exception.code, AnalystErrorCode.INVALID_CONTEXT)
        self.assertEqual(provider.calls, [])

    async def test_provider_errors_and_invalid_outputs_are_sanitized(self):
        context = analyst_context()
        with self.assertRaises(AnalystError) as raised:
            await ContentAnalystWorkflow(FakeAnalyst(error=RuntimeError("secret"))).run(context)
        self.assertEqual(raised.exception.code, AnalystErrorCode.PROVIDER_FAILED)
        self.assertNotIn("secret", str(raised.exception))
        with self.assertRaises(AnalystError) as raised:
            await ContentAnalystWorkflow(FakeAnalyst({"unexpected": "secret"})).run(context)
        self.assertEqual(raised.exception.code, AnalystErrorCode.INVALID_ASSESSMENT)
        self.assertNotIn("secret", str(raised.exception))


if __name__ == "__main__":
    import unittest
    unittest.main()
