"""Deterministic, evidence-bound community theme and safety analysis.

Comment text is untrusted input.  This module performs only bounded local rule
evaluation; it never builds prompts, invokes a model, or grants outbound action
authority.  ``NO_DETECTED_SIGNAL`` means that this versioned rule set did not
match, not that content is safe.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from flowx_os.community.comments import CommentState
from flowx_os.publishing.reconciliation import PublicationPlatform


THEME_TAXONOMY_VERSION = "community-theme-v1"
SAFETY_POLICY_VERSION = "community-safety-v1"

_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SAFE_REMOTE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_SAFE_VERSION = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")
_SAFE_RULE_ID = re.compile(r"^[a-z][a-z0-9._-]{0,79}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[ .()-]?){8,15}(?!\d)")
_SPACE = re.compile(r"[ \t\r\n]+")
_BIDI_CONTROLS = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
_ASCII_LOWER = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz",
)


def _aware_utc(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == timedelta(0)
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized(value: str) -> str:
    return _SPACE.sub(" ", value.translate(_ASCII_LOWER)).strip()


def _valid_untrusted_text(value: str) -> bool:
    return not any(
        character in _BIDI_CONTROLS
        or (ord(character) < 32 and character not in "\t\n\r")
        or ord(character) == 127
        for character in value
    )


class CommunityAnalysisError(RuntimeError):
    """A stable fail-closed community-analysis failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CommunityTheme(StrEnum):
    SUPPORT_REQUEST = "SUPPORT_REQUEST"
    PRICING = "PRICING"
    FEATURE_REQUEST = "FEATURE_REQUEST"
    CONTENT_REQUEST = "CONTENT_REQUEST"
    QUESTION = "QUESTION"
    PRAISE = "PRAISE"
    COMPLAINT = "COMPLAINT"
    OTHER = "OTHER"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"


class SafetyCategory(StrEnum):
    NO_DETECTED_SIGNAL = "NO_DETECTED_SIGNAL"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    SPAM_OR_SCAM = "SPAM_OR_SCAM"
    HARASSMENT = "HARASSMENT"
    PERSONAL_DATA = "PERSONAL_DATA"
    SEXUAL_CONTENT = "SEXUAL_CONTENT"
    HATE = "HATE"
    VIOLENCE = "VIOLENCE"
    SELF_HARM = "SELF_HARM"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"


class SafetySeverity(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AnalysisStatus(StrEnum):
    EMPTY = "EMPTY"
    CLASSIFIED = "CLASSIFIED"


_SEVERITY_ORDER = {
    SafetySeverity.NONE: 0,
    SafetySeverity.LOW: 1,
    SafetySeverity.MEDIUM: 2,
    SafetySeverity.HIGH: 3,
    SafetySeverity.CRITICAL: 4,
}

_SAFETY_RULES: tuple[
    tuple[str, SafetyCategory, SafetySeverity, tuple[str, ...]], ...
] = (
    ("safety.prompt_injection", SafetyCategory.PROMPT_INJECTION,
     SafetySeverity.MEDIUM, (
         "ignore previous instructions", "reveal system prompt", "developer message",
     )),
    ("safety.spam_scam", SafetyCategory.SPAM_OR_SCAM, SafetySeverity.MEDIUM, (
        "guaranteed profit", "crypto giveaway", "contact me on whatsapp",
        "contact me on telegram",
    )),
    ("safety.harassment", SafetyCategory.HARASSMENT, SafetySeverity.MEDIUM, (
        "you are stupid", " idiot", " loser",
    )),
    ("safety.sexual", SafetyCategory.SEXUAL_CONTENT, SafetySeverity.HIGH, (
        "explicit sexual", "send nudes", " porn",
    )),
    ("safety.hate", SafetyCategory.HATE, SafetySeverity.HIGH, (
        "hate speech", "racial slur",
    )),
    ("safety.violence", SafetyCategory.VIOLENCE, SafetySeverity.CRITICAL, (
        "kill you", "hurt you", "shoot you", "bomb threat",
    )),
    ("safety.self_harm", SafetyCategory.SELF_HARM, SafetySeverity.CRITICAL, (
        "kill myself", "end my life", "self harm", "suicide",
    )),
)

_THEME_RULES: tuple[tuple[CommunityTheme, str, tuple[str, ...]], ...] = (
    (CommunityTheme.SUPPORT_REQUEST, "theme.support", (
        " help", "not working", " issue", " problem", " error",
    )),
    (CommunityTheme.PRICING, "theme.pricing", (
        " price", " pricing", " cost", " subscription",
    )),
    (CommunityTheme.FEATURE_REQUEST, "theme.feature_request", (
        " feature", "please add", "would love", "can you add",
    )),
    (CommunityTheme.CONTENT_REQUEST, "theme.content_request", (
        "make a video", "cover this", " tutorial", "next topic",
    )),
    (CommunityTheme.PRAISE, "theme.praise", (
        " love", " great", " amazing", " thank", " awesome",
    )),
    (CommunityTheme.COMPLAINT, "theme.complaint", (
        " awful", " disappointing", " terrible", " hate",
    )),
)

_THEME_RULE_IDS = {
    CommunityTheme.SUPPORT_REQUEST: "theme.support",
    CommunityTheme.PRICING: "theme.pricing",
    CommunityTheme.FEATURE_REQUEST: "theme.feature_request",
    CommunityTheme.CONTENT_REQUEST: "theme.content_request",
    CommunityTheme.QUESTION: "theme.question",
    CommunityTheme.PRAISE: "theme.praise",
    CommunityTheme.COMPLAINT: "theme.complaint",
    CommunityTheme.OTHER: "theme.other",
    CommunityTheme.CONTENT_UNAVAILABLE: "theme.content_unavailable",
}


@dataclass(frozen=True, slots=True)
class CommunityAnalysisRequest:
    request_id: UUID
    owner_user_id: str
    publication_id: UUID
    requested_at: datetime
    theme_taxonomy_version: str = THEME_TAXONOMY_VERSION
    safety_policy_version: str = SAFETY_POLICY_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.publication_id, UUID)
            or not _aware_utc(self.requested_at)
            or _SAFE_VERSION.fullmatch(self.theme_taxonomy_version or "") is None
            or _SAFE_VERSION.fullmatch(self.safety_policy_version or "") is None
        ):
            raise ValueError("community analysis request is invalid")

    @property
    def fingerprint(self) -> str:
        return _sha256("|".join((
            str(self.request_id), self.owner_user_id, str(self.publication_id),
            self.theme_taxonomy_version, self.safety_policy_version,
            _timestamp(self.requested_at),
        )))


@dataclass(frozen=True, slots=True)
class CommunityCommentEvidence:
    version_id: UUID
    publication_id: UUID
    remote_comment_id: str
    comment_fingerprint: str
    text: str | None
    state: CommentState
    provider_updated_at: datetime

    def __post_init__(self) -> None:
        deleted = self.state is CommentState.DELETED
        if (
            not isinstance(self.version_id, UUID)
            or not isinstance(self.publication_id, UUID)
            or _SAFE_REMOTE_ID.fullmatch(self.remote_comment_id or "") is None
            or _HEX64.fullmatch(self.comment_fingerprint or "") is None
            or not isinstance(self.state, CommentState)
            or not _aware_utc(self.provider_updated_at)
            or (deleted and self.text is not None)
            or (not deleted and (
                not isinstance(self.text, str)
                or not 1 <= len(self.text) <= 10_000
                or self.text != self.text.strip()
                or not _valid_untrusted_text(self.text)
            ))
        ):
            raise ValueError("community comment evidence is invalid")


@dataclass(frozen=True, slots=True)
class CommunityEvidenceSnapshot:
    publication_id: UUID
    owner_user_id: str
    platform: PublicationPlatform
    ingestion_sync_id: UUID
    ingestion_target_fingerprint: str
    ingestion_completed_at: datetime
    comments: tuple[CommunityCommentEvidence, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.publication_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.platform, PublicationPlatform)
            or not isinstance(self.ingestion_sync_id, UUID)
            or _HEX64.fullmatch(self.ingestion_target_fingerprint or "") is None
            or not _aware_utc(self.ingestion_completed_at)
            or not isinstance(self.comments, tuple)
            or any(not isinstance(item, CommunityCommentEvidence) for item in self.comments)
            or any(item.publication_id != self.publication_id for item in self.comments)
            or tuple(sorted(self.comments, key=lambda item: item.remote_comment_id))
               != self.comments
            or len({item.remote_comment_id for item in self.comments}) != len(self.comments)
        ):
            raise ValueError("community evidence snapshot is invalid")

    @property
    def fingerprint(self) -> str:
        sources = ",".join(
            f"{item.version_id}:{item.comment_fingerprint}" for item in self.comments
        )
        return _sha256("|".join((
            str(self.ingestion_sync_id), self.ingestion_target_fingerprint, sources,
        )))


@dataclass(frozen=True, slots=True)
class CommentClassification:
    comment_version_id: UUID
    remote_comment_id: str
    comment_fingerprint: str
    theme: CommunityTheme
    theme_rule_id: str
    safety_category: SafetyCategory
    safety_severity: SafetySeverity
    safety_rule_ids: tuple[str, ...]
    requires_human_review: bool
    classification_fingerprint: str

    def __post_init__(self) -> None:
        unavailable = self.theme is CommunityTheme.CONTENT_UNAVAILABLE
        no_signal = self.safety_category is SafetyCategory.NO_DETECTED_SIGNAL
        expected_fingerprint = ""
        if (
            isinstance(self.comment_version_id, UUID)
            and _HEX64.fullmatch(self.comment_fingerprint or "") is not None
            and isinstance(self.theme, CommunityTheme)
            and isinstance(self.safety_category, SafetyCategory)
            and isinstance(self.safety_severity, SafetySeverity)
            and isinstance(self.safety_rule_ids, tuple)
            and type(self.requires_human_review) is bool
        ):
            expected_fingerprint = _sha256("|".join((
                str(self.comment_version_id), self.comment_fingerprint,
                self.theme.value, self.theme_rule_id, self.safety_category.value,
                self.safety_severity.value, ",".join(self.safety_rule_ids),
                str(self.requires_human_review).lower(),
            )))
        if (
            not isinstance(self.comment_version_id, UUID)
            or _SAFE_REMOTE_ID.fullmatch(self.remote_comment_id or "") is None
            or _HEX64.fullmatch(self.comment_fingerprint or "") is None
            or not isinstance(self.theme, CommunityTheme)
            or _SAFE_RULE_ID.fullmatch(self.theme_rule_id or "") is None
            or not isinstance(self.safety_category, SafetyCategory)
            or not isinstance(self.safety_severity, SafetySeverity)
            or not isinstance(self.safety_rule_ids, tuple)
            or tuple(sorted(set(self.safety_rule_ids))) != self.safety_rule_ids
            or any(_SAFE_RULE_ID.fullmatch(item or "") is None for item in self.safety_rule_ids)
            or type(self.requires_human_review) is not bool
            or _HEX64.fullmatch(self.classification_fingerprint or "") is None
            or self.classification_fingerprint != expected_fingerprint
            or self.theme_rule_id != _THEME_RULE_IDS.get(self.theme)
            or unavailable is not (
                self.safety_category is SafetyCategory.CONTENT_UNAVAILABLE
            )
            or (unavailable and (
                self.safety_severity is not SafetySeverity.NONE
                or self.safety_rule_ids
                or self.requires_human_review
            ))
            or (not unavailable and no_signal and (
                self.safety_severity is not SafetySeverity.NONE
                or self.safety_rule_ids
                or self.requires_human_review
            ))
            or (not unavailable and not no_signal and (
                self.safety_category is SafetyCategory.CONTENT_UNAVAILABLE
                or self.safety_severity is SafetySeverity.NONE
                or not self.safety_rule_ids
                or not self.requires_human_review
            ))
        ):
            raise ValueError("comment classification is invalid")


@dataclass(frozen=True, slots=True)
class ThemeCluster:
    theme: CommunityTheme
    member_count: int
    review_required_count: int
    classification_fingerprints: tuple[str, ...]
    cluster_fingerprint: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.theme, CommunityTheme)
            or self.theme is CommunityTheme.CONTENT_UNAVAILABLE
            or type(self.member_count) is not int
            or type(self.review_required_count) is not int
            or not 1 <= self.member_count <= 5_000
            or not 0 <= self.review_required_count <= self.member_count
            or len(self.classification_fingerprints) != self.member_count
            or tuple(sorted(self.classification_fingerprints))
               != self.classification_fingerprints
            or any(_HEX64.fullmatch(value or "") is None
                   for value in self.classification_fingerprints)
            or _HEX64.fullmatch(self.cluster_fingerprint or "") is None
        ):
            raise ValueError("theme cluster is invalid")


@dataclass(frozen=True, slots=True)
class CommunityAnalysisReport:
    request_id: UUID
    owner_user_id: str
    publication_id: UUID
    request_fingerprint: str
    ingestion_sync_id: UUID
    ingestion_target_fingerprint: str
    source_snapshot_fingerprint: str
    theme_taxonomy_version: str
    safety_policy_version: str
    status: AnalysisStatus
    total_comment_count: int
    analyzed_comment_count: int
    deleted_comment_count: int
    review_required_count: int
    classifications: tuple[CommentClassification, ...]
    clusters: tuple[ThemeCluster, ...]
    requested_at: datetime
    created_at: datetime
    report_fingerprint: str
    outbound_action_authorized: bool = False

    def __post_init__(self) -> None:
        active = tuple(
            item for item in self.classifications
            if isinstance(item, CommentClassification)
            and item.theme is not CommunityTheme.CONTENT_UNAVAILABLE
        ) if isinstance(self.classifications, tuple) else ()
        deleted = tuple(
            item for item in self.classifications
            if isinstance(item, CommentClassification)
            and item.theme is CommunityTheme.CONTENT_UNAVAILABLE
        ) if isinstance(self.classifications, tuple) else ()
        cluster_members = sum(item.member_count for item in self.clusters)
        clusters_match = all(
            cluster.classification_fingerprints == tuple(sorted(
                item.classification_fingerprint for item in active
                if item.theme is cluster.theme
            ))
            and cluster.review_required_count == sum(
                item.requires_human_review for item in active
                if item.theme is cluster.theme
            )
            and cluster.cluster_fingerprint == _sha256("|".join((
                str(self.request_id), cluster.theme.value, str(cluster.member_count),
                str(cluster.review_required_count),
                ",".join(cluster.classification_fingerprints),
            )))
            for cluster in self.clusters
        ) if isinstance(self.clusters, tuple) else False
        expected_report = ""
        if (
            isinstance(self.request_id, UUID)
            and isinstance(self.publication_id, UUID)
            and isinstance(self.ingestion_sync_id, UUID)
            and isinstance(self.status, AnalysisStatus)
            and _aware_utc(self.requested_at)
            and _aware_utc(self.created_at)
        ):
            expected_report = _sha256("|".join((
                str(self.request_id), self.owner_user_id, str(self.publication_id),
                self.request_fingerprint, str(self.ingestion_sync_id),
                self.ingestion_target_fingerprint, self.source_snapshot_fingerprint,
                self.theme_taxonomy_version, self.safety_policy_version,
                self.status.value, str(self.total_comment_count),
                str(self.analyzed_comment_count), str(self.deleted_comment_count),
                str(self.review_required_count), str(len(self.clusters)),
                _timestamp(self.requested_at), _timestamp(self.created_at), "false",
            )))
        if (
            not isinstance(self.request_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.publication_id, UUID)
            or not isinstance(self.ingestion_sync_id, UUID)
            or any(_HEX64.fullmatch(value or "") is None for value in (
                self.request_fingerprint, self.ingestion_target_fingerprint,
                self.source_snapshot_fingerprint, self.report_fingerprint,
            ))
            or _SAFE_VERSION.fullmatch(self.theme_taxonomy_version or "") is None
            or _SAFE_VERSION.fullmatch(self.safety_policy_version or "") is None
            or not isinstance(self.status, AnalysisStatus)
            or any(type(value) is not int or not 0 <= value <= 5_000 for value in (
                self.total_comment_count, self.analyzed_comment_count,
                self.deleted_comment_count, self.review_required_count,
            ))
            or self.analyzed_comment_count + self.deleted_comment_count
               != self.total_comment_count
            or self.review_required_count > self.analyzed_comment_count
            or len(self.classifications) != self.total_comment_count
            or len(active) != self.analyzed_comment_count
            or len(deleted) != self.deleted_comment_count
            or sum(item.requires_human_review for item in active)
               != self.review_required_count
            or tuple(sorted(self.classifications, key=lambda item: item.remote_comment_id))
               != self.classifications
            or len({item.remote_comment_id for item in self.classifications})
               != len(self.classifications)
            or tuple(sorted(self.clusters, key=lambda item: item.theme.value)) != self.clusters
            or len({item.theme for item in self.clusters}) != len(self.clusters)
            or cluster_members != self.analyzed_comment_count
            or not clusters_match
            or {item.theme for item in active} != {item.theme for item in self.clusters}
            or sum(item.review_required_count for item in self.clusters)
               != self.review_required_count
            or self.status is not (
                AnalysisStatus.EMPTY if self.total_comment_count == 0
                else AnalysisStatus.CLASSIFIED
            )
            or not _aware_utc(self.requested_at)
            or not _aware_utc(self.created_at)
            or self.created_at < self.requested_at
            or type(self.outbound_action_authorized) is not bool
            or self.outbound_action_authorized
            or self.report_fingerprint != expected_report
        ):
            raise ValueError("community analysis report is invalid")


@dataclass(frozen=True, slots=True)
class CommunityAnalysisPolicy:
    enabled: bool = False
    maximum_comments: int = 5_000

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or type(self.maximum_comments) is not int or not (
            1 <= self.maximum_comments <= 5_000
        ):
            raise ValueError("community analysis policy is invalid")


class CommunityAnalysisStore(Protocol):
    async def get_existing(
        self, request: CommunityAnalysisRequest,
    ) -> CommunityAnalysisReport | None: ...

    async def load_snapshot(
        self, request: CommunityAnalysisRequest, *, maximum_comments: int,
    ) -> CommunityEvidenceSnapshot: ...

    async def persist(
        self, request: CommunityAnalysisRequest, snapshot: CommunityEvidenceSnapshot,
        report: CommunityAnalysisReport,
    ) -> CommunityAnalysisReport: ...


class CommunityAnalyzer:
    """Classify one exact immutable comment snapshot with local versioned rules."""

    def __init__(
        self, store: CommunityAnalysisStore,
        policy: CommunityAnalysisPolicy | None = None,
    ) -> None:
        self._store = store
        self._policy = policy or CommunityAnalysisPolicy()

    async def analyze(
        self, request: CommunityAnalysisRequest, *, now: datetime,
    ) -> CommunityAnalysisReport:
        if not isinstance(request, CommunityAnalysisRequest) or not _aware_utc(now):
            raise ValueError("community analysis invocation is invalid")
        if not self._policy.enabled:
            raise CommunityAnalysisError(
                "ANALYSIS_DISABLED", "community analysis is disabled by policy",
            )
        if request.theme_taxonomy_version != THEME_TAXONOMY_VERSION or (
            request.safety_policy_version != SAFETY_POLICY_VERSION
        ):
            raise CommunityAnalysisError(
                "POLICY_VERSION_UNAVAILABLE", "requested analysis policy is unavailable",
            )
        existing = await self._store.get_existing(request)
        if existing is not None:
            return existing
        snapshot = await self._store.load_snapshot(
            request, maximum_comments=self._policy.maximum_comments,
        )
        if snapshot.owner_user_id != request.owner_user_id or (
            snapshot.publication_id != request.publication_id
        ):
            raise CommunityAnalysisError(
                "EVIDENCE_IDENTITY_MISMATCH", "comment evidence identity changed",
            )
        if request.requested_at < snapshot.ingestion_completed_at:
            raise CommunityAnalysisError(
                "REQUEST_PRECEDES_EVIDENCE", "analysis request predates comment evidence",
            )
        report = self._build_report(request=request, snapshot=snapshot, now=now)
        return await self._store.persist(request, snapshot, report)

    @classmethod
    def _build_report(
        cls, *, request: CommunityAnalysisRequest,
        snapshot: CommunityEvidenceSnapshot, now: datetime,
    ) -> CommunityAnalysisReport:
        classifications = tuple(cls._classify(item) for item in snapshot.comments)
        active = tuple(
            item for item in classifications
            if item.theme is not CommunityTheme.CONTENT_UNAVAILABLE
        )
        clusters: list[ThemeCluster] = []
        for theme in sorted({item.theme for item in active}, key=lambda item: item.value):
            members = tuple(item for item in active if item.theme is theme)
            fingerprints = tuple(sorted(item.classification_fingerprint for item in members))
            review_count = sum(item.requires_human_review for item in members)
            cluster_fingerprint = _sha256("|".join((
                str(request.request_id), theme.value, str(len(members)),
                str(review_count), ",".join(fingerprints),
            )))
            clusters.append(ThemeCluster(
                theme=theme, member_count=len(members),
                review_required_count=review_count,
                classification_fingerprints=fingerprints,
                cluster_fingerprint=cluster_fingerprint,
            ))
        deleted_count = len(classifications) - len(active)
        review_count = sum(item.requires_human_review for item in active)
        status = AnalysisStatus.EMPTY if not classifications else AnalysisStatus.CLASSIFIED
        report_values = (
            str(request.request_id), request.owner_user_id, str(request.publication_id),
            request.fingerprint, str(snapshot.ingestion_sync_id),
            snapshot.ingestion_target_fingerprint, snapshot.fingerprint,
            request.theme_taxonomy_version, request.safety_policy_version, status.value,
            str(len(classifications)), str(len(active)), str(deleted_count),
            str(review_count), str(len(clusters)), _timestamp(request.requested_at),
            _timestamp(now), "false",
        )
        return CommunityAnalysisReport(
            request_id=request.request_id, owner_user_id=request.owner_user_id,
            publication_id=request.publication_id, request_fingerprint=request.fingerprint,
            ingestion_sync_id=snapshot.ingestion_sync_id,
            ingestion_target_fingerprint=snapshot.ingestion_target_fingerprint,
            source_snapshot_fingerprint=snapshot.fingerprint,
            theme_taxonomy_version=request.theme_taxonomy_version,
            safety_policy_version=request.safety_policy_version, status=status,
            total_comment_count=len(classifications), analyzed_comment_count=len(active),
            deleted_comment_count=deleted_count, review_required_count=review_count,
            classifications=classifications, clusters=tuple(clusters),
            requested_at=request.requested_at, created_at=now,
            report_fingerprint=_sha256("|".join(report_values)),
        )

    @staticmethod
    def _classify(comment: CommunityCommentEvidence) -> CommentClassification:
        if comment.state is CommentState.DELETED:
            values = (
                str(comment.version_id), comment.comment_fingerprint,
                CommunityTheme.CONTENT_UNAVAILABLE.value, "theme.content_unavailable",
                SafetyCategory.CONTENT_UNAVAILABLE.value, SafetySeverity.NONE.value,
                "", "false",
            )
            return CommentClassification(
                comment_version_id=comment.version_id,
                remote_comment_id=comment.remote_comment_id,
                comment_fingerprint=comment.comment_fingerprint,
                theme=CommunityTheme.CONTENT_UNAVAILABLE,
                theme_rule_id="theme.content_unavailable",
                safety_category=SafetyCategory.CONTENT_UNAVAILABLE,
                safety_severity=SafetySeverity.NONE,
                safety_rule_ids=(), requires_human_review=False,
                classification_fingerprint=_sha256("|".join(values)),
            )

        assert comment.text is not None
        normalized = f" {_normalized(comment.text)} "
        theme, theme_rule = CommunityTheme.OTHER, "theme.other"
        for candidate, rule_id, phrases in _THEME_RULES:
            if any(phrase in normalized for phrase in phrases):
                theme, theme_rule = candidate, rule_id
                break
        if theme is CommunityTheme.OTHER and (
            "?" in comment.text
            or any(normalized.startswith(f" {word} ") for word in (
                "who", "what", "when", "where", "why", "how", "can", "does", "is",
            ))
        ):
            theme, theme_rule = CommunityTheme.QUESTION, "theme.question"

        matches: list[tuple[str, SafetyCategory, SafetySeverity]] = []
        for rule_id, category, severity, phrases in _SAFETY_RULES:
            if any(phrase in normalized for phrase in phrases):
                matches.append((rule_id, category, severity))
        if _EMAIL.search(comment.text) or _PHONE.search(comment.text):
            matches.append((
                "safety.personal_data", SafetyCategory.PERSONAL_DATA, SafetySeverity.HIGH,
            ))
        if matches:
            primary = max(matches, key=lambda item: (
                _SEVERITY_ORDER[item[2]], item[1].value, item[0],
            ))
            safety_category, severity = primary[1], primary[2]
            safety_rules = tuple(sorted({item[0] for item in matches}))
            review = True
        else:
            safety_category = SafetyCategory.NO_DETECTED_SIGNAL
            severity = SafetySeverity.NONE
            safety_rules = ()
            review = False
        values = (
            str(comment.version_id), comment.comment_fingerprint,
            theme.value, theme_rule, safety_category.value, severity.value,
            ",".join(safety_rules), str(review).lower(),
        )
        return CommentClassification(
            comment_version_id=comment.version_id,
            remote_comment_id=comment.remote_comment_id,
            comment_fingerprint=comment.comment_fingerprint,
            theme=theme, theme_rule_id=theme_rule,
            safety_category=safety_category, safety_severity=severity,
            safety_rule_ids=safety_rules, requires_human_review=review,
            classification_fingerprint=_sha256("|".join(values)),
        )
