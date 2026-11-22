"""Typed, deterministic human decisions over exact QA evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import re
import unicodedata
from uuid import UUID

from flowx_os.domain.content_state import ContentStatus


_SAFE_REVIEWER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SECRET_ASSIGNMENT = re.compile(
    r"(?:password|secret|token|credential|api[_-]?key|authorization|cookie)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_BIDI_CONTROLS = {"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI"}


class HumanReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"


class HumanReviewRevisionTarget(StrEnum):
    SCRIPT_READY = "SCRIPT_READY"
    STORYBOARD_READY = "STORYBOARD_READY"


@dataclass(frozen=True, slots=True)
class HumanReviewRequest:
    request_id: UUID
    content_id: UUID
    asset_id: UUID
    qa_report_id: UUID
    reviewer_user_id: str
    decision: HumanReviewDecision
    reason: str
    revision_target: HumanReviewRevisionTarget | None = None

    def __post_init__(self) -> None:
        reason = self.reason.strip() if isinstance(self.reason, str) else ""
        reviewer = self.reviewer_user_id.strip() if isinstance(self.reviewer_user_id, str) else ""
        if (not all(isinstance(value, UUID) for value in (
                self.request_id, self.content_id, self.asset_id, self.qa_report_id))
                or not _SAFE_REVIEWER.fullmatch(reviewer)
                or not isinstance(self.decision, HumanReviewDecision)
                or not reason or len(reason) > 2000
                or _SECRET_ASSIGNMENT.search(reason)
                or any(unicodedata.category(character) == "Cc"
                       or unicodedata.bidirectional(character) in _BIDI_CONTROLS
                       for character in reason)
                or (self.decision == HumanReviewDecision.CHANGES_REQUIRED)
                   != isinstance(self.revision_target, HumanReviewRevisionTarget)):
            raise ValueError("human review request is invalid")
        object.__setattr__(self, "reviewer_user_id", reviewer)
        object.__setattr__(self, "reason", reason)

    @property
    def fingerprint(self) -> str:
        fields = (
            str(self.request_id), str(self.content_id), str(self.asset_id),
            str(self.qa_report_id), self.reviewer_user_id, self.decision.value,
            "FINAL_VIDEO", self.revision_target.value if self.revision_target else "",
            self.reason,
        )
        return hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()

    @property
    def next_status(self) -> ContentStatus:
        if self.decision == HumanReviewDecision.APPROVE:
            return ContentStatus.READY
        if self.decision == HumanReviewDecision.REJECT:
            return ContentStatus.ARCHIVED
        assert self.revision_target is not None
        return ContentStatus(self.revision_target.value)


@dataclass(frozen=True, slots=True)
class HumanReviewRecord:
    decision_id: UUID
    request: HumanReviewRequest
    next_status: ContentStatus
    created_at: datetime
