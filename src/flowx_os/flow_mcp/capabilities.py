"""Validated, fail-closed capability and authorization models for Flow MCP."""

from __future__ import annotations

import re
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class FlowOperation(StrEnum):
    VIDEO_GENERATE = "video_generate"
    SESSION_STATUS = "session_status"
    MEDIA_DOWNLOAD = "media_download"
    PROJECT_OPEN = "project_open"
    SCENE_STATUS = "scene_status"
    SCENE_EXTEND = "scene_extend"


class AdapterErrorCode(StrEnum):
    DISABLED = "adapter_disabled"
    CONFIGURATION_MISSING = "adapter_configuration_missing"
    MANIFEST_UNAVAILABLE = "manifest_unavailable"
    MANIFEST_STALE = "manifest_stale"
    SERVER_MISMATCH = "server_identity_mismatch"
    CAPABILITY_UNKNOWN = "capability_unknown"
    CAPABILITY_UNSUPPORTED = "capability_unsupported"
    TOOL_SCHEMA_INVALID = "tool_schema_invalid"
    ACCOUNT_UNVERIFIED = "account_unverified"
    ACCOUNT_MISMATCH = "account_mismatch"
    ACCOUNT_DISCONNECTED = "account_disconnected"
    ACCOUNT_NOT_LOGGED_IN = "account_not_logged_in"
    ACCOUNT_HEALTH_STALE = "account_health_stale"
    ACCOUNT_HEALTH_UNAVAILABLE = "account_health_unavailable"
    SPEND_AUTHORIZATION_REQUIRED = "spend_authorization_required"
    SPEND_AUTHORIZATION_INVALID = "spend_authorization_invalid"
    ARGUMENTS_INVALID = "arguments_invalid"
    TOOL_CALL_FAILED = "tool_call_failed"
    TOOL_RESULT_INVALID = "tool_result_invalid"


_ERROR_MESSAGES = {
    AdapterErrorCode.DISABLED: "Flow MCP operations are disabled.",
    AdapterErrorCode.CONFIGURATION_MISSING: "Flow MCP server or account configuration is incomplete.",
    AdapterErrorCode.MANIFEST_UNAVAILABLE: "A verified Flow MCP manifest is unavailable.",
    AdapterErrorCode.MANIFEST_STALE: "Flow MCP capability evidence is stale.",
    AdapterErrorCode.SERVER_MISMATCH: "The discovered Flow MCP server does not match configuration.",
    AdapterErrorCode.CAPABILITY_UNKNOWN: "The requested Flow MCP capability has not been verified.",
    AdapterErrorCode.CAPABILITY_UNSUPPORTED: "The requested Flow MCP capability is unsupported.",
    AdapterErrorCode.TOOL_SCHEMA_INVALID: "The configured Flow MCP tool binding does not match its manifest schema.",
    AdapterErrorCode.ACCOUNT_UNVERIFIED: "The Flow account has not been verified.",
    AdapterErrorCode.ACCOUNT_MISMATCH: "The verified Flow account does not match configuration.",
    AdapterErrorCode.ACCOUNT_DISCONNECTED: "The Flow MCP session is disconnected.",
    AdapterErrorCode.ACCOUNT_NOT_LOGGED_IN: "The Flow MCP session is not logged in.",
    AdapterErrorCode.ACCOUNT_HEALTH_STALE: "The Flow account health evidence is stale.",
    AdapterErrorCode.ACCOUNT_HEALTH_UNAVAILABLE: "Flow account health evidence is unavailable.",
    AdapterErrorCode.SPEND_AUTHORIZATION_REQUIRED: "An explicit spend authorization is required for this operation.",
    AdapterErrorCode.SPEND_AUTHORIZATION_INVALID: "The spend authorization is invalid for this account or operation.",
    AdapterErrorCode.ARGUMENTS_INVALID: "The operation arguments do not match the discovered tool schema.",
    AdapterErrorCode.TOOL_CALL_FAILED: "The Flow MCP tool call failed.",
    AdapterErrorCode.TOOL_RESULT_INVALID: "The Flow MCP tool returned an invalid result.",
}


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _validate_schema_definition(schema: Mapping[str, Any]) -> None:
    """Accept only the JSON Schema subset this boundary can enforce."""
    kind = schema.get("type")
    allowed = {
        "object": {"type", "properties", "required", "additionalProperties", "description", "title"},
        "string": {"type", "enum", "const", "minLength", "maxLength", "description", "title"},
        "integer": {"type", "enum", "const", "minimum", "maximum", "description", "title"},
        "number": {"type", "enum", "const", "minimum", "maximum", "description", "title"},
        "boolean": {"type", "enum", "const", "description", "title"},
        "array": {"type", "items", "minItems", "maxItems", "description", "title"},
    }
    if kind not in allowed or set(schema) - allowed[kind]:
        raise ValueError("MCP tool schema uses an unsupported or invalid JSON Schema construct")
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and (not isinstance(schema[key], int) or isinstance(schema[key], bool) or schema[key] < 0):
            raise ValueError(f"JSON Schema {key} must be a non-negative integer")
    for key in ("minimum", "maximum"):
        if key in schema and (
            isinstance(schema[key], bool)
            or not isinstance(schema[key], (int, float))
            or not math.isfinite(schema[key])
        ):
            raise ValueError(f"JSON Schema {key} must be a finite number")
    if "minLength" in schema and "maxLength" in schema and schema["minLength"] > schema["maxLength"]:
        raise ValueError("JSON Schema minLength must not exceed maxLength")
    if "minItems" in schema and "maxItems" in schema and schema["minItems"] > schema["maxItems"]:
        raise ValueError("JSON Schema minItems must not exceed maxItems")
    if "minimum" in schema and "maximum" in schema and schema["minimum"] > schema["maximum"]:
        raise ValueError("JSON Schema minimum must not exceed maximum")
    if "enum" in schema and (not isinstance(schema["enum"], (list, tuple)) or not schema["enum"]):
        raise ValueError("JSON Schema enum must be a non-empty array")
    if kind == "object":
        properties = schema.get("properties")
        required = schema.get("required", ())
        additional = schema.get("additionalProperties", False)
        if not isinstance(properties, Mapping) or not isinstance(required, (list, tuple)):
            raise ValueError("MCP tool input schema properties and required fields are invalid")
        if additional is not False:
            raise ValueError("MCP tool object schemas must explicitly reject additional properties")
        if not all(isinstance(key, str) for key in properties):
            raise ValueError("MCP tool input schema field names must be strings")
        if not all(isinstance(key, str) and key in properties for key in required):
            raise ValueError("MCP tool input schema required fields must exist in properties")
        for child in properties.values():
            if not isinstance(child, Mapping):
                raise ValueError("JSON Schema property definitions must be objects")
            _validate_schema_definition(child)
    if kind == "array":
        items = schema.get("items")
        if not isinstance(items, Mapping):
            raise ValueError("JSON Schema arrays require an item schema")
        _validate_schema_definition(items)


def schema_accepts(schema: Mapping[str, Any], value: Any) -> bool:
    """Validate a value against the deliberately supported JSON Schema subset."""
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
            return False
        properties = schema["properties"]
        required = schema.get("required", ())
        if not set(required).issubset(value) or not set(value).issubset(properties):
            return False
        return all(schema_accepts(properties[key], item) for key, item in value.items())
    if kind == "string":
        valid = isinstance(value, str)
        valid = valid and len(value) >= schema.get("minLength", 0)
        valid = valid and len(value) <= schema.get("maxLength", float("inf"))
    elif kind == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif kind == "number":
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif kind == "boolean":
        valid = isinstance(value, bool)
    elif kind == "array":
        valid = isinstance(value, (list, tuple))
        valid = valid and len(value) >= schema.get("minItems", 0)
        valid = valid and len(value) <= schema.get("maxItems", float("inf"))
        valid = valid and all(schema_accepts(schema["items"], item) for item in value)
    else:
        return False
    if not valid:
        return False
    if kind in {"integer", "number"}:
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if "const" in schema and value != schema["const"]:
        return False
    return True


class FlowAdapterError(RuntimeError):
    """Stable payload-safe error; raw MCP data and exception text are never included."""

    def __init__(self, code: AdapterErrorCode) -> None:
        self.code = code
        super().__init__(_ERROR_MESSAGES[code])

    def to_payload(self) -> dict[str, str]:
        return {"code": self.code.value, "message": _ERROR_MESSAGES[self.code]}


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    """App-side identity and enablement policy. Defaults always deny operations."""

    enabled: bool = False
    expected_server_id: str | None = None
    expected_account_ref: str | None = None
    max_manifest_age: timedelta = timedelta(minutes=15)

    def __post_init__(self) -> None:
        if self.max_manifest_age <= timedelta(0):
            raise ValueError("max_manifest_age must be positive")
        if self.enabled and (not self.expected_server_id or not self.expected_account_ref):
            raise FlowAdapterError(AdapterErrorCode.CONFIGURATION_MISSING)
        if self.expected_account_ref and not validate_account_ref(self.expected_account_ref):
            raise FlowAdapterError(AdapterErrorCode.ACCOUNT_UNVERIFIED)


@dataclass(frozen=True, slots=True)
class FlowAccountAuthorization:
    """Short-lived proof minted by the account-health service, not user input."""

    account_ref: str
    checked_at: datetime
    valid_until: datetime
    _issuer: object

    def __post_init__(self) -> None:
        if self._issuer is not _ACCOUNT_AUTHORIZATION_ISSUER:
            raise ValueError("account authorization must be issued by trusted account-health service")
        if not validate_account_ref(self.account_ref):
            raise ValueError("account_ref must be an opaque local reference")
        if self.checked_at.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("account authorization timestamps must be timezone-aware")
        if self.valid_until <= self.checked_at:
            raise ValueError("account authorization must have a positive validity window")

    @property
    def verified(self) -> bool:
        return True


_ACCOUNT_AUTHORIZATION_ISSUER = object()


def _issue_flow_account_authorization(
    account_ref: str,
    *,
    checked_at: datetime,
    valid_until: datetime,
) -> FlowAccountAuthorization:
    """Internal constructor reserved for the account-health verification flow."""
    return FlowAccountAuthorization(account_ref, checked_at, valid_until, _ACCOUNT_AUTHORIZATION_ISSUER)


@dataclass(frozen=True, slots=True)
class SpendAuthorization:
    """Human-approved operation reference and hard credit ceiling."""

    approval_ref: str
    account_ref: str
    operation: FlowOperation
    max_allowed_credits: int

    def __post_init__(self) -> None:
        if (
            not self.approval_ref.strip()
            or not validate_account_ref(self.account_ref)
            or self.max_allowed_credits <= 0
        ):
            raise ValueError("spend authorization requires a reference, account, operation and positive credit ceiling")


@dataclass(frozen=True, slots=True)
class McpTool:
    """A tool declaration copied from an inspected MCP manifest."""

    name: str
    input_schema: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.name.strip() or not isinstance(self.input_schema, Mapping):
            raise ValueError("tool name and object input schema are required")
        if self.input_schema.get("type") != "object":
            raise ValueError("MCP tool input schema must declare an object")
        _validate_schema_definition(self.input_schema)
        object.__setattr__(self, "input_schema", _freeze(self.input_schema))

    @property
    def allowed_inputs(self) -> frozenset[str]:
        return frozenset(self.input_schema["properties"])

    @property
    def required_inputs(self) -> frozenset[str]:
        return frozenset(self.input_schema.get("required", ()))


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    """Explicit mapping from a normalized app operation to one observed MCP tool."""

    operation: FlowOperation
    tool_name: str
    required_inputs: frozenset[str] = frozenset()
    requires_spend_authorization: bool = False

    def __post_init__(self) -> None:
        if not self.tool_name.strip():
            raise ValueError("tool_name must not be blank")
        object.__setattr__(self, "required_inputs", frozenset(self.required_inputs))


@dataclass(frozen=True, slots=True)
class FlowMcpManifest:
    """One time-bounded, server-specific manifest snapshot and explicit app bindings."""

    server_id: str
    observed_at: datetime
    tools: Mapping[str, McpTool]
    bindings: Mapping[FlowOperation, CapabilityBinding]

    def __post_init__(self) -> None:
        if not self.server_id.strip() or self.observed_at.tzinfo is None:
            raise ValueError("manifest requires server identity and timezone-aware observation time")
        copied_tools = dict(self.tools)
        copied_bindings = dict(self.bindings)
        if any(name != tool.name for name, tool in copied_tools.items()):
            raise ValueError("manifest tool keys must match declared tool names")
        if any(op != binding.operation for op, binding in copied_bindings.items()):
            raise ValueError("manifest binding keys must match their operations")
        object.__setattr__(self, "tools", MappingProxyType(copied_tools))
        object.__setattr__(self, "bindings", MappingProxyType(copied_bindings))


_ACCOUNT_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_account_ref(value: str) -> bool:
    """Accept an opaque local alias, never an email address, token, or cookie."""

    return bool(_ACCOUNT_REF.fullmatch(value))


def manifest_is_fresh(manifest: FlowMcpManifest, *, now: datetime, max_age: timedelta) -> bool:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    observed = manifest.observed_at.astimezone(timezone.utc)
    current = now.astimezone(timezone.utc)
    return observed <= current and current - observed <= max_age
