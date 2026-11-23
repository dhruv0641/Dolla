"""Evidence-bound, non-causal recommendations and inert experiment proposals."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from flowx_os.analytics.cohorts import (
    CohortAnalysisReport,
    CohortAnalysisRequest,
    CohortExclusionReason,
    CohortReportStatus,
    CohortSource,
    CohortSummary,
    CreativeFactor,
)
from flowx_os.analytics.collection import CollectionWindow
from flowx_os.analytics.metrics import MetricRegistry
from flowx_os.publishing.reconciliation import PublicationPlatform


_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SAFE_VERSION = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")
_SAFE_LABEL = re.compile(r"^[^\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]{1,80}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ASSOCIATION_ONLY = "DESCRIPTIVE_ASSOCIATION_ONLY_NOT_CAUSAL_NO_GUARANTEED_WINNER"
_SAFETY_RULES = (
    "PAUSE_ON_POLICY_OR_SAFETY_SIGNAL",
    "PAUSE_ON_UNKNOWN_AUTH_JOB_OR_SPEND_STATE",
)


def _aware_utc(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
        and value.utcoffset() == timedelta(0)
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


class RecommendationError(ValueError):
    """Recommendation or experiment evidence failed closed."""


class AssociationDirection(StrEnum):
    TREATMENT_MEDIAN_LOWER = "TREATMENT_MEDIAN_LOWER"
    MEDIANS_EQUAL = "MEDIANS_EQUAL"
    TREATMENT_MEDIAN_HIGHER = "TREATMENT_MEDIAN_HIGHER"


class RecommendationStatus(StrEnum):
    HYPOTHESIS_ONLY = "HYPOTHESIS_ONLY"


class ExperimentProposalStatus(StrEnum):
    DRAFT_REQUIRES_HUMAN_APPROVAL = "DRAFT_REQUIRES_HUMAN_APPROVAL"


class AllocationStrategy(StrEnum):
    BALANCED_FIXED_1_TO_1 = "BALANCED_FIXED_1_TO_1"


class StopRule(StrEnum):
    FIXED_SAMPLE_NO_EARLY_EFFICACY_STOP = "FIXED_SAMPLE_NO_EARLY_EFFICACY_STOP"


@dataclass(frozen=True, slots=True)
class RecommendationRequest:
    recommendation_id: UUID
    owner_user_id: str
    report_request_id: UUID
    report_fingerprint: str
    definition_version: str
    control_label: str
    treatment_label: str
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.recommendation_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.report_request_id, UUID)
            or _HEX64.fullmatch(self.report_fingerprint or "") is None
            or _SAFE_VERSION.fullmatch(self.definition_version or "") is None
            or _SAFE_LABEL.fullmatch(self.control_label or "") is None
            or _SAFE_LABEL.fullmatch(self.treatment_label or "") is None
            or self.control_label != self.control_label.strip()
            or self.treatment_label != self.treatment_label.strip()
            or self.control_label == self.treatment_label
            or not _aware_utc(self.created_at)
        ):
            raise RecommendationError("recommendation request is invalid")

    @property
    def fingerprint(self) -> str:
        values = (
            str(self.recommendation_id), self.owner_user_id,
            str(self.report_request_id), self.report_fingerprint,
            self.definition_version, self.control_label, self.treatment_label,
            _timestamp(self.created_at),
        )
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EvidenceBackedRecommendation:
    recommendation_id: UUID
    owner_user_id: str
    request_fingerprint: str
    report_request_id: UUID
    report_request_fingerprint: str
    report_fingerprint: str
    definition_version: str
    factor: CreativeFactor
    platform: PublicationPlatform
    metric_id: str
    window: CollectionWindow
    registry_version: str
    registry_fingerprint: str
    minimum_group_size: int
    control: CohortSummary
    treatment: CohortSummary
    candidate_count: int
    included_count: int
    exclusions: tuple[tuple[CohortExclusionReason, int], ...]
    disclosed_cohorts: tuple[CohortSummary, ...]
    sources: tuple[CohortSource, ...]
    direction: AssociationDirection
    created_at: datetime
    status: RecommendationStatus = RecommendationStatus.HYPOTHESIS_ONLY
    interpretation: str = _ASSOCIATION_ONLY

    def __post_init__(self) -> None:
        exclusion_total = sum(count for _, count in self.exclusions) if all(
            isinstance(item, tuple) and len(item) == 2 and type(item[1]) is int
            for item in self.exclusions
        ) else -1
        if (
            not isinstance(self.recommendation_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or _HEX64.fullmatch(self.request_fingerprint or "") is None
            or not isinstance(self.report_request_id, UUID)
            or _HEX64.fullmatch(self.report_request_fingerprint or "") is None
            or _HEX64.fullmatch(self.report_fingerprint or "") is None
            or _SAFE_VERSION.fullmatch(self.definition_version or "") is None
            or not isinstance(self.factor, CreativeFactor)
            or self.factor is CreativeFactor.PLATFORM
            or not isinstance(self.platform, PublicationPlatform)
            or not isinstance(self.window, CollectionWindow)
            or _SAFE_VERSION.fullmatch(self.registry_version or "") is None
            or _HEX64.fullmatch(self.registry_fingerprint or "") is None
            or type(self.minimum_group_size) is not int
            or not 3 <= self.minimum_group_size <= 10_000
            or not isinstance(self.control, CohortSummary)
            or not isinstance(self.treatment, CohortSummary)
            or not self.control.eligible or not self.treatment.eligible
            or self.control.label == self.treatment.label
            or not isinstance(self.direction, AssociationDirection)
            or not isinstance(self.status, RecommendationStatus)
            or self.status is not RecommendationStatus.HYPOTHESIS_ONLY
            or self.interpretation != _ASSOCIATION_ONLY
            or type(self.candidate_count) is not int
            or type(self.included_count) is not int
            or not 0 <= self.included_count <= self.candidate_count <= 10_000
            or tuple(sorted(self.exclusions, key=lambda item: item[0].value)) != self.exclusions
            or {reason for reason, _ in self.exclusions} != set(CohortExclusionReason)
            or any(not isinstance(reason, CohortExclusionReason) or count < 0
                   for reason, count in self.exclusions)
            or exclusion_total + self.included_count != self.candidate_count
            or tuple(sorted(self.disclosed_cohorts, key=lambda item: item.label))
               != self.disclosed_cohorts
            or not all(isinstance(item, CohortSummary) for item in self.disclosed_cohorts)
            or len({item.label for item in self.disclosed_cohorts})
               != len(self.disclosed_cohorts)
            or sum(item.sample_size for item in self.disclosed_cohorts) != self.included_count
            or self.control not in self.disclosed_cohorts
            or self.treatment not in self.disclosed_cohorts
            or tuple(sorted(self.sources, key=lambda item: item.publication_id.hex)) != self.sources
            or not all(isinstance(item, CohortSource) for item in self.sources)
            or len(self.sources) != self.included_count
            or not _aware_utc(self.created_at)
        ):
            raise RecommendationError("evidence-backed recommendation is invalid")

    @property
    def fingerprint(self) -> str:
        values = [
            str(self.recommendation_id), self.owner_user_id,
            self.request_fingerprint, str(self.report_request_id),
            self.report_request_fingerprint, self.report_fingerprint,
            self.definition_version, self.factor.value, self.platform.value,
            self.metric_id, self.window.value, self.registry_version,
            self.registry_fingerprint, str(self.minimum_group_size),
            self.control.label, self.treatment.label, self.direction.value,
            self.status.value, self.interpretation,
            str(self.candidate_count), str(self.included_count),
            _timestamp(self.created_at),
        ]
        for reason, count in self.exclusions:
            values.extend((reason.value, str(count)))
        for item in self.disclosed_cohorts:
            values.extend((
                item.label, str(item.sample_size), str(item.eligible).lower(),
                _decimal(item.median) or "", _decimal(item.first_quartile) or "",
                _decimal(item.third_quartile) or "",
            ))
        for item in self.sources:
            values.extend((
                str(item.publication_id), str(item.metadata_snapshot_id),
                item.metadata_fingerprint, str(item.observation_request_id),
                item.observation_fingerprint,
            ))
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()

    def canonical(self) -> dict[str, object]:
        return {
            "recommendation_id": str(self.recommendation_id),
            "owner_user_id": self.owner_user_id,
            "request_fingerprint": self.request_fingerprint,
            "report_request_id": str(self.report_request_id),
            "report_request_fingerprint": self.report_request_fingerprint,
            "report_fingerprint": self.report_fingerprint,
            "definition_version": self.definition_version,
            "factor": self.factor.value,
            "platform": self.platform.value,
            "metric_id": self.metric_id,
            "window": self.window.value,
            "registry_version": self.registry_version,
            "registry_fingerprint": self.registry_fingerprint,
            "minimum_group_size": self.minimum_group_size,
            "control": _summary(self.control),
            "treatment": _summary(self.treatment),
            "candidate_count": self.candidate_count,
            "included_count": self.included_count,
            "exclusions": [(reason.value, count) for reason, count in self.exclusions],
            "disclosed_cohorts": [_summary(item) for item in self.disclosed_cohorts],
            "sources": [item.canonical() for item in self.sources],
            "direction": self.direction.value,
            "status": self.status.value,
            "interpretation": self.interpretation,
            "created_at": _timestamp(self.created_at),
        }


class RecommendationEngine:
    """Convert one immutable descriptive report into a review-only hypothesis."""

    def propose(
        self, *, request: RecommendationRequest,
        analysis_request: CohortAnalysisRequest,
        report: CohortAnalysisReport, registry: MetricRegistry,
    ) -> EvidenceBackedRecommendation:
        if (
            not isinstance(request, RecommendationRequest)
            or not isinstance(analysis_request, CohortAnalysisRequest)
            or not isinstance(report, CohortAnalysisReport)
            or not isinstance(registry, MetricRegistry)
            or request.owner_user_id != analysis_request.owner_user_id
            or request.report_request_id != analysis_request.request_id
            or request.report_fingerprint != report.fingerprint
            or report.request_fingerprint != analysis_request.fingerprint
            or report.status is not CohortReportStatus.DESCRIPTIVE
            or sum(item.eligible for item in report.cohorts) < 2
            or analysis_request.registry_version != registry.version
            or analysis_request.registry_fingerprint != registry.fingerprint
        ):
            raise RecommendationError("descriptive cohort evidence is unavailable or mismatched")
        definition = registry.require(analysis_request.metric_id)
        cohorts = {item.label: item for item in report.cohorts}
        control = cohorts.get(request.control_label)
        treatment = cohorts.get(request.treatment_label)
        if control is None or treatment is None or not control.eligible or not treatment.eligible:
            raise RecommendationError("both selected cohorts require eligible evidence")
        direction = (
            AssociationDirection.TREATMENT_MEDIAN_HIGHER
            if treatment.median > control.median
            else AssociationDirection.TREATMENT_MEDIAN_LOWER
            if treatment.median < control.median
            else AssociationDirection.MEDIANS_EQUAL
        )
        return EvidenceBackedRecommendation(
            recommendation_id=request.recommendation_id,
            owner_user_id=request.owner_user_id,
            request_fingerprint=request.fingerprint,
            report_request_id=request.report_request_id,
            report_request_fingerprint=analysis_request.fingerprint,
            report_fingerprint=report.fingerprint,
            definition_version=request.definition_version,
            factor=analysis_request.factor,
            platform=definition.platform,
            metric_id=analysis_request.metric_id,
            window=analysis_request.window,
            registry_version=analysis_request.registry_version,
            registry_fingerprint=analysis_request.registry_fingerprint,
            minimum_group_size=analysis_request.minimum_group_size,
            control=control, treatment=treatment,
            candidate_count=report.candidate_count,
            included_count=report.included_count,
            exclusions=report.exclusions,
            disclosed_cohorts=report.cohorts,
            sources=report.sources,
            direction=direction,
            created_at=request.created_at,
        )


@dataclass(frozen=True, slots=True)
class ExperimentProposalRequest:
    proposal_id: UUID
    owner_user_id: str
    recommendation_id: UUID
    recommendation_fingerprint: str
    definition_version: str
    minimum_sample_per_arm: int
    target_sample_per_arm: int
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.proposal_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.recommendation_id, UUID)
            or _HEX64.fullmatch(self.recommendation_fingerprint or "") is None
            or _SAFE_VERSION.fullmatch(self.definition_version or "") is None
            or type(self.minimum_sample_per_arm) is not int
            or type(self.target_sample_per_arm) is not int
            or not 3 <= self.minimum_sample_per_arm <= self.target_sample_per_arm <= 10_000
            or not _aware_utc(self.created_at)
        ):
            raise RecommendationError("experiment proposal request is invalid")

    @property
    def fingerprint(self) -> str:
        values = (
            str(self.proposal_id), self.owner_user_id,
            str(self.recommendation_id), self.recommendation_fingerprint,
            self.definition_version, str(self.minimum_sample_per_arm),
            str(self.target_sample_per_arm), _timestamp(self.created_at),
        )
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExperimentProposal:
    proposal_id: UUID
    owner_user_id: str
    request_fingerprint: str
    recommendation_id: UUID
    recommendation_fingerprint: str
    definition_version: str
    factor: CreativeFactor
    platform: PublicationPlatform
    metric_id: str
    window: CollectionWindow
    registry_version: str
    registry_fingerprint: str
    control_label: str
    treatment_label: str
    minimum_sample_per_arm: int
    control_target_size: int
    treatment_target_size: int
    created_at: datetime
    allocation: AllocationStrategy = AllocationStrategy.BALANCED_FIXED_1_TO_1
    stop_rule: StopRule = StopRule.FIXED_SAMPLE_NO_EARLY_EFFICACY_STOP
    safety_rules: tuple[str, ...] = _SAFETY_RULES
    status: ExperimentProposalStatus = ExperimentProposalStatus.DRAFT_REQUIRES_HUMAN_APPROVAL

    def __post_init__(self) -> None:
        if (
            not isinstance(self.proposal_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or _HEX64.fullmatch(self.request_fingerprint or "") is None
            or not isinstance(self.recommendation_id, UUID)
            or _HEX64.fullmatch(self.recommendation_fingerprint or "") is None
            or _SAFE_VERSION.fullmatch(self.definition_version or "") is None
            or not isinstance(self.factor, CreativeFactor)
            or self.factor is CreativeFactor.PLATFORM
            or not isinstance(self.platform, PublicationPlatform)
            or not isinstance(self.window, CollectionWindow)
            or _SAFE_VERSION.fullmatch(self.registry_version or "") is None
            or _HEX64.fullmatch(self.registry_fingerprint or "") is None
            or _SAFE_LABEL.fullmatch(self.control_label or "") is None
            or _SAFE_LABEL.fullmatch(self.treatment_label or "") is None
            or self.control_label == self.treatment_label
            or type(self.minimum_sample_per_arm) is not int
            or type(self.control_target_size) is not int
            or type(self.treatment_target_size) is not int
            or not 3 <= self.minimum_sample_per_arm <= self.control_target_size <= 10_000
            or self.control_target_size != self.treatment_target_size
            or not isinstance(self.allocation, AllocationStrategy)
            or self.allocation is not AllocationStrategy.BALANCED_FIXED_1_TO_1
            or not isinstance(self.stop_rule, StopRule)
            or self.stop_rule is not StopRule.FIXED_SAMPLE_NO_EARLY_EFFICACY_STOP
            or self.safety_rules != _SAFETY_RULES
            or not isinstance(self.status, ExperimentProposalStatus)
            or self.status is not ExperimentProposalStatus.DRAFT_REQUIRES_HUMAN_APPROVAL
            or not _aware_utc(self.created_at)
        ):
            raise RecommendationError("experiment proposal is invalid")

    @property
    def fingerprint(self) -> str:
        values = (
            str(self.proposal_id), self.owner_user_id, self.request_fingerprint,
            str(self.recommendation_id), self.recommendation_fingerprint,
            self.definition_version, self.factor.value, self.platform.value,
            self.metric_id, self.window.value, self.registry_version,
            self.registry_fingerprint, self.control_label, self.treatment_label,
            str(self.minimum_sample_per_arm), str(self.control_target_size),
            str(self.treatment_target_size), self.allocation.value,
            self.stop_rule.value, *self.safety_rules, self.status.value,
            _timestamp(self.created_at),
        )
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()

    def canonical(self) -> dict[str, object]:
        return {
            "proposal_id": str(self.proposal_id),
            "owner_user_id": self.owner_user_id,
            "request_fingerprint": self.request_fingerprint,
            "recommendation_id": str(self.recommendation_id),
            "recommendation_fingerprint": self.recommendation_fingerprint,
            "definition_version": self.definition_version,
            "single_variable": self.factor.value,
            "platform": self.platform.value,
            "metric_id": self.metric_id,
            "window": self.window.value,
            "registry_version": self.registry_version,
            "registry_fingerprint": self.registry_fingerprint,
            "control_label": self.control_label,
            "treatment_label": self.treatment_label,
            "minimum_sample_per_arm": self.minimum_sample_per_arm,
            "control_target_size": self.control_target_size,
            "treatment_target_size": self.treatment_target_size,
            "allocation": self.allocation.value,
            "stop_rule": self.stop_rule.value,
            "safety_rules": list(self.safety_rules),
            "status": self.status.value,
            "human_approval_required": True,
            "execution_authorized": False,
            "generation_authorized": False,
            "spend_authorized": False,
            "account_connection_authorized": False,
            "scheduling_authorized": False,
            "upload_authorized": False,
            "publishing_authorized": False,
            "created_at": _timestamp(self.created_at),
        }


class ExperimentPlanner:
    """Create an inert proposal; TASK-066 owns any approved execution loop."""

    def propose(
        self, *, request: ExperimentProposalRequest,
        recommendation: EvidenceBackedRecommendation,
    ) -> ExperimentProposal:
        if (
            not isinstance(request, ExperimentProposalRequest)
            or not isinstance(recommendation, EvidenceBackedRecommendation)
            or request.owner_user_id != recommendation.owner_user_id
            or request.recommendation_id != recommendation.recommendation_id
            or request.recommendation_fingerprint != recommendation.fingerprint
            or request.created_at < recommendation.created_at
        ):
            raise RecommendationError("recommendation evidence is unavailable or mismatched")
        return ExperimentProposal(
            proposal_id=request.proposal_id,
            owner_user_id=request.owner_user_id,
            request_fingerprint=request.fingerprint,
            recommendation_id=request.recommendation_id,
            recommendation_fingerprint=request.recommendation_fingerprint,
            definition_version=request.definition_version,
            factor=recommendation.factor,
            platform=recommendation.platform,
            metric_id=recommendation.metric_id,
            window=recommendation.window,
            registry_version=recommendation.registry_version,
            registry_fingerprint=recommendation.registry_fingerprint,
            control_label=recommendation.control.label,
            treatment_label=recommendation.treatment.label,
            minimum_sample_per_arm=request.minimum_sample_per_arm,
            control_target_size=request.target_sample_per_arm,
            treatment_target_size=request.target_sample_per_arm,
            created_at=request.created_at,
        )


def _summary(value: CohortSummary) -> dict[str, object]:
    return {
        "label": value.label,
        "sample_size": value.sample_size,
        "eligible": value.eligible,
        "median": _decimal(value.median),
        "q1": _decimal(value.first_quartile),
        "q3": _decimal(value.third_quartile),
    }
