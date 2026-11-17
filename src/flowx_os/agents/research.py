"""Provider-neutral research orchestration with citation/source binding."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from pydantic import Field, field_validator

from flowx_os.agents.schemas import (
    AgentSchemaError,
    EvidenceReference,
    ResearchResult,
    _StrictModel,
    validate_agent_output,
)

MAX_SOURCES = 20
MAX_SOURCE_TEXT_BYTES = 1_000_000


class RetrievedSource(_StrictModel):
    """An immutable source snapshot returned by an injected retrieval provider."""

    evidence: EvidenceReference
    retrieved_at: datetime
    text: str = Field(min_length=1, max_length=100_000)

    @field_validator("retrieved_at")
    @classmethod
    def retrieved_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value

    @field_validator("text")
    @classmethod
    def text_is_utf8(cls, value: str) -> str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("source text must be valid UTF-8") from None
        return value


class ResearchSourceProvider(Protocol):
    """Retrieval boundary. Implementations must enforce network-safe fetching."""

    async def search(self, query: str, *, limit: int) -> Sequence[RetrievedSource | Mapping[str, Any]]: ...


class ResearchSummarizer(Protocol):
    """Summarization boundary; output remains untrusted until validated."""

    async def summarize(
        self, query: str, sources: Sequence[RetrievedSource]
    ) -> ResearchResult | Mapping[str, Any]: ...


class ResearchErrorCode(StrEnum):
    INVALID_QUERY = "invalid_query"
    INVALID_LIMIT = "invalid_limit"
    SOURCE_PROVIDER_FAILED = "source_provider_failed"
    SUMMARIZER_FAILED = "summarizer_failed"
    INVALID_SOURCE_RESPONSE = "invalid_source_response"
    NO_SOURCES = "no_sources"
    TOO_MANY_SOURCES = "too_many_sources"
    SOURCE_BYTES_EXCEEDED = "source_bytes_exceeded"
    DUPLICATE_SOURCE_ID = "duplicate_source_id"
    UNKNOWN_CITATION = "unknown_citation"
    SOURCE_MISMATCH = "source_mismatch"
    UNSUPPORTED_EXCERPT = "unsupported_excerpt"
    INVALID_SUMMARY = "invalid_summary"


class ResearchEvidenceError(ValueError):
    """Safe workflow failure containing only a stable code and schema path."""

    def __init__(self, code: ResearchErrorCode, *, path: str = "research"):
        self.code = code
        self.path = path
        super().__init__(f"research workflow failed: {code.value} at {path}")


@dataclass(frozen=True, slots=True)
class EvidenceBackedResearch:
    result: ResearchResult
    sources: tuple[RetrievedSource, ...]


def _normalized_quote(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()


def _validate_citations(result: ResearchResult, sources: Sequence[RetrievedSource]) -> None:
    by_id: dict[UUID, RetrievedSource] = {}
    for index, source in enumerate(sources):
        citation_id = source.evidence.citation_id
        if citation_id in by_id:
            raise ResearchEvidenceError(ResearchErrorCode.DUPLICATE_SOURCE_ID, path=f"sources.{index}")
        by_id[citation_id] = source

    for finding_index, finding in enumerate(result.findings):
        for citation_index, citation in enumerate(finding.citations):
            path = f"findings.{finding_index}.citations.{citation_index}"
            source = by_id.get(citation.citation_id)
            if source is None:
                raise ResearchEvidenceError(ResearchErrorCode.UNKNOWN_CITATION, path=path)
            if citation.source_url != source.evidence.source_url or citation.source_title != source.evidence.source_title:
                raise ResearchEvidenceError(ResearchErrorCode.SOURCE_MISMATCH, path=path)
            quoted = _normalized_quote(citation.excerpt)
            content = _normalized_quote(source.text)
            if not quoted or quoted not in content:
                raise ResearchEvidenceError(ResearchErrorCode.UNSUPPORTED_EXCERPT, path=path)


class EvidenceBackedResearchWorkflow:
    """Retrieve snapshots, validate generated claims, and bind citations to snapshots."""

    def __init__(self, source_provider: ResearchSourceProvider, summarizer: ResearchSummarizer):
        self._source_provider = source_provider
        self._summarizer = summarizer

    async def run(self, query: str, *, source_limit: int = 10) -> EvidenceBackedResearch:
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ResearchEvidenceError(ResearchErrorCode.INVALID_QUERY)
        if isinstance(source_limit, bool) or not isinstance(source_limit, int) or not 1 <= source_limit <= MAX_SOURCES:
            raise ResearchEvidenceError(ResearchErrorCode.INVALID_LIMIT)

        try:
            raw_sources = await self._source_provider.search(query.strip(), limit=source_limit)
        except Exception:
            raise ResearchEvidenceError(ResearchErrorCode.SOURCE_PROVIDER_FAILED) from None
        if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, (str, bytes)):
            raise ResearchEvidenceError(ResearchErrorCode.INVALID_SOURCE_RESPONSE)
        if not raw_sources:
            raise ResearchEvidenceError(ResearchErrorCode.NO_SOURCES)
        if len(raw_sources) > source_limit:
            raise ResearchEvidenceError(ResearchErrorCode.TOO_MANY_SOURCES)

        try:
            sources = tuple(validate_agent_output(RetrievedSource, item) for item in raw_sources)
        except AgentSchemaError:
            raise ResearchEvidenceError(ResearchErrorCode.INVALID_SOURCE_RESPONSE) from None
        total_bytes = sum(len(source.text.encode("utf-8")) for source in sources)
        if total_bytes > MAX_SOURCE_TEXT_BYTES:
            raise ResearchEvidenceError(ResearchErrorCode.SOURCE_BYTES_EXCEEDED)

        # Reject duplicate IDs before handing snapshots to the summarizer.
        seen: set[UUID] = set()
        for index, source in enumerate(sources):
            if source.evidence.citation_id in seen:
                raise ResearchEvidenceError(ResearchErrorCode.DUPLICATE_SOURCE_ID, path=f"sources.{index}")
            seen.add(source.evidence.citation_id)

        try:
            raw_result = await self._summarizer.summarize(query.strip(), sources)
        except Exception:
            raise ResearchEvidenceError(ResearchErrorCode.SUMMARIZER_FAILED) from None
        try:
            result = validate_agent_output(ResearchResult, raw_result)
        except AgentSchemaError:
            raise ResearchEvidenceError(ResearchErrorCode.INVALID_SUMMARY, path="result") from None
        _validate_citations(result, sources)
        return EvidenceBackedResearch(result=result, sources=sources)
