"""Provider-neutral, observation-linked analyst workflow."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from flowx_os.agents.schemas import AgentSchemaError, _StrictModel, validate_agent_output

_METRIC_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class AnalystObservation(_StrictModel):
    observation_id: UUID
    metric: str = Field(min_length=1, max_length=64)
    value: float
    unit: str = Field(min_length=1, max_length=40)
    captured_at: datetime
    sample_count: int = Field(ge=1, le=1_000_000_000)

    @field_validator("observation_id", mode="before")
    @classmethod
    def parse_observation_id(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                raise ValueError("observation_id must be a UUID") from None
        return value

    @field_validator("metric")
    @classmethod
    def metric_is_safe_identifier(cls, value: str) -> str:
        if not _METRIC_NAME.fullmatch(value):
            raise ValueError("metric must be a safe identifier")
        return value

    @field_validator("value")
    @classmethod
    def value_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("value must be finite")
        return value

    @field_validator("captured_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value


class AnalystContext(_StrictModel):
    prompt_id: str = Field(min_length=1, max_length=100)
    prompt_version: int = Field(ge=1, le=100_000)
    brand_goal: str = Field(min_length=1, max_length=1000)
    observations: list[AnalystObservation] = Field(min_length=1, max_length=100)

    @field_validator("brand_goal")
    @classmethod
    def goal_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("brand_goal must not be blank")
        return value

    @model_validator(mode="after")
    def observation_ids_are_unique(self) -> "AnalystContext":
        ids = [item.observation_id for item in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("observation IDs must be unique")
        return self


class AnalystFinding(_StrictModel):
    title: str = Field(min_length=1, max_length=200)
    observed_fact: str = Field(min_length=1, max_length=1000)
    interpretation: str = Field(min_length=1, max_length=1000)
    recommendation: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)
    observation_ids: list[UUID] = Field(min_length=1, max_length=20)

    @field_validator("observation_ids", mode="before")
    @classmethod
    def parse_observation_ids(cls, value: Any) -> Any:
        if isinstance(value, list):
            try:
                return [UUID(item) if isinstance(item, str) else item for item in value]
            except ValueError:
                raise ValueError("observation_ids must contain UUIDs") from None
        return value

    @model_validator(mode="after")
    def unique_observation_refs(self) -> "AnalystFinding":
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("observation IDs must be unique")
        return self


class AnalystAssessment(_StrictModel):
    summary: str = Field(min_length=1, max_length=2000)
    findings: list[AnalystFinding] = Field(default_factory=list, max_length=20)
    data_limitations: list[str] = Field(default_factory=list, max_length=20)


class VerifiedAnalystResult(_StrictModel):
    assessment: AnalystAssessment
    all_observation_references_verified: Literal[True]
    human_interpretation_required: Literal[True] = True


class AnalystProvider(Protocol):
    async def analyze(self, context: AnalystContext) -> AnalystAssessment | Mapping[str, Any]: ...


class AnalystErrorCode(StrEnum):
    INVALID_CONTEXT = "invalid_context"
    PROVIDER_FAILED = "provider_failed"
    INVALID_ASSESSMENT = "invalid_assessment"
    UNKNOWN_OBSERVATION = "unknown_observation"


class AnalystError(ValueError):
    """Safe analyst failure with a stable code and bounded field path."""

    def __init__(self, code: str, *, path: str = "analysis"):
        self.code = code
        self.path = path[:200]
        super().__init__(f"analyst workflow failed: {code} at {self.path}")


class ContentAnalystWorkflow:
    def __init__(self, provider: AnalystProvider):
        self._provider = provider

    async def run(self, context: AnalystContext | Mapping[str, Any]) -> VerifiedAnalystResult:
        try:
            active = validate_agent_output(AnalystContext, context)
        except (AgentSchemaError, TypeError, ValueError):
            raise AnalystError(AnalystErrorCode.INVALID_CONTEXT) from None
        observation_ids = frozenset(item.observation_id for item in active.observations)
        provider_context = active.model_copy(deep=True)
        try:
            raw = await self._provider.analyze(provider_context)
        except Exception:
            raise AnalystError(AnalystErrorCode.PROVIDER_FAILED) from None
        try:
            assessment = validate_agent_output(AnalystAssessment, raw)
        except (AgentSchemaError, TypeError, ValueError):
            raise AnalystError(AnalystErrorCode.INVALID_ASSESSMENT) from None
        for finding_index, finding in enumerate(assessment.findings):
            if any(item not in observation_ids for item in finding.observation_ids):
                raise AnalystError(AnalystErrorCode.UNKNOWN_OBSERVATION, path=f"findings.{finding_index}.observation_ids")
        return VerifiedAnalystResult(
            assessment=assessment,
            all_observation_references_verified=True,
            human_interpretation_required=True,
        )
