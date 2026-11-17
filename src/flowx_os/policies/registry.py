"""Load and validate a local, versioned prompt and policy registry.

Registry content is configuration, not executable code. This module does not
call model providers and does not interpolate user or remote content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from string import Formatter
from pathlib import Path
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

MAX_PROMPT_BYTES = 32 * 1024
MAX_PROMPT_VALUE_BYTES = 8 * 1024
_VARIABLE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SECRET_NAME = re.compile(r"(?:token|secret|password|credential|api[_-]?key|authorization|cookie)", re.I)
_CREDENTIAL_VALUE = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|client[_ -]?secret|authorization)\s*[:=]\s*\S+"
    r"|\bbearer\s+[a-z0-9._~+/=-]{16,}\b"
    r"|\b(?:sk-[a-z0-9_-]{16,}|gh[pousr]_[a-z0-9_]{16,}|github_pat_[a-z0-9_]{16,}|AIza[a-z0-9_-]{30,})\b"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)


class RegistryError(ValueError):
    """Raised when a registry is unreadable or violates its schema."""


class PromptRenderError(ValueError):
    """Raised for missing, unknown, or oversized prompt values."""


@dataclass(frozen=True)
class PromptDefinition:
    prompt_id: str
    version: int
    purpose: str
    system: str
    template: str
    variables: tuple[str, ...]

    def render(self, values: Mapping[str, str]) -> "RenderedPrompt":
        """Render declared string slots only; formatting expressions are forbidden."""
        if not isinstance(values, Mapping):
            raise PromptRenderError("Prompt values must be a mapping")
        if any(type(key) is not str for key in values):
            raise PromptRenderError("Prompt value names must be strings")
        supplied = set(values)
        expected = set(self.variables)
        if supplied != expected:
            raise PromptRenderError("Prompt values do not match the declared variable set")
        bounded: dict[str, str] = {}
        for name, value in values.items():
            if type(value) is not str:
                raise PromptRenderError("Prompt values must be strings")
            if len(value.encode("utf-8")) > MAX_PROMPT_VALUE_BYTES:
                raise PromptRenderError("A prompt value exceeds its byte limit")
            bounded[name] = value
        try:
            user = self.template.format_map(bounded)
        except (KeyError, ValueError, IndexError):
            raise PromptRenderError("Prompt template could not be rendered") from None
        if len((self.system + user).encode("utf-8")) > MAX_PROMPT_BYTES:
            raise PromptRenderError("Rendered prompt exceeds its byte limit")
        if _CREDENTIAL_VALUE.search(self.system) or _CREDENTIAL_VALUE.search(user):
            raise PromptRenderError("Prompt content appears to contain a credential")
        return RenderedPrompt(prompt_id=self.prompt_id, version=self.version, system=self.system, user=user)


@dataclass(frozen=True)
class RenderedPrompt:
    prompt_id: str
    version: int
    system: str
    user: str


def _template_variables(template: str, field: str) -> tuple[str, ...]:
    try:
        parsed = tuple(Formatter().parse(template))
    except ValueError:
        raise RegistryError(f"{field} has invalid template braces") from None
    found: list[str] = []
    for _, name, format_spec, conversion in parsed:
        if name is None:
            continue
        if (not _VARIABLE_NAME.fullmatch(name) or format_spec or conversion
                or _SECRET_NAME.search(name)):
            raise RegistryError(f"{field} contains an unsupported template field")
        found.append(name)
    return tuple(dict.fromkeys(found))


@dataclass(frozen=True)
class PolicyRegistry:
    version: int
    max_scene_regenerations: int
    human_approval_required: bool
    autonomous_publishing_enabled: bool
    prompts: Mapping[tuple[str, int], PromptDefinition]

    def get_prompt(self, prompt_id: str, version: int | None = None) -> PromptDefinition:
        """Return the current or requested prompt version without mutation."""
        if version is not None:
            prompt = self.prompts.get((prompt_id, version))
            if prompt is None:
                raise KeyError(f"Unknown prompt definition: {prompt_id!r}")
            return prompt
        versions = [
            prompt for (item_id, _), prompt in self.prompts.items() if item_id == prompt_id
        ]
        if not versions:
            raise KeyError(f"Unknown prompt definition: {prompt_id!r}")
        return max(versions, key=lambda item: item.version)


def _positive_int(value: Any, field: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RegistryError(f"{field} must be an integer >= {minimum}")
    return value


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{field} must be a non-empty string")
    return value


def load_registry(path: str | Path) -> PolicyRegistry:
    """Read a JSON registry and reject unknown keys or unsafe policy values."""
    registry_path = Path(path)
    try:
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RegistryError(f"Cannot read registry: {registry_path}") from exc
    except json.JSONDecodeError as exc:
        raise RegistryError(f"Invalid registry JSON at line {exc.lineno}") from exc

    if not isinstance(raw, dict):
        raise RegistryError("Registry root must be an object")
    expected = {"version", "policy", "prompts"}
    if set(raw) != expected:
        raise RegistryError(f"Registry keys must be exactly {sorted(expected)}")

    policy = raw["policy"]
    if not isinstance(policy, dict) or set(policy) != {
        "max_scene_regenerations", "human_approval_required", "autonomous_publishing_enabled"
    }:
        raise RegistryError("Policy must define exactly the supported policy fields")
    human_approval = policy["human_approval_required"]
    publishing = policy["autonomous_publishing_enabled"]
    if not isinstance(human_approval, bool) or not isinstance(publishing, bool):
        raise RegistryError("Approval and publishing policy values must be booleans")
    if publishing and human_approval:
        raise RegistryError("Autonomous publishing conflicts with required human approval")

    prompt_data = raw["prompts"]
    if not isinstance(prompt_data, list) or not prompt_data:
        raise RegistryError("prompts must be a non-empty array")
    prompts: dict[tuple[str, int], PromptDefinition] = {}
    for index, item in enumerate(prompt_data):
        field = f"prompts[{index}]"
        if not isinstance(item, dict) or set(item) != {"id", "version", "purpose", "system", "template", "variables"}:
            raise RegistryError(f"{field} must define exactly id, version, purpose, system, template, and variables")
        prompt_id = _nonempty_string(item["id"], f"{field}.id")
        version = _positive_int(item["version"], f"{field}.version")
        prompt_key = (prompt_id, version)
        if prompt_key in prompts:
            raise RegistryError(f"Duplicate prompt id/version: {prompt_id}")
        system = _nonempty_string(item["system"], f"{field}.system")
        template = _nonempty_string(item["template"], f"{field}.template")
        if _CREDENTIAL_VALUE.search(system) or _CREDENTIAL_VALUE.search(template):
            raise RegistryError(f"{field} appears to contain a credential")
        if len(system.encode("utf-8")) > MAX_PROMPT_BYTES or len(template.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise RegistryError(f"{field} exceeds the prompt byte limit")
        variables = item["variables"]
        if not isinstance(variables, list) or any(
            type(name) is not str or not _VARIABLE_NAME.fullmatch(name) or _SECRET_NAME.search(name)
            for name in variables
        ) or len(variables) != len(set(variables)):
            raise RegistryError(f"{field}.variables must contain unique safe variable names")
        discovered = _template_variables(template, f"{field}.template")
        if set(discovered) != set(variables):
            raise RegistryError(f"{field}.variables must exactly match template fields")
        prompts[prompt_key] = PromptDefinition(
            prompt_id=prompt_id,
            version=version,
            purpose=_nonempty_string(item["purpose"], f"{field}.purpose"),
            system=system,
            template=template,
            variables=tuple(variables),
        )

    return PolicyRegistry(
        version=_positive_int(raw["version"], "version"),
        max_scene_regenerations=_positive_int(
            policy["max_scene_regenerations"], "max_scene_regenerations", allow_zero=True
        ),
        human_approval_required=human_approval,
        autonomous_publishing_enabled=publishing,
        prompts=MappingProxyType(prompts),
    )
