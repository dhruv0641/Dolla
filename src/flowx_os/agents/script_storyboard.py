"""Provider-neutral script and storyboard generation with evidence binding."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field, field_validator, model_validator

from flowx_os.agents.research import RetrievedSource
from flowx_os.agents.schemas import (
    AgentSchemaError,
    EvidenceReference,
    ScriptDraft,
    StrategyCandidate,
    StoryboardDraft,
    _StrictModel,
    validate_agent_output,
)

MAX_SCRIPT_SOURCE_BYTES = 1_000_000
MAX_SCRIPT_SOURCES = 20


class ScriptStoryboardContext(_StrictModel):
    """Bounded, evidence-bearing context passed to an injected generator."""

    idea: StrategyCandidate
    sources: list[RetrievedSource] = Field(min_length=1, max_length=MAX_SCRIPT_SOURCES)
    brand_voice: str = Field(min_length=1, max_length=1000)
    target_duration_seconds: int = Field(ge=1, le=300)
    scene_count: int = Field(ge=1, le=30)

    @field_validator("brand_voice")
    @classmethod
    def brand_voice_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("brand_voice must not be blank")
        return value

    @model_validator(mode="after")
    def source_ids_are_unique_and_bounded(self) -> "ScriptStoryboardContext":
        if not self.scene_count <= self.target_duration_seconds <= self.scene_count * 60:
            raise ValueError("target duration must be achievable within the requested scene count")
        ids = [source.evidence.citation_id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("source citation IDs must be unique")
        total_bytes = sum(len(source.text.encode("utf-8")) for source in self.sources)
        if total_bytes > MAX_SCRIPT_SOURCE_BYTES:
            raise ValueError("source snapshots exceed the 1 MB limit")
        sources_by_id = {source.evidence.citation_id: source for source in self.sources}
        idea_ids = [item.citation_id for item in self.idea.evidence]
        if len(idea_ids) != len(set(idea_ids)):
            raise ValueError("idea evidence citation IDs must be unique")
        for index, evidence in enumerate(self.idea.evidence):
            source = sources_by_id.get(evidence.citation_id)
            if (source is None or evidence.source_url != source.evidence.source_url
                    or evidence.source_title != source.evidence.source_title):
                raise ValueError(f"idea evidence at index {index} is not present in source snapshots")
            excerpt = _normalized_text(evidence.excerpt)
            if not excerpt or excerpt not in _normalized_text(source.text):
                raise ValueError(f"idea evidence at index {index} is not present in the source snapshot")
        return self


class ScriptStoryboardDraft(_StrictModel):
    """The paired, untrusted result returned by a generator implementation."""

    script: ScriptDraft
    storyboard: StoryboardDraft


class ScriptStoryboardGenerator(Protocol):
    """Provider boundary; implementations own model access and cost controls."""

    async def generate(
        self, context: ScriptStoryboardContext
    ) -> ScriptStoryboardDraft | Mapping[str, Any]: ...


class ScriptStoryboardErrorCode(StrEnum):
    INVALID_CONTEXT = "invalid_context"
    GENERATOR_FAILED = "generator_failed"
    INVALID_OUTPUT = "invalid_output"
    INVALID_SCENE_COUNT = "invalid_scene_count"
    INVALID_DURATION = "invalid_duration"
    TITLE_MISMATCH = "title_mismatch"
    NARRATION_MISMATCH = "narration_mismatch"
    MISSING_SCRIPT_EVIDENCE = "missing_script_evidence"
    UNKNOWN_CITATION = "unknown_citation"
    SOURCE_MISMATCH = "source_mismatch"
    UNSUPPORTED_EXCERPT = "unsupported_excerpt"


class ScriptStoryboardError(ValueError):
    """Safe workflow failure exposing only a stable code and bounded path."""

    def __init__(self, code: ScriptStoryboardErrorCode, *, path: str = "content"):
        self.code = code
        self.path = path[:200]
        super().__init__(f"script/storyboard workflow failed: {code.value} at {self.path}")


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()


def _validate_evidence(
    citations: Sequence[EvidenceReference], sources: Sequence[RetrievedSource], *, path: str
) -> None:
    source_by_id = {source.evidence.citation_id: source for source in sources}
    for index, citation in enumerate(citations):
        item_path = f"{path}.{index}"
        source = source_by_id.get(citation.citation_id)
        if source is None:
            raise ScriptStoryboardError(ScriptStoryboardErrorCode.UNKNOWN_CITATION, path=item_path)
        if (citation.source_url != source.evidence.source_url
                or citation.source_title != source.evidence.source_title):
            raise ScriptStoryboardError(ScriptStoryboardErrorCode.SOURCE_MISMATCH, path=item_path)
        excerpt = _normalized_text(citation.excerpt)
        if not excerpt or excerpt not in _normalized_text(source.text):
            raise ScriptStoryboardError(ScriptStoryboardErrorCode.UNSUPPORTED_EXCERPT, path=item_path)


class ScriptStoryboardWorkflow:
    """Validate provider output and enforce evidence and storyboard coherence."""

    def __init__(self, generator: ScriptStoryboardGenerator):
        self._generator = generator

    async def run(
        self, context: ScriptStoryboardContext | Mapping[str, Any]
    ) -> ScriptStoryboardDraft:
        try:
            active_context = validate_agent_output(ScriptStoryboardContext, context)
        except AgentSchemaError:
            raise ScriptStoryboardError(ScriptStoryboardErrorCode.INVALID_CONTEXT) from None
        except (TypeError, ValueError):
            raise ScriptStoryboardError(ScriptStoryboardErrorCode.INVALID_CONTEXT) from None

        # The provider receives a detached copy. Keep citation authority in
        # private deep copies so mutations to nested lists cannot add sources.
        trusted_sources = tuple(source.model_copy(deep=True) for source in active_context.sources)
        provider_context = active_context.model_copy(deep=True)

        try:
            raw = await self._generator.generate(provider_context)
        except Exception:
            raise ScriptStoryboardError(ScriptStoryboardErrorCode.GENERATOR_FAILED) from None
        try:
            result = validate_agent_output(ScriptStoryboardDraft, raw)
        except (AgentSchemaError, TypeError, ValueError):
            raise ScriptStoryboardError(ScriptStoryboardErrorCode.INVALID_OUTPUT) from None

        if len(result.storyboard.scenes) != active_context.scene_count:
            raise ScriptStoryboardError(ScriptStoryboardErrorCode.INVALID_SCENE_COUNT, path="storyboard.scenes")
        if sum(scene.duration_seconds for scene in result.storyboard.scenes) != active_context.target_duration_seconds:
            raise ScriptStoryboardError(ScriptStoryboardErrorCode.INVALID_DURATION, path="storyboard.scenes")
        if not _normalized_text(result.script.title) or result.storyboard.title != result.script.title:
            raise ScriptStoryboardError(ScriptStoryboardErrorCode.TITLE_MISMATCH, path="storyboard.title")
        if any(not _normalized_text(scene.narration) for scene in result.storyboard.scenes):
            raise ScriptStoryboardError(ScriptStoryboardErrorCode.NARRATION_MISMATCH, path="storyboard.scenes.narration")
        scene_narration = " ".join(scene.narration for scene in result.storyboard.scenes)
        if (not _normalized_text(result.script.narration)
                or _normalized_text(scene_narration) != _normalized_text(result.script.narration)):
            raise ScriptStoryboardError(ScriptStoryboardErrorCode.NARRATION_MISMATCH, path="storyboard.scenes.narration")
        if not result.script.evidence:
            raise ScriptStoryboardError(ScriptStoryboardErrorCode.MISSING_SCRIPT_EVIDENCE, path="script.evidence")
        _validate_evidence(result.script.evidence, trusted_sources, path="script.evidence")
        for scene_index, scene in enumerate(result.storyboard.scenes):
            _validate_evidence(scene.evidence, trusted_sources, path=f"storyboard.scenes.{scene_index}.evidence")
        return result
