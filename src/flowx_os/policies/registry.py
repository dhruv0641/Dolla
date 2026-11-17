"""Load and validate a local, versioned prompt and policy registry.

Registry content is configuration, not executable code. This module does not
call model providers and does not interpolate user or remote content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RegistryError(ValueError):
    """Raised when a registry is unreadable or violates its schema."""


@dataclass(frozen=True)
class PromptDefinition:
    prompt_id: str
    version: int
    purpose: str
    system: str


@dataclass(frozen=True)
class PolicyRegistry:
    version: int
    max_scene_regenerations: int
    human_approval_required: bool
    autonomous_publishing_enabled: bool
    prompts: dict[str, PromptDefinition]

    def get_prompt(self, prompt_id: str, version: int | None = None) -> PromptDefinition:
        """Return the current or requested prompt version without mutation."""
        prompt = self.prompts.get(prompt_id)
        if prompt is None or (version is not None and prompt.version != version):
            raise KeyError(f"Unknown prompt definition: {prompt_id!r}")
        return prompt


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
    prompts: dict[str, PromptDefinition] = {}
    for index, item in enumerate(prompt_data):
        field = f"prompts[{index}]"
        if not isinstance(item, dict) or set(item) != {"id", "version", "purpose", "system"}:
            raise RegistryError(f"{field} must define exactly id, version, purpose, and system")
        prompt_id = _nonempty_string(item["id"], f"{field}.id")
        if prompt_id in prompts:
            raise RegistryError(f"Duplicate prompt id: {prompt_id}")
        prompts[prompt_id] = PromptDefinition(
            prompt_id=prompt_id,
            version=_positive_int(item["version"], f"{field}.version"),
            purpose=_nonempty_string(item["purpose"], f"{field}.purpose"),
            system=_nonempty_string(item["system"], f"{field}.system"),
        )

    return PolicyRegistry(
        version=_positive_int(raw["version"], "version"),
        max_scene_regenerations=_positive_int(
            policy["max_scene_regenerations"], "max_scene_regenerations", allow_zero=True
        ),
        human_approval_required=human_approval,
        autonomous_publishing_enabled=publishing,
        prompts=prompts,
    )
