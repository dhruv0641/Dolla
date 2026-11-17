"""Tests for the provider-neutral script/storyboard boundary."""

from datetime import datetime, timezone
from unittest import IsolatedAsyncioTestCase
from uuid import uuid4

from flowx_os.agents.research import RetrievedSource
from flowx_os.agents.schemas import EvidenceReference, StrategyCandidate
from flowx_os.agents.script_storyboard import (
    ScriptStoryboardContext,
    ScriptStoryboardError,
    ScriptStoryboardErrorCode,
    ScriptStoryboardWorkflow,
)


def source(*, citation_id=None, text="Urban gardens improve access to fresh vegetables."):
    return RetrievedSource(
        evidence=EvidenceReference(
            citation_id=citation_id or uuid4(),
            source_url="https://example.org/urban-gardens",
            source_title="Urban garden access",
            excerpt="Urban gardens improve access to fresh vegetables.",
        ),
        retrieved_at=datetime.now(timezone.utc),
        text=text,
    )


def context(*, sources=None):
    sources = sources or [source()]
    return ScriptStoryboardContext(
        idea=StrategyCandidate(
            title="Grow More Nearby",
            target_audience="Apartment residents",
            rationale="Explain a small practical starting point.",
            evidence=[item.evidence for item in sources],
            score=82.0,
        ),
        sources=sources,
        brand_voice="Warm, clear, practical",
        target_duration_seconds=10,
        scene_count=2,
    )


def draft(active_context, **overrides):
    evidence = active_context.sources[0].evidence.model_dump(mode="json")
    value = {
        "script": {
            "title": "Grow More Nearby",
            "hook": "Fresh food can start close to home.",
            "narration": "Urban gardens improve access to fresh vegetables.",
            "call_to_action": "Find one sunny corner to begin.",
            "evidence": [evidence],
        },
        "storyboard": {
            "title": "Grow More Nearby",
            "scenes": [
                {
                    "scene_number": 1,
                    "duration_seconds": 5,
                    "visual_prompt": "Show a small shared planter in morning light.",
                    "narration": "Urban gardens improve access to",
                    "evidence": [evidence],
                },
                {
                    "scene_number": 2,
                    "duration_seconds": 5,
                    "visual_prompt": "Show neighbors picking fresh vegetables.",
                    "narration": "fresh vegetables.",
                    "evidence": [evidence],
                },
            ],
        },
    }
    for path, change in overrides.items():
        section, key = path.split("__", 1)
        value[section][key] = change
    return value


class FakeGenerator:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def generate(self, value):
        self.calls.append(value)
        if self.error:
            raise self.error
        return self.result(value) if callable(self.result) else self.result


class ScriptStoryboardWorkflowTests(IsolatedAsyncioTestCase):
    async def test_valid_result_is_bound_to_exact_source_and_coherent_storyboard(self):
        provider = FakeGenerator(lambda value: draft(value))
        request = context()
        result = await ScriptStoryboardWorkflow(provider).run(request)
        self.assertEqual(result.script.title, result.storyboard.title)
        self.assertEqual(len(result.storyboard.scenes), 2)
        self.assertEqual(provider.calls, [request])

    async def test_invalid_context_fails_before_generator_is_called(self):
        provider = FakeGenerator({})
        with self.assertRaises(ScriptStoryboardError) as raised:
            await ScriptStoryboardWorkflow(provider).run({"brand_voice": "bad"})
        self.assertEqual(raised.exception.code, ScriptStoryboardErrorCode.INVALID_CONTEXT)
        self.assertEqual(provider.calls, [])

    async def test_impossible_duration_and_scene_count_fail_before_generator_call(self):
        provider = FakeGenerator({})
        for scene_count, duration in ((1, 300), (30, 10)):
            active = context()
            payload = active.model_dump(mode="python")
            payload["scene_count"] = scene_count
            payload["target_duration_seconds"] = duration
            with self.subTest(scene_count=scene_count, duration=duration), self.assertRaises(ScriptStoryboardError) as raised:
                await ScriptStoryboardWorkflow(provider).run(payload)
            self.assertEqual(raised.exception.code, ScriptStoryboardErrorCode.INVALID_CONTEXT)
        self.assertEqual(provider.calls, [])

    async def test_context_rejects_duplicate_or_unbound_idea_evidence(self):
        item = source()
        with self.assertRaises(ValueError):
            context(sources=[item, item])
        altered = item.evidence.model_copy(update={"source_title": "Different source"})
        with self.assertRaises(ValueError):
            ScriptStoryboardContext(
                idea=StrategyCandidate(title="Idea", target_audience="People", rationale="Why", evidence=[altered], score=80),
                sources=[item], brand_voice="Voice", target_duration_seconds=10, scene_count=2,
            )

    async def test_provider_failure_is_sanitized(self):
        provider = FakeGenerator(error=RuntimeError("private provider detail"))
        with self.assertRaises(ScriptStoryboardError) as raised:
            await ScriptStoryboardWorkflow(provider).run(context())
        self.assertEqual(raised.exception.code, ScriptStoryboardErrorCode.GENERATOR_FAILED)
        self.assertNotIn("private", str(raised.exception))

    async def test_invalid_untrusted_output_has_stable_safe_error(self):
        provider = FakeGenerator({"script": {"secret_payload": "value"}})
        with self.assertRaises(ScriptStoryboardError) as raised:
            await ScriptStoryboardWorkflow(provider).run(context())
        self.assertEqual(raised.exception.code, ScriptStoryboardErrorCode.INVALID_OUTPUT)
        self.assertNotIn("secret_payload", str(raised.exception))

    async def test_storyboard_requires_requested_scene_count_and_duration(self):
        for code, field, value in (
            (ScriptStoryboardErrorCode.INVALID_SCENE_COUNT, "storyboard__scenes", [
                {"scene_number": 1, "duration_seconds": 10, "visual_prompt": "One", "narration": "Urban gardens improve access to fresh vegetables."},
            ]),
            (ScriptStoryboardErrorCode.INVALID_DURATION, "storyboard__scenes", [
                {"scene_number": 1, "duration_seconds": 2, "visual_prompt": "One", "narration": "Urban gardens improve access to"},
                {"scene_number": 2, "duration_seconds": 2, "visual_prompt": "Two", "narration": "fresh vegetables."},
            ]),
        ):
            active = context()
            provider = FakeGenerator(lambda value, field=field, replacement=value: draft(value, **{field: replacement}))
            with self.subTest(code=code), self.assertRaises(ScriptStoryboardError) as raised:
                await ScriptStoryboardWorkflow(provider).run(active)
            self.assertEqual(raised.exception.code, code)

    async def test_storyboard_title_and_narration_must_match_script(self):
        active = context()
        for code, overrides in (
            (ScriptStoryboardErrorCode.TITLE_MISMATCH, {"storyboard__title": "Wrong title"}),
            (ScriptStoryboardErrorCode.NARRATION_MISMATCH, {"storyboard__scenes": [
                {"scene_number": 1, "duration_seconds": 5, "visual_prompt": "One", "narration": "Different words."},
                {"scene_number": 2, "duration_seconds": 5, "visual_prompt": "Two", "narration": "fresh vegetables."},
            ]}),
        ):
            provider = FakeGenerator(lambda value, overrides=overrides: draft(value, **overrides))
            with self.subTest(code=code), self.assertRaises(ScriptStoryboardError) as raised:
                await ScriptStoryboardWorkflow(provider).run(active)
            self.assertEqual(raised.exception.code, code)

    async def test_script_requires_evidence_and_citations_must_match_snapshot(self):
        active = context()
        cases = [
            (ScriptStoryboardErrorCode.MISSING_SCRIPT_EVIDENCE, {"script__evidence": []}),
            (ScriptStoryboardErrorCode.UNKNOWN_CITATION, {"script__evidence": [{
                **active.sources[0].evidence.model_dump(mode="json"), "citation_id": str(uuid4()),
            }]}),
            (ScriptStoryboardErrorCode.SOURCE_MISMATCH, {"script__evidence": [{
                **active.sources[0].evidence.model_dump(mode="json"), "source_title": "Impostor",
            }]}),
            (ScriptStoryboardErrorCode.UNSUPPORTED_EXCERPT, {"script__evidence": [{
                **active.sources[0].evidence.model_dump(mode="json"), "excerpt": "unrelated assertion",
            }]}),
            (ScriptStoryboardErrorCode.UNSUPPORTED_EXCERPT, {"script__evidence": [{
                **active.sources[0].evidence.model_dump(mode="json"), "excerpt": "   ",
            }]}),
        ]
        for code, overrides in cases:
            provider = FakeGenerator(lambda value, overrides=overrides: draft(value, **overrides))
            with self.subTest(code=code), self.assertRaises(ScriptStoryboardError) as raised:
                await ScriptStoryboardWorkflow(provider).run(active)
            self.assertEqual(raised.exception.code, code)

    async def test_scene_evidence_is_validated_too(self):
        active = context()
        scenes = draft(active)["storyboard"]["scenes"]
        scenes[0]["evidence"] = [{
            **active.sources[0].evidence.model_dump(mode="json"), "excerpt": "unsupported quote",
        }]
        provider = FakeGenerator(lambda value: draft(value, storyboard__scenes=scenes))
        with self.assertRaises(ScriptStoryboardError) as raised:
            await ScriptStoryboardWorkflow(provider).run(active)
        self.assertEqual(raised.exception.code, ScriptStoryboardErrorCode.UNSUPPORTED_EXCERPT)

    async def test_generator_cannot_mutate_the_trusted_citation_source_set(self):
        class MutatingGenerator:
            async def generate(self, value):
                fabricated = source(text="Fabricated facts are now sourced.")
                value.sources.append(fabricated)
                output = draft(value)
                output["script"]["evidence"] = [fabricated.evidence.model_dump(mode="python")]
                return output

        request = context()
        with self.assertRaises(ScriptStoryboardError) as raised:
            await ScriptStoryboardWorkflow(MutatingGenerator()).run(request)
        self.assertEqual(raised.exception.code, ScriptStoryboardErrorCode.UNKNOWN_CITATION)
        self.assertEqual(len(request.sources), 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
