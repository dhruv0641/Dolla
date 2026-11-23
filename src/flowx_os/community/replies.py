"""Inert deterministic reply drafts and mandatory safety escalation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from flowx_os.community.analysis import (
    CommunityTheme,
    SafetyCategory,
    SafetySeverity,
)
from flowx_os.community.comments import CommentState


REPLY_POLICY_VERSION = "community-reply-v1"
_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SAFE_REMOTE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_SAFE_VERSION = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")
_SAFE_REASON = re.compile(r"^[a-z][a-z0-9._-]{0,79}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_DRAFTS = {
    CommunityTheme.SUPPORT_REQUEST:
        "Thanks for letting us know. A team member will review the issue before responding with next steps.",
    CommunityTheme.PRICING:
        "Thanks for asking. A team member will verify the current pricing details before responding.",
    CommunityTheme.FEATURE_REQUEST:
        "Thanks for the suggestion. We have recorded it for human review and consideration.",
    CommunityTheme.CONTENT_REQUEST:
        "Thanks for the content suggestion. A team member will review it for a future plan.",
    CommunityTheme.QUESTION:
        "Thanks for your question. A team member will review it and provide an accurate response.",
    CommunityTheme.PRAISE:
        "Thank you for the kind feedback. We appreciate you taking the time to share it.",
    CommunityTheme.COMPLAINT:
        "Thanks for sharing this feedback. A team member will review the concern before responding.",
    CommunityTheme.OTHER:
        "Thanks for your comment. A team member will review it before any response is posted.",
}
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


def _aware_utc(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() == timedelta(0)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ReplyDraftError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReplyDisposition(StrEnum):
    DRAFT_REQUIRES_HUMAN_APPROVAL = "DRAFT_REQUIRES_HUMAN_APPROVAL"
    ESCALATED_NO_DRAFT = "ESCALATED_NO_DRAFT"
    CONTENT_UNAVAILABLE_NO_DRAFT = "CONTENT_UNAVAILABLE_NO_DRAFT"


class EscalationPriority(StrEnum):
    NONE = "NONE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    URGENT = "URGENT"


@dataclass(frozen=True, slots=True)
class ReplyDraftRequest:
    request_id: UUID
    owner_user_id: str
    publication_id: UUID
    analysis_request_id: UUID
    comment_version_id: UUID
    classification_fingerprint: str
    requested_at: datetime
    policy_version: str = REPLY_POLICY_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.publication_id, UUID)
            or not isinstance(self.analysis_request_id, UUID)
            or not isinstance(self.comment_version_id, UUID)
            or _HEX64.fullmatch(self.classification_fingerprint or "") is None
            or not _aware_utc(self.requested_at)
            or _SAFE_VERSION.fullmatch(self.policy_version or "") is None
        ):
            raise ValueError("reply draft request is invalid")

    @property
    def fingerprint(self) -> str:
        return _sha256("|".join((
            str(self.request_id), self.owner_user_id, str(self.publication_id),
            str(self.analysis_request_id), str(self.comment_version_id),
            self.classification_fingerprint, self.policy_version,
            _timestamp(self.requested_at),
        )))


@dataclass(frozen=True, slots=True)
class ReplyDraftTarget:
    owner_user_id: str
    publication_id: UUID
    analysis_request_id: UUID
    analysis_report_fingerprint: str
    comment_version_id: UUID
    remote_comment_id: str
    comment_fingerprint: str
    comment_state: CommentState
    theme: CommunityTheme
    theme_rule_id: str
    safety_category: SafetyCategory
    safety_severity: SafetySeverity
    safety_rule_ids: tuple[str, ...]
    requires_human_review: bool
    classification_fingerprint: str

    def __post_init__(self) -> None:
        unavailable = self.comment_state is CommentState.DELETED
        no_signal = self.safety_category is SafetyCategory.NO_DETECTED_SIGNAL
        expected_classification = ""
        if (
            isinstance(self.comment_version_id, UUID)
            and _HEX64.fullmatch(self.comment_fingerprint or "") is not None
            and isinstance(self.theme, CommunityTheme)
            and isinstance(self.safety_category, SafetyCategory)
            and isinstance(self.safety_severity, SafetySeverity)
            and isinstance(self.safety_rule_ids, tuple)
            and type(self.requires_human_review) is bool
        ):
            expected_classification = _sha256("|".join((
                str(self.comment_version_id), self.comment_fingerprint,
                self.theme.value, self.theme_rule_id, self.safety_category.value,
                self.safety_severity.value, ",".join(self.safety_rule_ids),
                str(self.requires_human_review).lower(),
            )))
        if (
            _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.publication_id, UUID)
            or not isinstance(self.analysis_request_id, UUID)
            or _HEX64.fullmatch(self.analysis_report_fingerprint or "") is None
            or not isinstance(self.comment_version_id, UUID)
            or _SAFE_REMOTE_ID.fullmatch(self.remote_comment_id or "") is None
            or _HEX64.fullmatch(self.comment_fingerprint or "") is None
            or not isinstance(self.comment_state, CommentState)
            or not isinstance(self.theme, CommunityTheme)
            or _SAFE_REASON.fullmatch(self.theme_rule_id or "") is None
            or self.theme_rule_id != _THEME_RULE_IDS.get(self.theme)
            or not isinstance(self.safety_category, SafetyCategory)
            or not isinstance(self.safety_severity, SafetySeverity)
            or not isinstance(self.safety_rule_ids, tuple)
            or tuple(sorted(set(self.safety_rule_ids))) != self.safety_rule_ids
            or type(self.requires_human_review) is not bool
            or _HEX64.fullmatch(self.classification_fingerprint or "") is None
            or self.classification_fingerprint != expected_classification
            or unavailable is not (self.theme is CommunityTheme.CONTENT_UNAVAILABLE)
            or unavailable is not (
                self.safety_category is SafetyCategory.CONTENT_UNAVAILABLE
            )
            or (unavailable and (
                self.safety_severity is not SafetySeverity.NONE
                or self.safety_rule_ids
                or self.requires_human_review
            ))
            or (not unavailable and (
                self.theme is CommunityTheme.CONTENT_UNAVAILABLE
                or self.safety_category is SafetyCategory.CONTENT_UNAVAILABLE
            ))
            or (not unavailable and no_signal and (
                self.safety_severity is not SafetySeverity.NONE
                or self.safety_rule_ids
                or self.requires_human_review
            ))
            or (not unavailable and not no_signal and (
                self.safety_severity is SafetySeverity.NONE
                or not self.safety_rule_ids
                or not self.requires_human_review
            ))
        ):
            raise ValueError("reply draft target is invalid")

    @property
    def fingerprint(self) -> str:
        return _sha256("|".join((
            self.owner_user_id, str(self.publication_id), str(self.analysis_request_id),
            self.analysis_report_fingerprint, str(self.comment_version_id),
            self.remote_comment_id, self.comment_fingerprint, self.comment_state.value,
            self.theme.value, self.theme_rule_id,
            self.safety_category.value, self.safety_severity.value,
            ",".join(self.safety_rule_ids), str(self.requires_human_review).lower(),
            self.classification_fingerprint,
        )))


@dataclass(frozen=True, slots=True)
class ReplyDraftRecord:
    request_id: UUID
    owner_user_id: str
    publication_id: UUID
    analysis_request_id: UUID
    comment_version_id: UUID
    request_fingerprint: str
    target_fingerprint: str
    analysis_report_fingerprint: str
    classification_fingerprint: str
    policy_version: str
    disposition: ReplyDisposition
    escalation_priority: EscalationPriority
    escalation_reasons: tuple[str, ...]
    draft_text: str | None
    human_approval_required: bool
    outbound_action_authorized: bool
    created_at: datetime
    record_fingerprint: str

    def __post_init__(self) -> None:
        draft_disposition = self.disposition is ReplyDisposition.DRAFT_REQUIRES_HUMAN_APPROVAL
        expected = ""
        if isinstance(self.request_id, UUID) and _aware_utc(self.created_at):
            expected = _sha256("|".join((
                str(self.request_id), self.owner_user_id, str(self.publication_id),
                str(self.analysis_request_id), str(self.comment_version_id),
                self.request_fingerprint, self.target_fingerprint,
                self.analysis_report_fingerprint, self.classification_fingerprint,
                self.policy_version, self.disposition.value,
                self.escalation_priority.value, ",".join(self.escalation_reasons),
                self.draft_text or "", str(self.human_approval_required).lower(),
                str(self.outbound_action_authorized).lower(), _timestamp(self.created_at),
            )))
        if (
            not isinstance(self.request_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.publication_id, UUID)
            or not isinstance(self.analysis_request_id, UUID)
            or not isinstance(self.comment_version_id, UUID)
            or any(_HEX64.fullmatch(value or "") is None for value in (
                self.request_fingerprint, self.target_fingerprint,
                self.analysis_report_fingerprint, self.classification_fingerprint,
                self.record_fingerprint,
            ))
            or _SAFE_VERSION.fullmatch(self.policy_version or "") is None
            or not isinstance(self.disposition, ReplyDisposition)
            or not isinstance(self.escalation_priority, EscalationPriority)
            or not isinstance(self.escalation_reasons, tuple)
            or tuple(sorted(set(self.escalation_reasons))) != self.escalation_reasons
            or any(_SAFE_REASON.fullmatch(value or "") is None for value in self.escalation_reasons)
            or type(self.human_approval_required) is not bool
            or not self.human_approval_required
            or type(self.outbound_action_authorized) is not bool
            or self.outbound_action_authorized
            or not _aware_utc(self.created_at)
            or (draft_disposition and (
                not isinstance(self.draft_text, str)
                or not 1 <= len(self.draft_text) <= 500
                or self.draft_text != self.draft_text.strip()
                or self.escalation_priority is not EscalationPriority.NONE
                or self.escalation_reasons
            ))
            or (not draft_disposition and (
                self.draft_text is not None
                or self.escalation_priority is EscalationPriority.NONE
                or not self.escalation_reasons
            ))
            or self.record_fingerprint != expected
        ):
            raise ValueError("reply draft record is invalid")


@dataclass(frozen=True, slots=True)
class ReplyDraftPolicy:
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("reply draft policy is invalid")


class ReplyDraftStore(Protocol):
    async def get_existing(self, request: ReplyDraftRequest) -> ReplyDraftRecord | None: ...
    async def load_target(self, request: ReplyDraftRequest) -> ReplyDraftTarget: ...
    async def persist(
        self, request: ReplyDraftRequest, target: ReplyDraftTarget,
        record: ReplyDraftRecord,
    ) -> ReplyDraftRecord: ...


class ReplyDraftService:
    def __init__(self, store: ReplyDraftStore, policy: ReplyDraftPolicy | None = None) -> None:
        self._store = store
        self._policy = policy or ReplyDraftPolicy()

    async def draft(self, request: ReplyDraftRequest, *, now: datetime) -> ReplyDraftRecord:
        if not isinstance(request, ReplyDraftRequest) or not _aware_utc(now):
            raise ValueError("reply draft invocation is invalid")
        if now < request.requested_at:
            raise ReplyDraftError("REQUEST_FROM_FUTURE", "reply draft request is in the future")
        if not self._policy.enabled:
            raise ReplyDraftError("DRAFTING_DISABLED", "reply drafting is disabled by policy")
        if request.policy_version != REPLY_POLICY_VERSION:
            raise ReplyDraftError("POLICY_VERSION_UNAVAILABLE", "reply policy is unavailable")
        existing = await self._store.get_existing(request)
        if existing is not None:
            self._require_identity(existing, request=request)
            existing_target = await self._store.load_target(request)
            if existing != self._build(request=request, target=existing_target):
                raise ReplyDraftError(
                    "STORED_RECORD_EVIDENCE_MISMATCH",
                    "stored reply draft differs from current exact evidence",
                )
            return existing
        target = await self._store.load_target(request)
        if (
            target.owner_user_id != request.owner_user_id
            or target.publication_id != request.publication_id
            or target.analysis_request_id != request.analysis_request_id
            or target.comment_version_id != request.comment_version_id
            or target.classification_fingerprint != request.classification_fingerprint
        ):
            raise ReplyDraftError("EVIDENCE_IDENTITY_MISMATCH", "reply evidence identity changed")
        record = self._build(request=request, target=target)
        stored = await self._store.persist(request, target, record)
        self._require_identity(stored, request=request)
        if stored != record:
            raise ReplyDraftError("PERSISTED_RECORD_MISMATCH", "stored reply draft differs from exact result")
        return stored

    @staticmethod
    def _build(*, request: ReplyDraftRequest, target: ReplyDraftTarget) -> ReplyDraftRecord:
        if target.comment_state is CommentState.DELETED or target.theme is CommunityTheme.CONTENT_UNAVAILABLE:
            disposition = ReplyDisposition.CONTENT_UNAVAILABLE_NO_DRAFT
            priority = EscalationPriority.HUMAN_REVIEW
            reasons = ("content-unavailable",)
            draft_text = None
        elif target.requires_human_review or target.safety_category is not SafetyCategory.NO_DETECTED_SIGNAL:
            disposition = ReplyDisposition.ESCALATED_NO_DRAFT
            priority = (
                EscalationPriority.URGENT
                if target.safety_severity is SafetySeverity.CRITICAL
                else EscalationPriority.HUMAN_REVIEW
            )
            reasons = tuple(sorted((
                f"safety-{target.safety_category.value.lower().replace('_', '-')}",
                *target.safety_rule_ids,
            )))
            draft_text = None
        else:
            disposition = ReplyDisposition.DRAFT_REQUIRES_HUMAN_APPROVAL
            priority = EscalationPriority.NONE
            reasons = ()
            draft_text = _DRAFTS[target.theme]
        values = (
            str(request.request_id), request.owner_user_id, str(request.publication_id),
            str(request.analysis_request_id), str(request.comment_version_id),
            request.fingerprint, target.fingerprint, target.analysis_report_fingerprint,
            target.classification_fingerprint, request.policy_version,
            disposition.value, priority.value, ",".join(reasons), draft_text or "",
            "true", "false", _timestamp(request.requested_at),
        )
        return ReplyDraftRecord(
            request_id=request.request_id, owner_user_id=request.owner_user_id,
            publication_id=request.publication_id,
            analysis_request_id=request.analysis_request_id,
            comment_version_id=request.comment_version_id,
            request_fingerprint=request.fingerprint, target_fingerprint=target.fingerprint,
            analysis_report_fingerprint=target.analysis_report_fingerprint,
            classification_fingerprint=target.classification_fingerprint,
            policy_version=request.policy_version, disposition=disposition,
            escalation_priority=priority, escalation_reasons=reasons,
            draft_text=draft_text, human_approval_required=True,
            outbound_action_authorized=False, created_at=request.requested_at,
            record_fingerprint=_sha256("|".join(values)),
        )

    @staticmethod
    def _require_identity(
        record: ReplyDraftRecord, *, request: ReplyDraftRequest,
    ) -> ReplyDraftRecord:
        if (
            not isinstance(record, ReplyDraftRecord)
            or record.request_id != request.request_id
            or record.owner_user_id != request.owner_user_id
            or record.publication_id != request.publication_id
            or record.analysis_request_id != request.analysis_request_id
            or record.comment_version_id != request.comment_version_id
            or record.request_fingerprint != request.fingerprint
            or record.classification_fingerprint != request.classification_fingerprint
            or record.policy_version != request.policy_version
            or record.created_at != request.requested_at
            or record.outbound_action_authorized
        ):
            raise ReplyDraftError("STORED_RECORD_IDENTITY_MISMATCH", "stored reply draft identity is invalid")
        return record
