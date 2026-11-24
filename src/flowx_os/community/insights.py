"""Deterministic community-insight proposals with no research execution authority.

This boundary converts an exact persisted community-analysis report into bounded,
review-required research proposals.  It does not read comment text, browse,
invoke a model/provider, publish, spend credits, or call Google Flow.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from flowx_os.community.analysis import CommunityTheme, ThemeCluster


INSIGHT_POLICY_VERSION = "community-insight-v1"
MAX_PROPOSALS = 8
_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SAFE_VERSION = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _aware_utc(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() == timedelta(0)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CommunityInsightError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ResearchPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


_QUESTION_KEYS: dict[CommunityTheme, str] = {
    CommunityTheme.SUPPORT_REQUEST: "investigate_recurring_product_friction",
    CommunityTheme.PRICING: "validate_pricing_clarity_and_objections",
    CommunityTheme.FEATURE_REQUEST: "assess_requested_capability_demand",
    CommunityTheme.CONTENT_REQUEST: "assess_requested_content_demand",
    CommunityTheme.QUESTION: "identify_recurring_knowledge_gaps",
    CommunityTheme.PRAISE: "identify_retention_and_advocacy_drivers",
    CommunityTheme.COMPLAINT: "investigate_recurring_dissatisfaction_causes",
    CommunityTheme.OTHER: "review_uncategorized_community_patterns",
}


@dataclass(frozen=True, slots=True)
class CommunityInsightRequest:
    request_id: UUID
    owner_user_id: str
    publication_id: UUID
    requested_at: datetime
    policy_version: str = INSIGHT_POLICY_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.publication_id, UUID)
            or not _aware_utc(self.requested_at)
            or _SAFE_VERSION.fullmatch(self.policy_version or "") is None
        ):
            raise ValueError("community insight request is invalid")

    @property
    def fingerprint(self) -> str:
        return _sha256("|".join((str(self.request_id), self.owner_user_id,
                                 str(self.publication_id), self.policy_version,
                                 _timestamp(self.requested_at))))


@dataclass(frozen=True, slots=True)
class CommunityInsightSource:
    owner_user_id: str
    publication_id: UUID
    analysis_request_id: UUID
    analysis_report_fingerprint: str
    source_snapshot_fingerprint: str
    analysis_created_at: datetime
    total_comment_count: int
    review_required_count: int
    clusters: tuple[ThemeCluster, ...]

    def __post_init__(self) -> None:
        if (
            _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.publication_id, UUID)
            or not isinstance(self.analysis_request_id, UUID)
            or any(_HEX64.fullmatch(item or "") is None for item in (
                self.analysis_report_fingerprint, self.source_snapshot_fingerprint,
            ))
            or not _aware_utc(self.analysis_created_at)
            or type(self.total_comment_count) is not int
            or type(self.review_required_count) is not int
            or not 0 <= self.review_required_count <= self.total_comment_count <= 5_000
            or not isinstance(self.clusters, tuple)
            or len(self.clusters) > MAX_PROPOSALS
            or any(not isinstance(item, ThemeCluster) for item in self.clusters)
            or tuple(sorted(self.clusters, key=lambda item: item.theme.value)) != self.clusters
            or sum(item.member_count for item in self.clusters) > self.total_comment_count
            or sum(item.review_required_count for item in self.clusters) != self.review_required_count
        ):
            raise ValueError("community insight source is invalid")

    @property
    def fingerprint(self) -> str:
        return _sha256("|".join((
            str(self.analysis_request_id), self.analysis_report_fingerprint,
            self.source_snapshot_fingerprint,
            ",".join(item.cluster_fingerprint for item in self.clusters),
        )))


@dataclass(frozen=True, slots=True)
class ResearchProposal:
    theme: CommunityTheme
    question_key: str
    priority: ResearchPriority
    member_count: int
    review_required_count: int
    source_cluster_fingerprint: str
    proposal_fingerprint: str
    requires_human_review: bool = True
    research_execution_authorized: bool = False

    def __post_init__(self) -> None:
        expected = ""
        if isinstance(self.theme, CommunityTheme) and isinstance(self.priority, ResearchPriority):
            expected = _sha256("|".join((
                self.theme.value, self.question_key, self.priority.value,
                str(self.member_count), str(self.review_required_count),
                self.source_cluster_fingerprint, "true", "false",
            )))
        if (
            self.theme not in _QUESTION_KEYS
            or self.question_key != _QUESTION_KEYS.get(self.theme)
            or type(self.member_count) is not int
            or type(self.review_required_count) is not int
            or not 1 <= self.member_count <= 5_000
            or not 0 <= self.review_required_count <= self.member_count
            or _HEX64.fullmatch(self.source_cluster_fingerprint or "") is None
            or type(self.requires_human_review) is not bool
            or not self.requires_human_review
            or type(self.research_execution_authorized) is not bool
            or self.research_execution_authorized
            or self.proposal_fingerprint != expected
        ):
            raise ValueError("research proposal is invalid")


@dataclass(frozen=True, slots=True)
class CommunityInsightRecord:
    request_id: UUID
    owner_user_id: str
    publication_id: UUID
    request_fingerprint: str
    policy_version: str
    analysis_request_id: UUID
    analysis_report_fingerprint: str
    source_snapshot_fingerprint: str
    insight_source_fingerprint: str
    proposals: tuple[ResearchProposal, ...]
    requested_at: datetime
    created_at: datetime
    record_fingerprint: str
    external_browsing_authorized: bool = False
    model_execution_authorized: bool = False
    provider_action_authorized: bool = False
    account_action_authorized: bool = False
    publishing_authorized: bool = False
    spend_authorized: bool = False
    flow_authorized: bool = False

    def __post_init__(self) -> None:
        authorities = (
            self.external_browsing_authorized, self.model_execution_authorized,
            self.provider_action_authorized, self.account_action_authorized,
            self.publishing_authorized, self.spend_authorized, self.flow_authorized,
        )
        expected = ""
        if _aware_utc(self.requested_at) and _aware_utc(self.created_at):
            expected = _sha256("|".join((
                str(self.request_id), self.owner_user_id, str(self.publication_id),
                self.request_fingerprint, self.policy_version,
                str(self.analysis_request_id), self.analysis_report_fingerprint,
                self.source_snapshot_fingerprint, self.insight_source_fingerprint,
                ",".join(item.proposal_fingerprint for item in self.proposals),
                _timestamp(self.requested_at), _timestamp(self.created_at),
                "false", "false", "false", "false", "false", "false", "false",
            )))
        if (
            not isinstance(self.request_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.publication_id, UUID)
            or not isinstance(self.analysis_request_id, UUID)
            or any(_HEX64.fullmatch(item or "") is None for item in (
                self.request_fingerprint, self.analysis_report_fingerprint,
                self.source_snapshot_fingerprint, self.insight_source_fingerprint,
                self.record_fingerprint,
            ))
            or _SAFE_VERSION.fullmatch(self.policy_version or "") is None
            or not isinstance(self.proposals, tuple)
            or len(self.proposals) > MAX_PROPOSALS
            or any(not isinstance(item, ResearchProposal) for item in self.proposals)
            or tuple(sorted(self.proposals, key=lambda item: item.theme.value)) != self.proposals
            or len({item.theme for item in self.proposals}) != len(self.proposals)
            or not _aware_utc(self.requested_at)
            or self.created_at != self.requested_at
            or any(type(value) is not bool or value for value in authorities)
            or self.record_fingerprint != expected
        ):
            raise ValueError("community insight record is invalid")


@dataclass(frozen=True, slots=True)
class CommunityInsightPolicy:
    enabled: bool = False
    maximum_proposals: int = MAX_PROPOSALS

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or type(self.maximum_proposals) is not int or not 1 <= self.maximum_proposals <= MAX_PROPOSALS:
            raise ValueError("community insight policy is invalid")


class CommunityInsightStore(Protocol):
    async def get_existing(self, request: CommunityInsightRequest) -> CommunityInsightRecord | None: ...
    async def load_source(self, request: CommunityInsightRequest) -> CommunityInsightSource: ...
    async def persist(self, request: CommunityInsightRequest, source: CommunityInsightSource,
                      record: CommunityInsightRecord) -> CommunityInsightRecord: ...


class CommunityInsightService:
    def __init__(self, store: CommunityInsightStore, policy: CommunityInsightPolicy | None = None) -> None:
        self._store = store
        self._policy = policy or CommunityInsightPolicy()

    async def propose(self, request: CommunityInsightRequest, *, now: datetime) -> CommunityInsightRecord:
        if not isinstance(request, CommunityInsightRequest) or not _aware_utc(now):
            raise ValueError("community insight invocation is invalid")
        if now < request.requested_at:
            raise CommunityInsightError("REQUEST_FROM_FUTURE", "community insight request is in the future")
        if not self._policy.enabled:
            raise CommunityInsightError("INSIGHTS_DISABLED", "community insights are disabled by policy")
        if request.policy_version != INSIGHT_POLICY_VERSION:
            raise CommunityInsightError("POLICY_VERSION_UNAVAILABLE", "community insight policy is unavailable")
        existing = await self._store.get_existing(request)
        if existing is not None:
            return self._require_identity(existing, request)
        source = await self._store.load_source(request)
        if source.owner_user_id != request.owner_user_id or source.publication_id != request.publication_id:
            raise CommunityInsightError("SOURCE_IDENTITY_MISMATCH", "community analysis identity changed")
        if request.requested_at < source.analysis_created_at:
            raise CommunityInsightError("REQUEST_PRECEDES_SOURCE", "insight request predates analysis")
        if len(source.clusters) > self._policy.maximum_proposals:
            raise CommunityInsightError("PROPOSAL_LIMIT_EXCEEDED", "community proposals exceed configured limit")
        record = self._build(request, source)
        persisted = await self._store.persist(request, source, record)
        self._require_identity(persisted, request)
        if persisted != record:
            raise CommunityInsightError("PERSISTED_RECORD_MISMATCH", "stored community insight differs from exact result")
        return persisted

    @staticmethod
    def _require_identity(record: CommunityInsightRecord, request: CommunityInsightRequest) -> CommunityInsightRecord:
        if (not isinstance(record, CommunityInsightRecord) or record.request_id != request.request_id
                or record.owner_user_id != request.owner_user_id or record.publication_id != request.publication_id
                or record.request_fingerprint != request.fingerprint or record.policy_version != request.policy_version
                or record.requested_at != request.requested_at):
            raise CommunityInsightError("STORED_RECORD_IDENTITY_MISMATCH", "stored community insight identity is invalid")
        return record

    @staticmethod
    def _build(request: CommunityInsightRequest, source: CommunityInsightSource) -> CommunityInsightRecord:
        proposals = []
        for cluster in source.clusters:
            priority = (ResearchPriority.HIGH if cluster.review_required_count
                        else ResearchPriority.MEDIUM if cluster.member_count >= 3
                        else ResearchPriority.LOW)
            key = _QUESTION_KEYS[cluster.theme]
            fingerprint = _sha256("|".join((cluster.theme.value, key, priority.value,
                str(cluster.member_count), str(cluster.review_required_count),
                cluster.cluster_fingerprint, "true", "false")))
            proposals.append(ResearchProposal(cluster.theme, key, priority,
                cluster.member_count, cluster.review_required_count,
                cluster.cluster_fingerprint, fingerprint))
        ordered = tuple(sorted(proposals, key=lambda item: item.theme.value))
        values = (
            str(request.request_id), request.owner_user_id, str(request.publication_id),
            request.fingerprint, request.policy_version, str(source.analysis_request_id),
            source.analysis_report_fingerprint, source.source_snapshot_fingerprint,
            source.fingerprint,
            ",".join(item.proposal_fingerprint for item in ordered),
            _timestamp(request.requested_at), _timestamp(request.requested_at),
            "false", "false", "false", "false", "false", "false", "false",
        )
        return CommunityInsightRecord(
            request_id=request.request_id, owner_user_id=request.owner_user_id,
            publication_id=request.publication_id, request_fingerprint=request.fingerprint,
            policy_version=request.policy_version,
            analysis_request_id=source.analysis_request_id,
            analysis_report_fingerprint=source.analysis_report_fingerprint,
            source_snapshot_fingerprint=source.source_snapshot_fingerprint,
            insight_source_fingerprint=source.fingerprint, proposals=ordered,
            requested_at=request.requested_at, created_at=request.requested_at,
            record_fingerprint=_sha256("|".join(values)),
        )
