"""Strict, versioned platform metric definitions with no false equivalence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

from flowx_os.publishing.reconciliation import PublicationPlatform


_VERSION = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")
_METRIC_ID = re.compile(r"^(youtube|instagram|facebook)[.][a-z][a-z0-9_]{0,63}$")
_RAW_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,99}$")
_ALLOWED_SOURCE_HOSTS = frozenset({"developers.google.com", "developers.facebook.com"})
_UNSAFE_TEXT = re.compile(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]")


class MetricDefinitionError(ValueError):
    """The checked-in metric registry is unsafe or internally inconsistent."""


class MetricKind(StrEnum):
    RAW = "RAW"
    DERIVED = "DERIVED"


class MetricUnit(StrEnum):
    COUNT = "COUNT"
    SECONDS = "SECONDS"
    MINUTES = "MINUTES"
    MILLISECONDS = "MILLISECONDS"
    RATIO = "RATIO"
    STRUCTURED = "STRUCTURED"


class MetricFormula(StrEnum):
    SUM_OVER_DENOMINATOR = "SUM_OVER_DENOMINATOR"


class MissingValuePolicy(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    metric_id: str
    platform: PublicationPlatform
    kind: MetricKind
    label: str
    definition: str
    unit: MetricUnit
    platform_only: bool
    missing_value_policy: MissingValuePolicy
    raw_name: str | None
    source_reference: str
    source_api_version: str
    inputs: tuple[str, ...] = ()
    denominator: str | None = None
    formula: MetricFormula | None = None
    calculation_version: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.metric_id, str)
            or not isinstance(self.platform, PublicationPlatform)
            or not isinstance(self.kind, MetricKind)
            or not isinstance(self.label, str)
            or not isinstance(self.definition, str)
            or not isinstance(self.unit, MetricUnit)
            or not isinstance(self.source_reference, str)
            or not isinstance(self.source_api_version, str)
            or not isinstance(self.inputs, tuple)
            or any(not isinstance(value, str) for value in self.inputs)
        ):
            raise MetricDefinitionError("metric definition metadata is invalid")
        prefix = self.platform.value.lower() + "."
        source = urlsplit(self.source_reference)
        if (_METRIC_ID.fullmatch(self.metric_id) is None
                or not self.metric_id.startswith(prefix)
                or not 1 <= len(self.label.strip()) <= 100
                or self.label != self.label.strip()
                or not 1 <= len(self.definition.strip()) <= 1000
                or self.definition != self.definition.strip()
                or self.platform_only is not True
                or self.missing_value_policy is not MissingValuePolicy.UNAVAILABLE
                or _UNSAFE_TEXT.search(self.label) is not None
                or _UNSAFE_TEXT.search(self.definition) is not None
                or source.scheme != "https" or source.hostname not in _ALLOWED_SOURCE_HOSTS
                or source.username is not None or source.password is not None
                or not self.source_api_version.strip()
                or len(self.source_api_version) > 60):
            raise MetricDefinitionError("metric definition metadata is invalid")
        if self.kind is MetricKind.RAW:
            if (_RAW_NAME.fullmatch(self.raw_name or "") is None or self.inputs
                    or self.denominator is not None or self.formula is not None
                    or self.calculation_version is not None):
                raise MetricDefinitionError("raw metric definition is invalid")
        elif self.kind is MetricKind.DERIVED:
            if (self.raw_name is not None or len(self.inputs) < 2
                    or len(self.inputs) != len(set(self.inputs))
                    or self.denominator not in self.inputs
                    or self.formula is not MetricFormula.SUM_OVER_DENOMINATOR
                    or _VERSION.fullmatch(self.calculation_version or "") is None
                    or self.unit is not MetricUnit.RATIO):
                raise MetricDefinitionError("derived metric definition is invalid")
        else:
            raise MetricDefinitionError("metric kind is invalid")


class MetricRegistry:
    def __init__(self, *, version: str, definitions: Sequence[MetricDefinition]) -> None:
        if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
            raise MetricDefinitionError("metric registry version is invalid")
        values = tuple(definitions)
        if not values or len(values) > 500 or not all(
                isinstance(item, MetricDefinition) for item in values):
            raise MetricDefinitionError("metric registry definitions are invalid")
        by_id = {item.metric_id: item for item in values}
        if len(by_id) != len(values):
            raise MetricDefinitionError("metric IDs must be unique")
        raw_keys = [
            (item.platform, item.raw_name) for item in values
            if item.kind is MetricKind.RAW
        ]
        if len(raw_keys) != len(set(raw_keys)):
            raise MetricDefinitionError("raw metric names must be unique per platform")
        for item in values:
            if item.kind is not MetricKind.DERIVED:
                continue
            inputs = [by_id.get(metric_id) for metric_id in item.inputs]
            if (any(value is None for value in inputs)
                    or any(value.platform is not item.platform for value in inputs if value)
                    or any(value.kind is not MetricKind.RAW for value in inputs if value)):
                raise MetricDefinitionError("derived metric inputs must be raw metrics on one platform")
        self.version = version
        self._definitions = values
        self._by_id = MappingProxyType(by_id)
        canonical = json.dumps(
            {
                "version": version,
                "metrics": [_canonical(item) for item in sorted(values, key=lambda item: item.metric_id)],
            },
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        )
        self.fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def definitions(self) -> tuple[MetricDefinition, ...]:
        return self._definitions

    def require(self, metric_id: str) -> MetricDefinition:
        try:
            return self._by_id[metric_id]
        except (KeyError, TypeError):
            raise MetricDefinitionError("metric definition is unavailable") from None

    def for_platform(self, platform: PublicationPlatform) -> tuple[MetricDefinition, ...]:
        if not isinstance(platform, PublicationPlatform):
            raise MetricDefinitionError("metric platform is invalid")
        return tuple(item for item in self._definitions if item.platform is platform)


def _canonical(value: MetricDefinition) -> dict[str, object]:
    return {
        "metric_id": value.metric_id, "platform": value.platform.value,
        "kind": value.kind.value, "label": value.label,
        "definition": value.definition, "unit": value.unit.value,
        "platform_only": value.platform_only,
        "missing_value_policy": value.missing_value_policy.value,
        "raw_name": value.raw_name,
        "source_reference": value.source_reference,
        "source_api_version": value.source_api_version,
        "inputs": list(value.inputs), "denominator": value.denominator,
        "formula": value.formula.value if value.formula else None,
        "calculation_version": value.calculation_version,
    }


def load_metric_registry(path: Path) -> MetricRegistry:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MetricDefinitionError("metric registry could not be loaded") from exc
    if not isinstance(raw, Mapping) or set(raw) != {"registry_version", "metrics"}:
        raise MetricDefinitionError("metric registry shape is invalid")
    metrics = raw["metrics"]
    if not isinstance(metrics, list):
        raise MetricDefinitionError("metric registry metrics must be a list")
    definitions: list[MetricDefinition] = []
    expected = {
        "metric_id", "platform", "kind", "label", "definition", "unit",
        "platform_only", "missing_value_policy", "raw_name",
        "source_reference", "source_api_version",
        "inputs", "denominator", "formula", "calculation_version",
    }
    try:
        for item in metrics:
            if not isinstance(item, Mapping) or set(item) != expected:
                raise MetricDefinitionError("metric entry shape is invalid")
            definitions.append(MetricDefinition(
                metric_id=item["metric_id"], platform=PublicationPlatform(item["platform"]),
                kind=MetricKind(item["kind"]), label=item["label"],
                definition=item["definition"], unit=MetricUnit(item["unit"]),
                platform_only=item["platform_only"],
                missing_value_policy=MissingValuePolicy(item["missing_value_policy"]),
                raw_name=item["raw_name"],
                source_reference=item["source_reference"],
                source_api_version=item["source_api_version"],
                inputs=tuple(item["inputs"]), denominator=item["denominator"],
                formula=MetricFormula(item["formula"]) if item["formula"] else None,
                calculation_version=item["calculation_version"],
            ))
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, MetricDefinitionError):
            raise
        raise MetricDefinitionError("metric entry is invalid") from exc
    return MetricRegistry(version=raw["registry_version"], definitions=definitions)
