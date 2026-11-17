import unittest
from datetime import datetime, timezone
from uuid import uuid4

from flowx_os.agents.research import (
    EvidenceBackedResearchWorkflow,
    ResearchErrorCode,
    ResearchEvidenceError,
    RetrievedSource,
)
from flowx_os.agents.schemas import ResearchResult


SOURCE_TEXT = "Urban gardens can improve access to fresh vegetables in dense neighborhoods."


def source(*, citation_id=None, source_url="https://example.org/gardens", title="Urban gardening"):
    return RetrievedSource(
        evidence={
            "citation_id": citation_id or uuid4(),
            "source_url": source_url,
            "source_title": title,
            "excerpt": SOURCE_TEXT,
        },
        retrieved_at=datetime.now(timezone.utc),
        text=SOURCE_TEXT,
    )


def summary(sources, *, citation=None, excerpt=SOURCE_TEXT, title="Urban gardening", url="https://example.org/gardens"):
    citation = citation or sources[0].evidence.citation_id
    return {
        "findings": [{
            "claim": "Urban gardens can improve access to fresh vegetables.",
            "citations": [{
                "citation_id": str(citation), "source_url": url,
                "source_title": title, "excerpt": excerpt,
            }],
            "confidence": 0.8,
        }],
        "open_questions": [],
    }


class FakeProvider:
    def __init__(self, values=None, error=None):
        self.values = values or []
        self.error = error
        self.calls = []

    async def search(self, query, *, limit):
        self.calls.append((query, limit))
        if self.error:
            raise self.error
        return self.values


class FakeSummarizer:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.calls = []

    async def summarize(self, query, sources):
        self.calls.append((query, sources))
        if self.error:
            raise self.error
        return self.output(sources) if callable(self.output) else self.output


class ResearchWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_citations_are_bound_to_retrieved_source_snapshots(self):
        doc = source()
        provider = FakeProvider([doc])
        summarizer = FakeSummarizer(lambda sources: summary(sources))
        result = await EvidenceBackedResearchWorkflow(provider, summarizer).run("  urban gardens  ", source_limit=4)
        self.assertEqual(result.sources, (doc,))
        self.assertEqual(result.result.findings[0].citations[0].citation_id, doc.evidence.citation_id)
        self.assertEqual(provider.calls, [("urban gardens", 4)])
        self.assertEqual(summarizer.calls[0][0], "urban gardens")

    async def test_excerpt_matching_normalizes_case_and_whitespace(self):
        doc = source()
        summarizer = FakeSummarizer(lambda sources: summary(
            sources, excerpt=" URBAN GARDENS can improve access to fresh\nvegetables in dense neighborhoods. "
        ))
        result = await EvidenceBackedResearchWorkflow(FakeProvider([doc]), summarizer).run("topic")
        self.assertEqual(len(result.result.findings), 1)

    async def test_empty_source_set_fails_before_summarizer(self):
        summarizer = FakeSummarizer(lambda sources: {})
        with self.assertRaises(ResearchEvidenceError) as raised:
            await EvidenceBackedResearchWorkflow(FakeProvider(), summarizer).run("topic")
        self.assertEqual(raised.exception.code, ResearchErrorCode.NO_SOURCES)
        self.assertEqual(summarizer.calls, [])

    async def test_unknown_citation_is_rejected(self):
        doc = source()
        summarizer = FakeSummarizer(lambda sources: summary(sources, citation=uuid4()))
        with self.assertRaises(ResearchEvidenceError) as raised:
            await EvidenceBackedResearchWorkflow(FakeProvider([doc]), summarizer).run("topic")
        self.assertEqual(raised.exception.code, ResearchErrorCode.UNKNOWN_CITATION)

    async def test_citation_identity_must_match_source_url_and_title(self):
        doc = source()
        for kwargs in ({"url": "https://other.example/source"}, {"title": "Other source"}):
            summarizer = FakeSummarizer(lambda sources, kw=kwargs: summary(sources, **kw))
            with self.subTest(kwargs=kwargs), self.assertRaises(ResearchEvidenceError) as raised:
                await EvidenceBackedResearchWorkflow(FakeProvider([doc]), summarizer).run("topic")
            self.assertEqual(raised.exception.code, ResearchErrorCode.SOURCE_MISMATCH)

    async def test_excerpt_must_appear_in_the_retrieved_snapshot(self):
        doc = source()
        summarizer = FakeSummarizer(lambda sources: summary(sources, excerpt="unrelated fabricated wording"))
        with self.assertRaises(ResearchEvidenceError) as raised:
            await EvidenceBackedResearchWorkflow(FakeProvider([doc]), summarizer).run("topic")
        self.assertEqual(raised.exception.code, ResearchErrorCode.UNSUPPORTED_EXCERPT)

    async def test_duplicate_source_ids_are_rejected_before_summarization(self):
        citation_id = uuid4()
        provider = FakeProvider([source(citation_id=citation_id), source(citation_id=citation_id)])
        summarizer = FakeSummarizer(lambda sources: {})
        with self.assertRaises(ResearchEvidenceError) as raised:
            await EvidenceBackedResearchWorkflow(provider, summarizer).run("topic")
        self.assertEqual(raised.exception.code, ResearchErrorCode.DUPLICATE_SOURCE_ID)
        self.assertEqual(summarizer.calls, [])

    async def test_source_and_summary_provider_errors_are_sanitized(self):
        source_provider = FakeProvider(error=RuntimeError("secret source-provider detail"))
        summarizer = FakeSummarizer(error=RuntimeError("secret model output detail"))
        with self.assertRaises(ResearchEvidenceError) as source_error:
            await EvidenceBackedResearchWorkflow(source_provider, summarizer).run("topic")
        self.assertEqual(source_error.exception.code, ResearchErrorCode.SOURCE_PROVIDER_FAILED)
        doc = source()
        with self.assertRaises(ResearchEvidenceError) as summary_error:
            await EvidenceBackedResearchWorkflow(FakeProvider([doc]), summarizer).run("topic")
        self.assertEqual(summary_error.exception.code, ResearchErrorCode.SUMMARIZER_FAILED)
        self.assertNotIn("secret", str(source_error.exception) + str(summary_error.exception))

    async def test_limits_and_invalid_source_response_fail_closed(self):
        doc = source()
        with self.assertRaises(ResearchEvidenceError) as raised:
            await EvidenceBackedResearchWorkflow(FakeProvider([doc]), FakeSummarizer()).run("topic", source_limit=0)
        self.assertEqual(raised.exception.code, ResearchErrorCode.INVALID_LIMIT)
        with self.assertRaises(ResearchEvidenceError) as raised:
            await EvidenceBackedResearchWorkflow(FakeProvider([doc, source()]), FakeSummarizer()).run("topic", source_limit=1)
        self.assertEqual(raised.exception.code, ResearchErrorCode.TOO_MANY_SOURCES)
        with self.assertRaises(ResearchEvidenceError) as raised:
            await EvidenceBackedResearchWorkflow(FakeProvider([{"bad": "source"}]), FakeSummarizer()).run("topic")
        self.assertEqual(raised.exception.code, ResearchErrorCode.INVALID_SOURCE_RESPONSE)

    async def test_total_source_snapshot_size_is_bounded(self):
        sources = [source(source_url=f"https://example.org/page-{index}") for index in range(11)]
        sources = [item.model_copy(update={"text": "x" * 100_000}) for item in sources]
        summarizer = FakeSummarizer(lambda values: {})
        with self.assertRaises(ResearchEvidenceError) as raised:
            await EvidenceBackedResearchWorkflow(FakeProvider(sources), summarizer).run("topic", source_limit=20)
        self.assertEqual(raised.exception.code, ResearchErrorCode.SOURCE_BYTES_EXCEEDED)
        self.assertEqual(summarizer.calls, [])

    async def test_invalid_summarizer_schema_returns_safe_code(self):
        doc = source()
        with self.assertRaises(ResearchEvidenceError) as raised:
            await EvidenceBackedResearchWorkflow(FakeProvider([doc]), FakeSummarizer({"unexpected": True})).run("topic")
        self.assertEqual(raised.exception.code, ResearchErrorCode.INVALID_SUMMARY)

    async def test_constructed_invalid_source_model_is_revalidated(self):
        valid = source()
        invalid = RetrievedSource.model_construct(
            evidence=valid.evidence, retrieved_at=datetime.now(), text="",
        )
        with self.assertRaises(ResearchEvidenceError) as raised:
            await EvidenceBackedResearchWorkflow(FakeProvider([invalid]), FakeSummarizer({})).run("topic")
        self.assertEqual(raised.exception.code, ResearchErrorCode.INVALID_SOURCE_RESPONSE)

    async def test_constructed_invalid_summary_model_is_revalidated(self):
        doc = source()
        invalid = ResearchResult.model_construct(findings=[object()], open_questions=[])
        with self.assertRaises(ResearchEvidenceError) as raised:
            await EvidenceBackedResearchWorkflow(FakeProvider([doc]), FakeSummarizer(invalid)).run("topic")
        self.assertEqual(raised.exception.code, ResearchErrorCode.INVALID_SUMMARY)

    async def test_research_query_is_required_and_bounded(self):
        workflow = EvidenceBackedResearchWorkflow(FakeProvider(), FakeSummarizer())
        for query in (" ", "x" * 501):
            with self.subTest(query_length=len(query)), self.assertRaises(ResearchEvidenceError) as raised:
                await workflow.run(query)
            self.assertEqual(raised.exception.code, ResearchErrorCode.INVALID_QUERY)


if __name__ == "__main__":
    unittest.main()
