"""Evidence-bound automated review with a hard human-approval boundary."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from flowx_os.agents.research import RetrievedSource
from flowx_os.agents.schemas import AgentSchemaError, _StrictModel, validate_agent_output
from flowx_os.agents.script_storyboard import ScriptStoryboardDraft, _validate_evidence


class ReviewDisposition(StrEnum):
    BLOCKED = "blocked"
    NEEDS_REVISION = "needs_revision"
    READY_FOR_HUMAN_REVIEW = "ready_for_human_review"


class ReviewSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ReviewCategory(StrEnum):
    FACTUALITY = "factuality"
    SAFETY = "safety"
    RIGHTS = "rights"
    BRAND = "brand"
    CLARITY = "clarity"
    COMPLETENESS = "completeness"
    POLICY = "policy"


class ReviewContext(_StrictModel):
    content_id: UUID
    prompt_id: str = Field(min_length=1, max_length=100)
    prompt_version: int = Field(ge=1, le=100_000)
    policy_version: int = Field(ge=1, le=100_000)
    draft: ScriptStoryboardDraft
    sources: list[RetrievedSource] = Field(min_length=1, max_length=20)

    @field_validator("content_id", mode="before")
    @classmethod
    def parse_content_id(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                raise ValueError("content_id must be a UUID") from None
        return value

    @model_validator(mode="after")
    def input_evidence_is_bound(self) -> "ReviewContext":
        ids = [item.evidence.citation_id for item in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("source citation IDs must be unique")
        if sum(len(item.text.encode("utf-8")) for item in self.sources) > 1_000_000:
            raise ValueError("source snapshots exceed the 1 MB limit")
        if not self.draft.script.evidence:
            raise ValueError("script must contain evidence")
        _validate_evidence(self.draft.script.evidence, self.sources, path="script.evidence")
        for index, scene in enumerate(self.draft.storyboard.scenes):
            _validate_evidence(scene.evidence, self.sources, path=f"storyboard.scenes.{index}.evidence")
        return self


class ReviewFinding(_StrictModel):
    category: ReviewCategory
    severity: ReviewSeverity
    summary: str = Field(min_length=1, max_length=1000)
    recommendation: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @field_validator("category", mode="before")
    @classmethod
    def parse_category(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return ReviewCategory(value)
            except ValueError:
                raise ValueError("category is not supported") from None
        return value

    @field_validator("severity", mode="before")
    @classmethod
    def parse_severity(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return ReviewSeverity(value)
            except ValueError:
                raise ValueError("severity is not supported") from None
        return value

    @field_validator("evidence_ids", mode="before")
    @classmethod
    def parse_evidence_ids(cls, value: Any) -> Any:
        if isinstance(value, list):
            try:
                return [UUID(item) if isinstance(item, str) else item for item in value]
            except ValueError:
                raise ValueError("evidence_ids must contain UUIDs") from None
        return value

    @model_validator(mode="after")
    def evidence_ids_unique(self) -> "ReviewFinding":
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence IDs must be unique")
        if self.category == ReviewCategory.FACTUALITY and not self.evidence_ids:
            raise ValueError("factuality findings must reference source evidence")
        return self


class ReviewAssessment(_StrictModel):
    disposition: ReviewDisposition
    score: float = Field(ge=0.0, le=100.0)
    summary: str = Field(min_length=1, max_length=2000)
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=30)

    @field_validator("disposition", mode="before")
    @classmethod
    def parse_disposition(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return ReviewDisposition(value)
            except ValueError:
                raise ValueError("disposition is not supported") from None
        return value

    @model_validator(mode="after")
    def critical_findings_cannot_be_ready(self) -> "ReviewAssessment":
        if (self.disposition == ReviewDisposition.READY_FOR_HUMAN_REVIEW
                and any(item.severity == ReviewSeverity.CRITICAL for item in self.findings)):
            raise ValueError("critical findings cannot be marked ready for human review")
        return self


class HumanReviewResult(_StrictModel):
    assessment: ReviewAssessment
    human_approval_required: Literal[True] = True
    approval_state: Literal["pending_human"] = "pending_human"
    content_approved: Literal[False] = False


class ContentReviewer(Protocol):
    async def review(self, context: ReviewContext) -> ReviewAssessment | Mapping[str, Any]: ...


class ReviewErrorCode(StrEnum):
    INVALID_CONTEXT = "invalid_context"
    PROVIDER_FAILED = "provider_failed"
    INVALID_ASSESSMENT = "invalid_assessment"
    UNKNOWN_EVIDENCE = "unknown_evidence"


class ReviewError(ValueError):
    """Safe review failure with no rejected payload or provider detail."""

    def __init__(self, code: ReviewErrorCode, *, path: str = "review"):
        self.code = code
        self.path = path[:200]
        super().__init__(f"review workflow failed: {code.value} at {self.path}")


class ContentReviewWorkflow:
    def __init__(self, reviewer: ContentReviewer):
        self._reviewer = reviewer

    async def run(self, context: ReviewContext | Mapping[str, Any]) -> HumanReviewResult:
        try:
            active = validate_agent_output(ReviewContext, context)
        except (AgentSchemaError, TypeError, ValueError):
            raise ReviewError(ReviewErrorCode.INVALID_CONTEXT) from None
        source_ids = frozenset(item.evidence.citation_id for item in active.sources)
        provider_context = active.model_copy(deep=True)
        try:
            raw = await self._reviewer.review(provider_context)
        except Exception:
            raise ReviewError(ReviewErrorCode.PROVIDER_FAILED) from None
        try:
            assessment = validate_agent_output(ReviewAssessment, raw)
        except (AgentSchemaError, TypeError, ValueError):
            raise ReviewError(ReviewErrorCode.INVALID_ASSESSMENT) from None
        for finding_index, finding in enumerate(assessment.findings):
            if any(item not in source_ids for item in finding.evidence_ids):
                raise ReviewError(ReviewErrorCode.UNKNOWN_EVIDENCE, path=f"findings.{finding_index}.evidence_ids")
        return HumanReviewResult(assessment=assessment)
