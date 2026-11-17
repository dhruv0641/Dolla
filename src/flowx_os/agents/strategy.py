"""Deterministic weighted idea scoring and stable ranking."""

from __future__ import annotations

import math
from collections.abc import Sequence as SequenceABC
from enum import StrEnum
from typing import Any, Sequence
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from flowx_os.agents.schemas import AgentSchemaError, EvidenceReference, _StrictModel, validate_agent_output


class IdeaDimension(StrEnum):
    ORIGINALITY = "originality"
    AUDIENCE_FIT = "audience_fit"
    EVIDENCE_STRENGTH = "evidence_strength"
    PRODUCTION_FEASIBILITY = "production_feasibility"
    BRAND_ALIGNMENT = "brand_alignment"


class IdeaBlocker(StrEnum):
    POLICY_REVIEW = "policy_review"
    RIGHTS_REVIEW = "rights_review"
    FACT_CHECK_REQUIRED = "fact_check_required"
    BRAND_CONFLICT = "brand_conflict"
    DUPLICATE_CONCEPT = "duplicate_concept"


class IdeaScoreStatus(StrEnum):
    READY_FOR_REVIEW = "ready_for_review"
    NEEDS_EVIDENCE = "needs_evidence"
    BELOW_THRESHOLD = "below_threshold"
    BLOCKED = "blocked"


class IdeaWeights(_StrictModel):
    originality: float = Field(default=0.15, ge=0.0, le=1.0)
    audience_fit: float = Field(default=0.25, ge=0.0, le=1.0)
    evidence_strength: float = Field(default=0.25, ge=0.0, le=1.0)
    production_feasibility: float = Field(default=0.15, ge=0.0, le=1.0)
    brand_alignment: float = Field(default=0.20, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "IdeaWeights":
        if not math.isclose(sum(self.model_dump().values()), 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("idea scoring weights must sum to 1.0")
        return self


class IdeaScoringProfile(_StrictModel):
    version: int = Field(default=1, ge=1, le=100_000)
    weights: IdeaWeights = Field(default_factory=IdeaWeights)
    minimum_eligible_score: float = Field(default=65.0, ge=0.0, le=100.0)
    minimum_evidence_sources: int = Field(default=1, ge=0, le=20)


class IdeaSignals(_StrictModel):
    """Normalized 0–100 ratings supplied by a reviewer or strategy component."""

    originality: float = Field(ge=0.0, le=100.0)
    audience_fit: float = Field(ge=0.0, le=100.0)
    evidence_strength: float = Field(ge=0.0, le=100.0)
    production_feasibility: float = Field(ge=0.0, le=100.0)
    brand_alignment: float = Field(ge=0.0, le=100.0)


class IdeaCandidate(_StrictModel):
    idea_id: UUID
    title: str = Field(min_length=1, max_length=200)
    concept: str = Field(min_length=1, max_length=3000)
    signals: IdeaSignals
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=20)
    blockers: list[IdeaBlocker] = Field(default_factory=list, max_length=10)

    @field_validator("idea_id", mode="before")
    @classmethod
    def parse_idea_uuid(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                raise ValueError("idea_id must be a UUID") from None
        return value

    @field_validator("blockers", mode="before")
    @classmethod
    def parse_blocker_values(cls, value: Any) -> Any:
        if isinstance(value, SequenceABC) and not isinstance(value, (str, bytes)):
            try:
                return [item if isinstance(item, IdeaBlocker) else IdeaBlocker(item) for item in value]
            except (TypeError, ValueError):
                raise ValueError("blockers contains an unsupported code") from None
        return value

    @model_validator(mode="after")
    def evidence_signal_has_provenance(self) -> "IdeaCandidate":
        ids = [item.citation_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence citation IDs must be unique")
        if not self.evidence and self.signals.evidence_strength > 0:
            raise ValueError("evidence_strength must be zero when evidence is absent")
        return self


class IdeaContribution(_StrictModel):
    dimension: IdeaDimension
    rating: float = Field(ge=0.0, le=100.0)
    weight: float = Field(ge=0.0, le=1.0)
    weighted_score: float = Field(ge=0.0, le=100.0)


class ScoredIdea(_StrictModel):
    idea_id: UUID
    title: str
    score: float = Field(ge=0.0, le=100.0)
    profile_version: int = Field(ge=1)
    contributions: list[IdeaContribution] = Field(min_length=5, max_length=5)
    evidence_source_count: int = Field(ge=0, le=20)
    blockers: list[IdeaBlocker] = Field(max_length=10)
    status: IdeaScoreStatus


class IdeaScoringErrorCode(StrEnum):
    INVALID_PROFILE = "invalid_profile"
    INVALID_CANDIDATE = "invalid_candidate"
    DUPLICATE_IDEA_ID = "duplicate_idea_id"


class IdeaScoringError(ValueError):
    """Safe score calculation failure with a stable code and field path."""

    def __init__(self, code: IdeaScoringErrorCode, *, path: str = "idea"):
        self.code = code
        self.path = path
        super().__init__(f"idea scoring failed: {code.value} at {path}")


def _validate_profile(profile: IdeaScoringProfile) -> IdeaScoringProfile:
    try:
        return validate_agent_output(IdeaScoringProfile, profile)
    except AgentSchemaError:
        raise IdeaScoringError(IdeaScoringErrorCode.INVALID_PROFILE, path="profile") from None


def score_idea(candidate: IdeaCandidate, profile: IdeaScoringProfile | None = None) -> ScoredIdea:
    """Compute a weighted score and keep evidence/blocker readiness separate."""
    active_profile = _validate_profile(profile or IdeaScoringProfile())
    try:
        idea = validate_agent_output(IdeaCandidate, candidate)
    except AgentSchemaError:
        raise IdeaScoringError(IdeaScoringErrorCode.INVALID_CANDIDATE) from None

    contribution_fields = (
        (IdeaDimension.ORIGINALITY, idea.signals.originality, active_profile.weights.originality),
        (IdeaDimension.AUDIENCE_FIT, idea.signals.audience_fit, active_profile.weights.audience_fit),
        (IdeaDimension.EVIDENCE_STRENGTH, idea.signals.evidence_strength, active_profile.weights.evidence_strength),
        (IdeaDimension.PRODUCTION_FEASIBILITY, idea.signals.production_feasibility, active_profile.weights.production_feasibility),
        (IdeaDimension.BRAND_ALIGNMENT, idea.signals.brand_alignment, active_profile.weights.brand_alignment),
    )
    contributions = [
        IdeaContribution(
            dimension=dimension,
            rating=rating,
            weight=weight,
            weighted_score=round(rating * weight, 2),
        )
        for dimension, rating, weight in contribution_fields
    ]
    total = round(sum(item.weighted_score for item in contributions), 2)
    if idea.blockers:
        status = IdeaScoreStatus.BLOCKED
    elif len(idea.evidence) < active_profile.minimum_evidence_sources:
        status = IdeaScoreStatus.NEEDS_EVIDENCE
    elif total < active_profile.minimum_eligible_score:
        status = IdeaScoreStatus.BELOW_THRESHOLD
    else:
        status = IdeaScoreStatus.READY_FOR_REVIEW
    return ScoredIdea(
        idea_id=idea.idea_id,
        title=idea.title,
        score=total,
        profile_version=active_profile.version,
        contributions=contributions,
        evidence_source_count=len(idea.evidence),
        blockers=idea.blockers,
        status=status,
    )


_STATUS_RANK = {
    IdeaScoreStatus.READY_FOR_REVIEW: 0,
    IdeaScoreStatus.NEEDS_EVIDENCE: 1,
    IdeaScoreStatus.BELOW_THRESHOLD: 2,
    IdeaScoreStatus.BLOCKED: 3,
}


def rank_ideas(
    candidates: Sequence[IdeaCandidate], profile: IdeaScoringProfile | None = None
) -> tuple[ScoredIdea, ...]:
    """Rank ideas deterministically: readiness, score, title, then stable UUID."""
    active_profile = _validate_profile(profile or IdeaScoringProfile())
    scored = [score_idea(candidate, active_profile) for candidate in candidates]
    ids = [item.idea_id for item in scored]
    if len(ids) != len(set(ids)):
        raise IdeaScoringError(IdeaScoringErrorCode.DUPLICATE_IDEA_ID)
    return tuple(sorted(
        scored,
        key=lambda item: (
            _STATUS_RANK[item.status], -item.score, item.title.casefold(), str(item.idea_id)
        ),
    ))
