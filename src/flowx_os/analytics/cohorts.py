"""Immutable creative-factor evidence and non-causal cohort summaries."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from statistics import median
from uuid import UUID

from flowx_os.analytics.collection import (
    CollectionWindow,
    MetricAvailability,
    StoredMetricObservation,
)
from flowx_os.analytics.metrics import MetricKind, MetricRegistry, MetricUnit
from flowx_os.publishing.reconciliation import PublicationPlatform


_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SAFE_EVIDENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SAFE_VERSION = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")
_SAFE_METRIC_ID = re.compile(r"^[a-z][a-z0-9_.]{2,79}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE_TEXT = re.compile(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]")
_MAX_INTEGER = 9_223_372_036_854_775_807
_MAX_DECIMAL = Decimal("9223372036854775807")


def _aware_utc(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
        and value.utcoffset() == timedelta(0)
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class CreativeFactor(StrEnum):
    NICHE = "NICHE"
    HOOK_TYPE = "HOOK_TYPE"
    SCRIPT_WORD_COUNT = "SCRIPT_WORD_COUNT"
    CTA_TYPE = "CTA_TYPE"
    SCENE_COUNT = "SCENE_COUNT"
    DURATION_SECONDS = "DURATION_SECONDS"
    NARRATOR_VOICE = "NARRATOR_VOICE"
    POSTING_TIME_UTC = "POSTING_TIME_UTC"
    PLATFORM = "PLATFORM"
    LANGUAGE = "LANGUAGE"
    VISUAL_MOTIF = "VISUAL_MOTIF"
    FLOW_MODEL = "FLOW_MODEL"
    FLOW_COST_MICROCREDITS = "FLOW_COST_MICROCREDITS"


class FactorValueKind(StrEnum):
    TEXT = "TEXT"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    TIMESTAMP = "TIMESTAMP"


_FACTOR_KINDS = {
    CreativeFactor.NICHE: FactorValueKind.TEXT,
    CreativeFactor.HOOK_TYPE: FactorValueKind.TEXT,
    CreativeFactor.SCRIPT_WORD_COUNT: FactorValueKind.INTEGER,
    CreativeFactor.CTA_TYPE: FactorValueKind.TEXT,
    CreativeFactor.SCENE_COUNT: FactorValueKind.INTEGER,
    CreativeFactor.DURATION_SECONDS: FactorValueKind.DECIMAL,
    CreativeFactor.NARRATOR_VOICE: FactorValueKind.TEXT,
    CreativeFactor.POSTING_TIME_UTC: FactorValueKind.TIMESTAMP,
    CreativeFactor.PLATFORM: FactorValueKind.TEXT,
    CreativeFactor.LANGUAGE: FactorValueKind.TEXT,
    CreativeFactor.VISUAL_MOTIF: FactorValueKind.TEXT,
    CreativeFactor.FLOW_MODEL: FactorValueKind.TEXT,
    CreativeFactor.FLOW_COST_MICROCREDITS: FactorValueKind.INTEGER,
}


class FactorAvailability(StrEnum):
    OBSERVED = "OBSERVED"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class FactorUnavailableReason(StrEnum):
    NOT_CAPTURED = "NOT_CAPTURED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SOURCE_AMBIGUOUS = "SOURCE_AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class CreativeFactorDatum:
    factor: CreativeFactor
    availability: FactorAvailability
    value: str | int | Decimal | datetime | None
    evidence_ref: str | None = None
    unavailable_reason: FactorUnavailableReason | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.factor, CreativeFactor) or not isinstance(
            self.availability, FactorAvailability,
        ):
            raise ValueError("creative factor datum is invalid")
        if self.availability is FactorAvailability.OBSERVED:
            if (
                self.value is None
                or _SAFE_EVIDENCE.fullmatch(self.evidence_ref or "") is None
                or self.unavailable_reason is not None
            ):
                raise ValueError("observed creative factor evidence is invalid")
            self._validate_value()
        elif self.availability is FactorAvailability.UNAVAILABLE:
            if (
                self.value is not None
                or self.evidence_ref is not None
                or not isinstance(self.unavailable_reason, FactorUnavailableReason)
            ):
                raise ValueError("unavailable creative factor evidence is invalid")
        elif self.availability is FactorAvailability.NOT_APPLICABLE:
            if self.value is not None or self.evidence_ref is not None or self.unavailable_reason is not None:
                raise ValueError("inapplicable creative factor evidence is invalid")
        else:
            raise ValueError("creative factor availability is invalid")

    def _validate_value(self) -> None:
        kind = _FACTOR_KINDS[self.factor]
        value = self.value
        if kind is FactorValueKind.TEXT:
            if (
                not isinstance(value, str)
                or value != value.strip()
                or not 1 <= len(value) <= 200
                or _UNSAFE_TEXT.search(value) is not None
            ):
                raise ValueError("creative text factor is invalid")
        elif kind is FactorValueKind.INTEGER:
            if type(value) is not int or not 0 <= value <= _MAX_INTEGER:
                raise ValueError("creative integer factor is invalid")
        elif kind is FactorValueKind.DECIMAL:
            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or not Decimal("0") <= value <= _MAX_DECIMAL
            ):
                raise ValueError("creative decimal factor is invalid")
        elif kind is FactorValueKind.TIMESTAMP:
            if not _aware_utc(value):
                raise ValueError("creative timestamp factor is invalid")

    @property
    def canonical_value(self) -> str | None:
        if self.availability is not FactorAvailability.OBSERVED:
            return None
        if isinstance(self.value, datetime):
            return _timestamp(self.value)
        if isinstance(self.value, Decimal):
            return format(self.value, "f")
        return str(self.value)

    def canonical(self) -> dict[str, object]:
        return {
            "factor": self.factor.value,
            "availability": self.availability.value,
            "value": self.canonical_value,
            "evidence_ref": self.evidence_ref,
            "unavailable_reason": (
                self.unavailable_reason.value if self.unavailable_reason else None
            ),
        }


@dataclass(frozen=True, slots=True)
class CreativeMetadataSnapshot:
    snapshot_id: UUID
    owner_user_id: str
    brand_id: UUID
    content_id: UUID
    publication_id: UUID
    artifact_version: int
    storyboard_version: int
    platform: PublicationPlatform
    published_at: datetime
    schema_version: str
    source_fingerprint: str
    factors: tuple[CreativeFactorDatum, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        factors = tuple(sorted(self.factors, key=lambda item: item.factor.value)) if isinstance(
            self.factors, tuple,
        ) and all(isinstance(item, CreativeFactorDatum) for item in self.factors) else ()
        by_factor = {item.factor: item for item in factors}
        platform = by_factor.get(CreativeFactor.PLATFORM)
        posting_time = by_factor.get(CreativeFactor.POSTING_TIME_UTC)
        if (
            not isinstance(self.snapshot_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.brand_id, UUID)
            or not isinstance(self.content_id, UUID)
            or not isinstance(self.publication_id, UUID)
            or type(self.artifact_version) is not int
            or not 1 <= self.artifact_version <= 1_000_000
            or type(self.storyboard_version) is not int
            or not 1 <= self.storyboard_version <= 1_000_000
            or not isinstance(self.platform, PublicationPlatform)
            or not _aware_utc(self.published_at)
            or _SAFE_VERSION.fullmatch(self.schema_version or "") is None
            or _HEX64.fullmatch(self.source_fingerprint or "") is None
            or len(factors) != len(CreativeFactor)
            or set(by_factor) != set(CreativeFactor)
            or platform is None
            or platform.availability is not FactorAvailability.OBSERVED
            or platform.value != self.platform.value
            or posting_time is None
            or posting_time.availability is not FactorAvailability.OBSERVED
            or posting_time.value != self.published_at
            or not _aware_utc(self.created_at)
            or self.created_at < self.published_at
        ):
            raise ValueError("creative metadata snapshot is invalid")
        object.__setattr__(self, "factors", factors)

    def require_factor(self, factor: CreativeFactor) -> CreativeFactorDatum:
        if not isinstance(factor, CreativeFactor):
            raise ValueError("creative factor is invalid")
        return next(item for item in self.factors if item.factor is factor)

    @property
    def fingerprint(self) -> str:
        payload = {
            "snapshot_id": str(self.snapshot_id),
            "owner_user_id": self.owner_user_id,
            "brand_id": str(self.brand_id),
            "content_id": str(self.content_id),
            "publication_id": str(self.publication_id),
            "artifact_version": self.artifact_version,
            "storyboard_version": self.storyboard_version,
            "platform": self.platform.value,
            "published_at": _timestamp(self.published_at),
            "schema_version": self.schema_version,
            "source_fingerprint": self.source_fingerprint,
            "factors": [item.canonical() for item in self.factors],
            "created_at": _timestamp(self.created_at),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CohortBand:
    label: str
    lower_inclusive: Decimal
    upper_exclusive: Decimal

    def __post_init__(self) -> None:
        if (
            not isinstance(self.label, str)
            or self.label != self.label.strip()
            or not 1 <= len(self.label) <= 80
            or _UNSAFE_TEXT.search(self.label) is not None
            or not isinstance(self.lower_inclusive, Decimal)
            or not isinstance(self.upper_exclusive, Decimal)
            or not self.lower_inclusive.is_finite()
            or not self.upper_exclusive.is_finite()
            or self.lower_inclusive < 0
            or self.upper_exclusive <= self.lower_inclusive
            or self.upper_exclusive > _MAX_DECIMAL
        ):
            raise ValueError("cohort band is invalid")

    def contains(self, value: Decimal) -> bool:
        return self.lower_inclusive <= value < self.upper_exclusive

    def canonical(self) -> dict[str, str]:
        return {
            "label": self.label,
            "lower": format(self.lower_inclusive, "f"),
            "upper": format(self.upper_exclusive, "f"),
        }


@dataclass(frozen=True, slots=True)
class CohortAnalysisRequest:
    request_id: UUID
    owner_user_id: str
    definition_version: str
    factor: CreativeFactor
    metric_id: str
    window: CollectionWindow
    registry_version: str
    registry_fingerprint: str
    minimum_group_size: int = 3
    bands: tuple[CohortBand, ...] = ()

    def __post_init__(self) -> None:
        bands = tuple(self.bands) if isinstance(self.bands, tuple) else ()
        kind = _FACTOR_KINDS.get(self.factor)
        numeric = kind in {FactorValueKind.INTEGER, FactorValueKind.DECIMAL}
        if (
            not isinstance(self.request_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or _SAFE_VERSION.fullmatch(self.definition_version or "") is None
            or not isinstance(self.factor, CreativeFactor)
            or self.factor is CreativeFactor.PLATFORM
            or _SAFE_METRIC_ID.fullmatch(self.metric_id or "") is None
            or not isinstance(self.window, CollectionWindow)
            or _SAFE_VERSION.fullmatch(self.registry_version or "") is None
            or _HEX64.fullmatch(self.registry_fingerprint or "") is None
            or type(self.minimum_group_size) is not int
            or not 3 <= self.minimum_group_size <= 10_000
            or len(bands) > 20
            or not all(isinstance(item, CohortBand) for item in bands)
            or (bands and not numeric)
        ):
            raise ValueError("cohort analysis request is invalid")
        ordered = tuple(sorted(bands, key=lambda item: item.lower_inclusive))
        if any(
            left.upper_exclusive > right.lower_inclusive
            or left.label == right.label
            for left, right in zip(ordered, ordered[1:])
        ):
            raise ValueError("cohort bands overlap or duplicate labels")
        object.__setattr__(self, "bands", ordered)

    @property
    def fingerprint(self) -> str:
        payload = {
            "request_id": str(self.request_id),
            "owner_user_id": self.owner_user_id,
            "definition_version": self.definition_version,
            "factor": self.factor.value,
            "metric_id": self.metric_id,
            "window": self.window.value,
            "registry_version": self.registry_version,
            "registry_fingerprint": self.registry_fingerprint,
            "minimum_group_size": self.minimum_group_size,
            "bands": [item.canonical() for item in self.bands],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CohortCandidate:
    publication_id: UUID
    owner_user_id: str
    metadata: CreativeMetadataSnapshot | None
    observation: StoredMetricObservation | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.publication_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or (self.metadata is not None and not isinstance(self.metadata, CreativeMetadataSnapshot))
            or (self.observation is not None and not isinstance(self.observation, StoredMetricObservation))
        ):
            raise ValueError("cohort candidate is invalid")


class CohortExclusionReason(StrEnum):
    METADATA_UNAVAILABLE = "METADATA_UNAVAILABLE"
    SNAPSHOT_UNAVAILABLE = "SNAPSHOT_UNAVAILABLE"
    FACTOR_UNAVAILABLE = "FACTOR_UNAVAILABLE"
    METRIC_UNAVAILABLE = "METRIC_UNAVAILABLE"
    OUTSIDE_BANDS = "OUTSIDE_BANDS"


class CohortReportStatus(StrEnum):
    DESCRIPTIVE = "DESCRIPTIVE"
    INSUFFICIENT_COHORTS = "INSUFFICIENT_COHORTS"


@dataclass(frozen=True, slots=True)
class CohortSummary:
    label: str
    sample_size: int
    eligible: bool
    median: Decimal | None
    first_quartile: Decimal | None
    third_quartile: Decimal | None

    def __post_init__(self) -> None:
        values = (self.first_quartile, self.median, self.third_quartile)
        if (
            not isinstance(self.label, str)
            or not self.label
            or type(self.sample_size) is not int
            or self.sample_size < 1
            or type(self.eligible) is not bool
            or (self.eligible and any(
                value is None for value in (
                    self.median, self.first_quartile, self.third_quartile,
                )
            ))
            or (not self.eligible and any(
                value is not None for value in (
                    self.median, self.first_quartile, self.third_quartile,
                )
            ))
            or (self.eligible and (
                not all(isinstance(value, Decimal) and value.is_finite() for value in values)
                or not self.first_quartile <= self.median <= self.third_quartile
            ))
        ):
            raise ValueError("cohort summary is invalid")


@dataclass(frozen=True, slots=True)
class CohortAnalysisReport:
    request_fingerprint: str
    status: CohortReportStatus
    interpretation: str
    candidate_count: int
    included_count: int
    exclusions: tuple[tuple[CohortExclusionReason, int], ...]
    cohorts: tuple[CohortSummary, ...]
    source_fingerprints: tuple[str, ...]

    def __post_init__(self) -> None:
        exclusion_total = sum(count for _, count in self.exclusions) if all(
            isinstance(item, tuple) and len(item) == 2 and type(item[1]) is int
            for item in self.exclusions
        ) else -1
        eligible_count = sum(item.eligible for item in self.cohorts) if all(
            isinstance(item, CohortSummary) for item in self.cohorts
        ) else -1
        if (
            _HEX64.fullmatch(self.request_fingerprint or "") is None
            or not isinstance(self.status, CohortReportStatus)
            or self.interpretation != "DESCRIPTIVE_ASSOCIATION_ONLY_NOT_CAUSAL"
            or type(self.candidate_count) is not int
            or type(self.included_count) is not int
            or not 0 <= self.included_count <= self.candidate_count <= 10_000
            or tuple(sorted(self.exclusions, key=lambda item: item[0].value)) != self.exclusions
            or not all(
                isinstance(reason, CohortExclusionReason)
                and type(count) is int and count >= 0
                for reason, count in self.exclusions
            )
            or {reason for reason, _ in self.exclusions} != set(CohortExclusionReason)
            or tuple(sorted(self.cohorts, key=lambda item: item.label)) != self.cohorts
            or not all(isinstance(item, CohortSummary) for item in self.cohorts)
            or len({item.label for item in self.cohorts}) != len(self.cohorts)
            or sum(item.sample_size for item in self.cohorts) != self.included_count
            or exclusion_total + self.included_count != self.candidate_count
            or (self.status is CohortReportStatus.DESCRIPTIVE) != (eligible_count >= 2)
            or tuple(sorted(self.source_fingerprints)) != self.source_fingerprints
            or len(set(self.source_fingerprints)) != len(self.source_fingerprints)
            or not all(_HEX64.fullmatch(item or "") for item in self.source_fingerprints)
            or len(self.source_fingerprints) != self.included_count * 2
        ):
            raise ValueError("cohort analysis report is invalid")

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def canonical(self) -> dict[str, object]:
        return {
            "request_fingerprint": self.request_fingerprint,
            "status": self.status.value,
            "interpretation": self.interpretation,
            "candidate_count": self.candidate_count,
            "included_count": self.included_count,
            "exclusions": [(reason.value, count) for reason, count in self.exclusions],
            "cohorts": [
                {
                    "label": item.label,
                    "sample_size": item.sample_size,
                    "eligible": item.eligible,
                    "median": format(item.median, "f") if item.median is not None else None,
                    "q1": format(item.first_quartile, "f") if item.first_quartile is not None else None,
                    "q3": format(item.third_quartile, "f") if item.third_quartile is not None else None,
                }
                for item in self.cohorts
            ],
            "source_fingerprints": list(self.source_fingerprints),
        }


def _quartiles(values: list[Decimal]) -> tuple[Decimal, Decimal, Decimal]:
    ordered = sorted(values)
    center = Decimal(median(ordered))
    middle = len(ordered) // 2
    lower = ordered[:middle]
    upper = ordered[-middle:]
    return Decimal(median(lower)), center, Decimal(median(upper))


class CreativeCohortAnalyzer:
    """Summarize comparable samples; never infer causality or select a winner."""

    def analyze(
        self, *, request: CohortAnalysisRequest,
        candidates: tuple[CohortCandidate, ...], registry: MetricRegistry,
    ) -> CohortAnalysisReport:
        if (
            not isinstance(request, CohortAnalysisRequest)
            or not isinstance(candidates, tuple)
            or not all(isinstance(item, CohortCandidate) for item in candidates)
            or not 1 <= len(candidates) <= 10_000
            or not isinstance(registry, MetricRegistry)
        ):
            raise ValueError("cohort analysis inputs are invalid")
        definition = registry.require(request.metric_id)
        if (
            request.registry_version != registry.version
            or request.registry_fingerprint != registry.fingerprint
            or definition.kind is not MetricKind.RAW
            or definition.unit not in {
                MetricUnit.COUNT, MetricUnit.SECONDS, MetricUnit.MINUTES,
                MetricUnit.MILLISECONDS,
            }
        ):
            raise ValueError("cohort metric definition is not comparable")
        if len({item.publication_id for item in candidates}) != len(candidates):
            raise ValueError("cohort candidates must be unique by publication")
        exclusions = {reason: 0 for reason in CohortExclusionReason}
        groups: dict[str, list[Decimal]] = {}
        source_fingerprints: set[str] = set()
        for candidate in candidates:
            if candidate.owner_user_id != request.owner_user_id:
                raise ValueError("cohort candidate owner is invalid")
            if candidate.metadata is None:
                exclusions[CohortExclusionReason.METADATA_UNAVAILABLE] += 1
                continue
            metadata = candidate.metadata
            if (
                metadata.owner_user_id != request.owner_user_id
                or metadata.publication_id != candidate.publication_id
                or metadata.platform is not definition.platform
            ):
                raise ValueError("cohort metadata lineage is invalid")
            if candidate.observation is None:
                exclusions[CohortExclusionReason.SNAPSHOT_UNAVAILABLE] += 1
                continue
            observation = candidate.observation.observation
            if (
                candidate.observation.owner_user_id != request.owner_user_id
                or observation.publication_id != candidate.publication_id
                or observation.platform is not metadata.platform
                or observation.window is not request.window
                or observation.registry_version != registry.version
                or observation.registry_fingerprint != registry.fingerprint
            ):
                raise ValueError("cohort metric lineage is invalid")
            factor = metadata.require_factor(request.factor)
            if factor.availability is not FactorAvailability.OBSERVED:
                exclusions[CohortExclusionReason.FACTOR_UNAVAILABLE] += 1
                continue
            try:
                datum = next(item for item in observation.values if item.metric_id == request.metric_id)
            except StopIteration:
                raise ValueError("cohort metric is absent from the exact snapshot") from None
            datum.validate_for(registry)
            if datum.availability is not MetricAvailability.AVAILABLE:
                exclusions[CohortExclusionReason.METRIC_UNAVAILABLE] += 1
                continue
            if type(datum.value) is int:
                metric_value = Decimal(datum.value)
            elif type(datum.value) is float and math.isfinite(datum.value):
                metric_value = Decimal(str(datum.value))
            else:
                raise ValueError("cohort metric value is not scalar")
            label = self._group_label(factor, request.bands)
            if label is None:
                exclusions[CohortExclusionReason.OUTSIDE_BANDS] += 1
                continue
            groups.setdefault(label, []).append(metric_value)
            source_fingerprints.add(metadata.fingerprint)
            source_fingerprints.add(candidate.observation.storage_fingerprint)
        summaries = []
        included_count = sum(len(values) for values in groups.values())
        for label, values in groups.items():
            eligible = len(values) >= request.minimum_group_size
            if eligible:
                q1, center, q3 = _quartiles(values)
            else:
                q1 = center = q3 = None
            summaries.append(CohortSummary(
                label=label, sample_size=len(values), eligible=eligible,
                median=center, first_quartile=q1, third_quartile=q3,
            ))
        eligible_count = sum(item.eligible for item in summaries)
        return CohortAnalysisReport(
            request_fingerprint=request.fingerprint,
            status=(CohortReportStatus.DESCRIPTIVE
                    if eligible_count >= 2 else CohortReportStatus.INSUFFICIENT_COHORTS),
            interpretation="DESCRIPTIVE_ASSOCIATION_ONLY_NOT_CAUSAL",
            candidate_count=len(candidates), included_count=included_count,
            exclusions=tuple(sorted(exclusions.items(), key=lambda item: item[0].value)),
            cohorts=tuple(sorted(summaries, key=lambda item: item.label)),
            source_fingerprints=tuple(sorted(source_fingerprints)),
        )

    @staticmethod
    def _group_label(
        factor: CreativeFactorDatum, bands: tuple[CohortBand, ...],
    ) -> str | None:
        if not bands:
            return factor.canonical_value
        if type(factor.value) is int:
            value = Decimal(factor.value)
        elif isinstance(factor.value, Decimal):
            value = factor.value
        else:
            raise ValueError("numeric cohort bands require a numeric factor")
        return next((band.label for band in bands if band.contains(value)), None)
