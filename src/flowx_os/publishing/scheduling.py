"""Explicit publication approval and timezone-safe delivery scheduling."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Callable, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flowx_os.publishing.reconciliation import PublicationPlatform


_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SAFE_TIMEZONE = re.compile(r"^(?:UTC|[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)+)$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_BIDI = {"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI"}


class PublicationApprovalDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class PublicationDeliveryState(StrEnum):
    SCHEDULED = "SCHEDULED"
    DISPATCH_RESERVED = "DISPATCH_RESERVED"
    CANCELLED = "CANCELLED"


class PublicationSchedulingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) is None:
            raise ValueError("publication scheduling error code is invalid")
        self.code = code
        super().__init__(message)


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _safe_reason(value: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if (not 1 <= len(normalized) <= 500
            or any(unicodedata.category(char) == "Cc"
                   or unicodedata.bidirectional(char) in _BIDI for char in normalized)):
        raise ValueError("publication approval reason is invalid")
    return normalized


def resolve_local_schedule(
    local_value: datetime, timezone_name: str, fold: int | None,
) -> tuple[datetime, int]:
    """Convert one explicit civil time to UTC, rejecting gaps and implicit folds."""
    if not isinstance(local_value, datetime) or local_value.tzinfo is not None:
        raise ValueError("local publication schedule must be timezone-naive")
    name = timezone_name.strip() if isinstance(timezone_name, str) else ""
    if _SAFE_TIMEZONE.fullmatch(name) is None:
        raise ValueError("publication timezone is invalid")
    try:
        zone = ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("publication timezone is unavailable") from exc

    candidates: dict[int, tuple[datetime, int]] = {}
    for candidate_fold in (0, 1):
        localized = local_value.replace(tzinfo=zone, fold=candidate_fold)
        utc_value = localized.astimezone(timezone.utc)
        roundtrip = utc_value.astimezone(zone)
        if roundtrip.replace(tzinfo=None) == local_value and roundtrip.fold == candidate_fold:
            offset = localized.utcoffset()
            if offset is not None:
                candidates[candidate_fold] = (
                    utc_value, int(offset.total_seconds() // 60),
                )
    unique = {value for value in candidates.values()}
    if not unique:
        raise ValueError("local publication schedule does not exist in the timezone")
    if len(unique) > 1:
        if fold not in candidates:
            raise ValueError("ambiguous publication schedule requires an explicit fold")
        return candidates[fold]
    if fold not in {None, 0}:
        raise ValueError("publication schedule fold is invalid for an unambiguous time")
    return next(iter(unique))


def local_day_bounds(local_day: date, timezone_name: str) -> tuple[datetime, datetime]:
    def first_valid(value: datetime) -> datetime:
        first_minute = None
        for minute in range(2 * 24 * 60 + 1):
            candidate = value + timedelta(minutes=minute)
            try:
                resolved, _ = resolve_local_schedule(candidate, timezone_name, 0)
            except ValueError:
                continue
            first_minute = (candidate, resolved)
            break
        if first_minute is None:
            raise ValueError("publication local-day boundary is unavailable")
        candidate, resolved = first_minute
        if candidate == value:
            return resolved
        previous = candidate - timedelta(minutes=1)
        for second in range(1, 61):
            exact = previous + timedelta(seconds=second)
            try:
                return resolve_local_schedule(exact, timezone_name, 0)[0]
            except ValueError:
                continue
        return resolved

    start = first_valid(datetime.combine(local_day, datetime.min.time()))
    end = first_valid(datetime.combine(local_day + timedelta(days=1), datetime.min.time()))
    if end <= start:
        raise ValueError("publication local-day bounds are invalid")
    return start, end


@dataclass(frozen=True, slots=True)
class PublicationApprovalRequest:
    request_id: UUID
    approval_id: UUID
    publication_id: UUID
    owner_user_id: str
    approver_user_id: str
    decision: PublicationApprovalDecision
    valid_until: datetime
    reason: str

    def __post_init__(self) -> None:
        owner = self.owner_user_id.strip() if isinstance(self.owner_user_id, str) else ""
        approver = self.approver_user_id.strip() if isinstance(self.approver_user_id, str) else ""
        if (not all(isinstance(value, UUID) for value in (
                self.request_id, self.approval_id, self.publication_id))
                or _SAFE_OWNER.fullmatch(owner) is None
                or _SAFE_OWNER.fullmatch(approver) is None
                or owner != approver
                or not isinstance(self.decision, PublicationApprovalDecision)
                or not _aware(self.valid_until)):
            raise ValueError("publication approval identity is invalid")
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "approver_user_id", approver)
        object.__setattr__(self, "valid_until", self.valid_until.astimezone(timezone.utc))
        object.__setattr__(self, "reason", _safe_reason(self.reason))


@dataclass(frozen=True, slots=True)
class PublicationApprovalRecord:
    approval_id: UUID
    request_id: UUID
    publication_id: UUID
    owner_user_id: str
    decision: PublicationApprovalDecision
    valid_until: datetime
    reason: str
    platform: PublicationPlatform
    content_id: UUID
    channel_id: UUID
    asset_id: UUID
    artifact_version: int
    publication_state_version: int
    destination_fingerprint: str
    created_at: datetime

    def __post_init__(self) -> None:
        if (not all(isinstance(value, UUID) for value in (
                self.approval_id, self.request_id, self.publication_id,
                self.content_id, self.channel_id, self.asset_id))
                or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
                or not isinstance(self.decision, PublicationApprovalDecision)
                or not _aware(self.valid_until) or not _aware(self.created_at)
                or self.valid_until <= self.created_at
                or self.reason != _safe_reason(self.reason)
                or not isinstance(self.platform, PublicationPlatform)
                or type(self.artifact_version) is not int or self.artifact_version <= 0
                or type(self.publication_state_version) is not int
                or self.publication_state_version < 0
                or _HEX64.fullmatch(self.destination_fingerprint or "") is None):
            raise ValueError("publication approval record is invalid")


@dataclass(frozen=True, slots=True)
class PublicationScheduleRequest:
    request_id: UUID
    schedule_id: UUID
    publication_id: UUID
    approval_id: UUID
    owner_user_id: str
    local_scheduled_at: datetime
    timezone_name: str
    fold: int | None = None

    def __post_init__(self) -> None:
        owner = self.owner_user_id.strip() if isinstance(self.owner_user_id, str) else ""
        if (not all(isinstance(value, UUID) for value in (
                self.request_id, self.schedule_id, self.publication_id, self.approval_id))
                or _SAFE_OWNER.fullmatch(owner) is None
                or self.fold not in {None, 0, 1}):
            raise ValueError("publication schedule identity is invalid")
        name = self.timezone_name.strip() if isinstance(self.timezone_name, str) else ""
        resolve_local_schedule(self.local_scheduled_at, name, self.fold)
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "timezone_name", name)

    @property
    def scheduled_at_utc(self) -> datetime:
        return resolve_local_schedule(
            self.local_scheduled_at, self.timezone_name, self.fold,
        )[0]

    @property
    def utc_offset_minutes(self) -> int:
        return resolve_local_schedule(
            self.local_scheduled_at, self.timezone_name, self.fold,
        )[1]

    @property
    def day_bounds_utc(self) -> tuple[datetime, datetime]:
        return local_day_bounds(self.local_scheduled_at.date(), self.timezone_name)


@dataclass(frozen=True, slots=True)
class PublicationScheduleRecord:
    schedule_id: UUID
    request_id: UUID
    publication_id: UUID
    approval_id: UUID
    owner_user_id: str
    platform: PublicationPlatform
    channel_id: UUID
    content_id: UUID
    asset_id: UUID
    artifact_version: int
    local_scheduled_at: datetime
    timezone_name: str
    fold: int | None
    utc_offset_minutes: int
    scheduled_at_utc: datetime
    state: PublicationDeliveryState
    outbox_job_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        if (not all(isinstance(value, UUID) for value in (
                self.schedule_id, self.request_id, self.publication_id,
                self.approval_id, self.channel_id, self.content_id,
                self.asset_id, self.outbox_job_id))
                or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
                or not isinstance(self.platform, PublicationPlatform)
                or type(self.artifact_version) is not int or self.artifact_version <= 0
                or not isinstance(self.state, PublicationDeliveryState)
                or not _aware(self.scheduled_at_utc) or not _aware(self.created_at)):
            raise ValueError("publication schedule record is invalid")
        expected_utc, expected_offset = resolve_local_schedule(
            self.local_scheduled_at, self.timezone_name, self.fold,
        )
        if (self.scheduled_at_utc != expected_utc
                or self.utc_offset_minutes != expected_offset):
            raise ValueError("publication schedule record time is invalid")


@dataclass(frozen=True, slots=True)
class PublicationSchedulePolicy:
    enabled: bool = False
    minimum_lead_seconds: int = 300
    maximum_horizon_days: int = 90
    maximum_per_local_day: int = 3
    minimum_gap_seconds: int = 14_400
    outbox_max_attempts: int = 5

    def __post_init__(self) -> None:
        if (type(self.enabled) is not bool
                or type(self.minimum_lead_seconds) is not int
                or not 60 <= self.minimum_lead_seconds <= 86_400
                or type(self.maximum_horizon_days) is not int
                or not 1 <= self.maximum_horizon_days <= 365
                or type(self.maximum_per_local_day) is not int
                or not 1 <= self.maximum_per_local_day <= 100
                or type(self.minimum_gap_seconds) is not int
                or not 0 <= self.minimum_gap_seconds <= 86_400
                or type(self.outbox_max_attempts) is not int
                or not 1 <= self.outbox_max_attempts <= 20):
            raise ValueError("publication schedule policy is invalid")


class PublicationScheduleStore(Protocol):
    async def get_approval(
        self, request: PublicationApprovalRequest,
    ) -> PublicationApprovalRecord | None: ...

    async def record_approval(
        self, request: PublicationApprovalRequest,
    ) -> PublicationApprovalRecord: ...

    async def get_schedule(
        self, request: PublicationScheduleRequest,
    ) -> PublicationScheduleRecord | None: ...

    async def schedule(
        self, request: PublicationScheduleRequest, *, now: datetime,
        policy: PublicationSchedulePolicy,
    ) -> PublicationScheduleRecord: ...


class PublicationSchedulingService:
    def __init__(
        self, *, store: PublicationScheduleStore,
        policy: PublicationSchedulePolicy | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._policy = policy or PublicationSchedulePolicy()
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def approve(
        self, request: PublicationApprovalRequest,
    ) -> PublicationApprovalRecord:
        if not isinstance(request, PublicationApprovalRequest):
            raise ValueError("publication approval request is required")
        existing = await self._store.get_approval(request)
        if existing is not None:
            return existing
        now = self._now()
        if not _aware(now):
            raise PublicationSchedulingError("CLOCK_INVALID", "scheduler clock is invalid")
        if request.valid_until <= now.astimezone(timezone.utc):
            raise PublicationSchedulingError("APPROVAL_EXPIRED", "publication approval is expired")
        return await self._store.record_approval(request)

    async def schedule(
        self, request: PublicationScheduleRequest,
    ) -> PublicationScheduleRecord:
        if not isinstance(request, PublicationScheduleRequest):
            raise ValueError("publication schedule request is required")
        existing = await self._store.get_schedule(request)
        if existing is not None:
            return existing
        if not self._policy.enabled:
            raise PublicationSchedulingError("SCHEDULING_DISABLED", "publication scheduling is disabled")
        now = self._now()
        if not _aware(now):
            raise PublicationSchedulingError("CLOCK_INVALID", "scheduler clock is invalid")
        now_utc = now.astimezone(timezone.utc)
        scheduled = request.scheduled_at_utc
        if scheduled < now_utc + timedelta(seconds=self._policy.minimum_lead_seconds):
            raise PublicationSchedulingError("SCHEDULE_TOO_SOON", "publication schedule lead time is too short")
        if scheduled > now_utc + timedelta(days=self._policy.maximum_horizon_days):
            raise PublicationSchedulingError("SCHEDULE_TOO_DISTANT", "publication schedule exceeds the horizon")
        return await self._store.schedule(
            request, now=now_utc, policy=self._policy,
        )
