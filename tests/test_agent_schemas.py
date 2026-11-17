import json
import unittest
from uuid import uuid4
from pydantic import ValidationError

from flowx_os.agents.schemas import (
    AgentSchemaError,
    EvidenceReference,
    ResearchResult,
    ScriptDraft,
    StoryboardDraft,
    validate_agent_request,
    validate_agent_output,
)


def valid_request():
    return {
        "request_id": str(uuid4()),
        "correlation_id": str(uuid4()),
        "brand_id": str(uuid4()),
        "role": "research",
        "prompt_id": "research.v1",
        "prompt_version": 1,
        "policy_version": 1,
        "input_data": {"topic": "urban gardening"},
    }


class AgentSchemaTests(unittest.TestCase):
    def test_valid_request_is_version_pinned_and_immutable(self):
        data = valid_request()
        request = validate_agent_request(data)
        self.assertEqual(request.prompt_id, "research.v1")
        self.assertEqual(request.prompt_version, 1)
        with self.assertRaises(ValidationError):
            request.prompt_version = 2

    def test_request_rejects_unknown_fields_without_echoing_input(self):
        data = valid_request()
        data["api_key"] = "sensitive-marker-value"
        with self.assertRaises(AgentSchemaError) as raised:
            validate_agent_request(data)
        rendered = str(raised.exception) + json.dumps([issue.model_dump() for issue in raised.exception.issues])
        self.assertNotIn("sensitive-marker-value", rendered)
        self.assertNotIn("api_key", rendered)
        self.assertEqual(raised.exception.issues[0].code, "extra_forbidden")

    def test_long_unknown_field_name_cannot_break_error_redaction(self):
        field_name = "private-marker-" + ("x" * 400)
        data = valid_request()
        data[field_name] = "do-not-echo"
        with self.assertRaises(AgentSchemaError) as raised:
            validate_agent_request(data)
        self.assertNotIn("private-marker", str(raised.exception))
        self.assertNotIn(field_name, " ".join(issue.path for issue in raised.exception.issues))
        self.assertLessEqual(max(len(issue.path) for issue in raised.exception.issues), 300)

    def test_request_requires_positive_versions_and_bounded_json_payload(self):
        data = valid_request()
        data["policy_version"] = 0
        with self.assertRaises(AgentSchemaError):
            validate_agent_request(data)
        data = valid_request()
        data["input_data"] = {"text": "x" * 32769}
        with self.assertRaises(AgentSchemaError) as raised:
            validate_agent_request(data)
        self.assertTrue(any(issue.path == "input_data" for issue in raised.exception.issues))

    def test_request_rejects_non_json_python_values(self):
        for invalid in ({"tuple": (1, 2)}, {"bytes": b"secret"}, {1: "non-string key"}):
            data = valid_request()
            data["input_data"] = invalid
            with self.subTest(invalid_type=type(next(iter(invalid.values()))).__name__):
                with self.assertRaises(AgentSchemaError):
                    validate_agent_request(data)

    def test_evidence_requires_public_http_url_and_nonempty_provenance(self):
        for url in (
            "file:///etc/passwd", "https://example.org:bad/source",
            "http://127.0.0.1/admin", "http://localhost:5432/secret",
            "http://not a valid host/source", "https://example.org:",
            "http://.", "http://-bad.com", "http://example.com\n.evil",
            " https://example.org/",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                EvidenceReference(
                    citation_id=uuid4(), source_url=url,
                    source_title="source", excerpt="quoted evidence",
                )

    def test_research_finding_requires_evidence_and_bounded_confidence(self):
        citation = {
            "citation_id": str(uuid4()), "source_url": "https://example.org/source",
            "source_title": "Example", "excerpt": "Evidence excerpt",
        }
        with self.assertRaises(ValueError):
            ResearchResult.model_validate({"findings": [{
                "claim": "A claim", "citations": [], "confidence": 0.5,
            }]})
        with self.assertRaises(ValueError):
            ResearchResult.model_validate({"findings": [{
                "claim": "A claim", "citations": [citation], "confidence": 1.2,
            }]})

    def test_script_draft_is_strict_and_bounded(self):
        with self.assertRaises(ValueError):
            ScriptDraft.model_validate({
                "title": "Title", "hook": "Hook", "narration": "Words",
                "call_to_action": "Follow", "publish_now": True,
            })

    def test_storyboard_scene_numbers_are_sequential(self):
        with self.assertRaises(ValueError):
            StoryboardDraft.model_validate({
                "title": "Draft", "scenes": [
                    {"scene_number": 1, "duration_seconds": 3, "visual_prompt": "Scene"},
                    {"scene_number": 3, "duration_seconds": 3, "visual_prompt": "Scene"},
                ],
            })

    def test_role_values_are_allowlisted(self):
        data = valid_request()
        data["role"] = "publisher_admin"
        with self.assertRaises(AgentSchemaError):
            validate_agent_request(data)

    def test_output_error_redaction_hides_untrusted_provider_text(self):
        private_text = "private-provider-output-marker"
        with self.assertRaises(AgentSchemaError) as raised:
            validate_agent_output(ScriptDraft, {"title": private_text})
        rendered = str(raised.exception) + json.dumps([issue.model_dump() for issue in raised.exception.issues])
        self.assertNotIn(private_text, rendered)


if __name__ == "__main__":
    unittest.main()
