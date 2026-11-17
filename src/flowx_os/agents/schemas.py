"""Strict schemas at the boundary between orchestration and AI agents.

These models validate structure only. They do not call a model, verify a claim,
approve content, grant permissions, or authorize publishing.
"""

from __future__ import annotations

import json
import ipaddress
import math
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, TypeVar
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, ValidationError,
    field_validator, model_validator,
)


class AgentRole(StrEnum):
    RESEARCH = "research"
    STRATEGY = "strategy"
    SCRIPT = "script"
    STORYBOARD = "storyboard"
    REVIEWER = "reviewer"
    ANALYST = "analyst"


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always"
    )


class AgentRequest(_StrictModel):
    """Version-pinned request passed to an agent implementation."""

    request_id: UUID
    correlation_id: UUID
    brand_id: UUID
    role: AgentRole
    prompt_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$")
    prompt_version: int = Field(ge=1, le=100_000)
    policy_version: int = Field(ge=1, le=100_000)
    input_data: dict[str, Any]

    @field_validator("request_id", "correlation_id", "brand_id", mode="before")
    @classmethod
    def parse_uuid_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                raise ValueError("value must be a UUID") from None
        return value

    @field_validator("role", mode="before")
    @classmethod
    def parse_role_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return AgentRole(value)
            except ValueError:
                raise ValueError("role is not supported") from None
        return value

    @field_validator("input_data")
    @classmethod
    def input_is_bounded_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        def visit(item: Any, depth: int = 0) -> None:
            if depth > 20:
                raise ValueError("input_data nesting exceeds the supported depth")
            if isinstance(item, dict):
                if any(type(key) is not str for key in item):
                    raise ValueError("input_data object keys must be strings")
                for child in item.values():
                    visit(child, depth + 1)
            elif isinstance(item, list):
                for child in item:
                    visit(child, depth + 1)
            elif item is None or type(item) in (str, bool, int):
                return
            elif type(item) is float and math.isfinite(item):
                return
            else:
                raise ValueError("input_data must contain only JSON values")

        try:
            visit(value)
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("input_data must contain JSON-compatible values") from exc
        if len(encoded.encode("utf-8")) > 32 * 1024:
            raise ValueError("input_data exceeds the 32768-byte limit")
        return value


class EvidenceReference(_StrictModel):
    """A traceable source excerpt attached to a research finding."""

    citation_id: UUID
    source_url: str = Field(min_length=1, max_length=2048)
    source_title: str = Field(min_length=1, max_length=300)
    excerpt: str = Field(min_length=1, max_length=2000)

    @field_validator("citation_id", mode="before")
    @classmethod
    def parse_citation_uuid(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                raise ValueError("citation_id must be a UUID") from None
        return value

    @field_validator("source_url")
    @classmethod
    def require_http_source(cls, value: str) -> str:
        if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            raise ValueError("source_url must not contain whitespace or control characters")
        try:
            normalized = str(TypeAdapter(HttpUrl).validate_python(value))
        except ValidationError:
            raise ValueError("source_url must be a valid absolute HTTP or HTTPS URL") from None
        parsed = urlsplit(normalized)
        original = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or original.username is not None or original.password is not None):
            raise ValueError("source_url must be an absolute HTTP or HTTPS URL")
        if original.netloc.endswith(":"):
            raise ValueError("source_url has an invalid empty port")
        try:
            port = original.port
        except ValueError:
            raise ValueError("source_url has an invalid port") from None
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("source_url has an invalid port")
        original_host = original.hostname
        normalized_host = parsed.hostname
        if original_host is None or normalized_host is None:
            raise ValueError("source_url must include a valid host")
        try:
            host = original_host.encode("idna").decode("ascii").rstrip(".").lower()
        except UnicodeError:
            raise ValueError("source_url must include a valid host") from None
        canonical_host = normalized_host.rstrip(".").lower()
        if host != canonical_host:
            raise ValueError("source_url authority is ambiguous")
        if not host:
            raise ValueError("source_url must include a valid host")
        if host == "localhost" or host.endswith((".localhost", ".local")):
            raise ValueError("source_url must use a publicly routable host")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError("source_url must use a publicly routable host")
        if address is None and (
            len(host) > 253
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split("."))
        ):
            raise ValueError("source_url must include a valid DNS host")
        return value


class ResearchFinding(_StrictModel):
    claim: str = Field(min_length=1, max_length=1000)
    citations: list[EvidenceReference] = Field(min_length=1, max_length=10)
    confidence: float = Field(ge=0.0, le=1.0)


class ResearchResult(_StrictModel):
    findings: list[ResearchFinding] = Field(min_length=1, max_length=50)
    open_questions: list[str] = Field(default_factory=list, max_length=20)


class StrategyCandidate(_StrictModel):
    title: str = Field(min_length=1, max_length=200)
    target_audience: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=20)
    score: float = Field(ge=0.0, le=100.0)


class ScriptDraft(_StrictModel):
    title: str = Field(min_length=1, max_length=200)
    hook: str = Field(min_length=1, max_length=1000)
    narration: str = Field(min_length=1, max_length=12000)
    call_to_action: str = Field(min_length=1, max_length=500)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=20)


class StoryboardScene(_StrictModel):
    scene_number: int = Field(ge=1, le=30)
    duration_seconds: int = Field(ge=1, le=60)
    visual_prompt: str = Field(min_length=1, max_length=2000)
    narration: str = Field(default="", max_length=2000)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=20)


class StoryboardDraft(_StrictModel):
    title: str = Field(min_length=1, max_length=200)
    scenes: list[StoryboardScene] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def scenes_are_sequential(self) -> "StoryboardDraft":
        numbers = [scene.scene_number for scene in self.scenes]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("scene_number values must be sequential starting at 1")
        return self


class AgentValidationIssue(_StrictModel):
    path: str = Field(min_length=1, max_length=300)
    code: str = Field(min_length=1, max_length=80)


class AgentSchemaError(ValueError):
    """Payload-free validation error safe to include in structured logs."""

    def __init__(self, issues: tuple[AgentValidationIssue, ...]):
        self.issues = issues
        super().__init__(f"agent data failed schema validation ({len(issues)} issue(s))")


_SchemaT = TypeVar("_SchemaT", bound=_StrictModel)


def _safe_validation_issues(exc: ValidationError, *, root: str) -> tuple[AgentValidationIssue, ...]:
    issues = []
    for error in exc.errors(include_input=False, include_context=False, include_url=False):
        location = list(error["loc"])
        # Unknown field names are caller-controlled; report their location
        # without copying those names into logs or error responses.
        if error["type"] == "extra_forbidden" and location:
            location[-1] = "<extra>"
        path = (".".join(str(part) for part in location) or root)[:300]
        issues.append(AgentValidationIssue(path=path, code=str(error["type"])))
    return tuple(issues)


def validate_agent_output(schema: type[_SchemaT], data: Any) -> _SchemaT:
    """Validate untrusted agent output with payload-free, structured errors."""
    if not isinstance(schema, type) or not issubclass(schema, _StrictModel):
        raise TypeError("schema must be one of the agent contract models")
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise AgentSchemaError(_safe_validation_issues(exc, root="output")) from None


def validate_agent_request(data: Mapping[str, Any]) -> AgentRequest:
    """Validate an untrusted mapping without exposing supplied values in errors."""
    return validate_agent_output(AgentRequest, data)
