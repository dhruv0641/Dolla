"""Read-only, cross-platform publication state reconciliation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID


_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SAFE_REMOTE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_SAFE_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SECRET_REF = re.compile(r"^secretref://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_LOCAL_STATUSES = {
    "DRAFT", "PUBLISH_REQUESTED", "UPLOAD_STARTED", "PROCESSING",
    "VERIFY_PENDING", "PUBLISHED", "FAILED", "CANCELLED",
}


class PublicationPlatform(StrEnum):
    YOUTUBE = "YOUTUBE"
    INSTAGRAM = "INSTAGRAM"
    FACEBOOK = "FACEBOOK"


class RemotePublicationState(StrEnum):
    ABSENT = "ABSENT"
    PROCESSING = "PROCESSING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    DELETED = "DELETED"
    RESTRICTED = "RESTRICTED"
    UNKNOWN = "UNKNOWN"


class ReconciliationVerdict(StrEnum):
    IN_SYNC = "IN_SYNC"
    REMOTE_AHEAD = "REMOTE_AHEAD"
    LOCAL_AHEAD = "LOCAL_AHEAD"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


class PlatformReconciliationError(RuntimeError):
    """Stable, operator-safe reconciliation error."""

    def __init__(self, code: str, message: str) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) is None:
            raise ValueError("reconciliation error code is invalid")
        self.code = code
        super().__init__(message)


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _canonical_url(platform: PublicationPlatform, remote_id: str, value: str | None) -> bool:
    if value is None:
        return True
    if platform is PublicationPlatform.YOUTUBE:
        return value == f"https://www.youtube.com/watch?v={remote_id}"
    if platform is PublicationPlatform.FACEBOOK:
        return value == f"https://www.facebook.com/reel/{remote_id}"
    return re.fullmatch(r"https://www\.instagram\.com/reel/[A-Za-z0-9_-]+/?", value) is not None


@dataclass(frozen=True, slots=True)
class PlatformReconciliationRequest:
    request_id: UUID
    publication_id: UUID
    owner_user_id: str

    def __post_init__(self) -> None:
        owner = self.owner_user_id.strip() if isinstance(self.owner_user_id, str) else ""
        if (not isinstance(self.request_id, UUID) or not isinstance(self.publication_id, UUID)
                or _SAFE_OWNER.fullmatch(owner) is None):
            raise ValueError("reconciliation request identity is invalid")
        object.__setattr__(self, "owner_user_id", owner)


@dataclass(frozen=True, slots=True)
class PublicationReconciliationTarget:
    publication_id: UUID
    owner_user_id: str
    platform: PublicationPlatform
    local_status: str
    publication_state_version: int
    request_fingerprint: str
    channel_id: UUID
    destination_id: str
    credentials_ref: str
    destination_fingerprint: str
    remote_object_id: str | None
    remote_url: str | None

    def __post_init__(self) -> None:
        expected_destination = hashlib.sha256(
            f"{self.destination_id}|{self.credentials_ref}".encode("utf-8")
        ).hexdigest()
        if (not isinstance(self.publication_id, UUID)
                or not isinstance(self.channel_id, UUID)
                or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
                or not isinstance(self.platform, PublicationPlatform)
                or self.local_status not in _LOCAL_STATUSES
                or type(self.publication_state_version) is not int
                or not 0 <= self.publication_state_version <= 9_223_372_036_854_775_807
                or _HEX64.fullmatch(self.request_fingerprint or "") is None
                or _SAFE_REMOTE_ID.fullmatch(self.destination_id or "") is None
                or _SECRET_REF.fullmatch(self.credentials_ref or "") is None
                or self.destination_fingerprint != expected_destination
                or (self.remote_object_id is not None
                    and _SAFE_REMOTE_ID.fullmatch(self.remote_object_id) is None)
                or (self.remote_url is not None and (
                    self.remote_object_id is None
                    or not _canonical_url(self.platform, self.remote_object_id, self.remote_url)
                ))):
            raise ValueError("reconciliation target is invalid")

    @property
    def fingerprint(self) -> str:
        values = (
            str(self.publication_id), self.owner_user_id, self.platform.value,
            self.local_status, str(self.publication_state_version),
            self.request_fingerprint, str(self.channel_id), self.destination_id,
            self.destination_fingerprint, self.remote_object_id or "", self.remote_url or "",
        )
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PlatformPublicationObservation:
    request_id: UUID
    publication_id: UUID
    platform: PublicationPlatform
    destination_id: str
    remote_object_id: str
    state: RemotePublicationState
    observed_at: datetime
    evidence_id: str
    remote_url: str | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.request_id, UUID)
                or not isinstance(self.publication_id, UUID)
                or not isinstance(self.platform, PublicationPlatform)
                or _SAFE_REMOTE_ID.fullmatch(self.destination_id or "") is None
                or _SAFE_REMOTE_ID.fullmatch(self.remote_object_id or "") is None
                or not isinstance(self.state, RemotePublicationState)
                or not _aware(self.observed_at)
                or _SAFE_EVIDENCE_ID.fullmatch(self.evidence_id or "") is None
                or not _canonical_url(self.platform, self.remote_object_id, self.remote_url)
                or (self.state is RemotePublicationState.PUBLISHED and self.remote_url is None)):
            raise ValueError("platform publication observation is invalid")

    @property
    def fingerprint(self) -> str:
        values = (
            str(self.request_id), str(self.publication_id), self.platform.value,
            self.destination_id, self.remote_object_id, self.state.value,
            self.observed_at.isoformat(), self.evidence_id, self.remote_url or "",
        )
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PublicationReconciliationRecord:
    request_id: UUID
    publication_id: UUID
    platform: PublicationPlatform
    local_status: str
    remote_state: RemotePublicationState
    verdict: ReconciliationVerdict
    requires_human_review: bool
    target_fingerprint: str
    observation_fingerprint: str
    destination_id: str
    remote_object_id: str
    remote_url: str | None
    evidence_id: str
    observed_at: datetime
    created_at: datetime

    def __post_init__(self) -> None:
        if (not isinstance(self.request_id, UUID) or not isinstance(self.publication_id, UUID)
                or not isinstance(self.platform, PublicationPlatform)
                or self.local_status not in _LOCAL_STATUSES
                or not isinstance(self.remote_state, RemotePublicationState)
                or not isinstance(self.verdict, ReconciliationVerdict)
                or type(self.requires_human_review) is not bool
                or _HEX64.fullmatch(self.target_fingerprint or "") is None
                or _HEX64.fullmatch(self.observation_fingerprint or "") is None
                or _SAFE_REMOTE_ID.fullmatch(self.destination_id or "") is None
                or _SAFE_REMOTE_ID.fullmatch(self.remote_object_id or "") is None
                or not _canonical_url(self.platform, self.remote_object_id, self.remote_url)
                or _SAFE_EVIDENCE_ID.fullmatch(self.evidence_id or "") is None
                or not _aware(self.observed_at) or not _aware(self.created_at)
                or self.requires_human_review is not (
                    self.verdict in {
                        ReconciliationVerdict.REMOTE_AHEAD,
                        ReconciliationVerdict.LOCAL_AHEAD,
                        ReconciliationVerdict.CONFLICT,
                        ReconciliationVerdict.UNKNOWN,
                    }
                )):
            raise ValueError("publication reconciliation record is invalid")


@dataclass(frozen=True, slots=True)
class PlatformReconciliationPolicy:
    enabled: bool = False
    maximum_observation_age_seconds: int = 300
    maximum_clock_skew_seconds: int = 30

    def __post_init__(self) -> None:
        if (type(self.enabled) is not bool
                or type(self.maximum_observation_age_seconds) is not int
                or not 30 <= self.maximum_observation_age_seconds <= 3_600
                or type(self.maximum_clock_skew_seconds) is not int
                or not 0 <= self.maximum_clock_skew_seconds <= 120):
            raise ValueError("platform reconciliation policy is invalid")


class PlatformPublicationObserver(Protocol):
    async def observe(
        self, *, request_id: UUID, publication_id: UUID,
        platform: PublicationPlatform, credentials_ref: str,
        destination_id: str, remote_object_id: str,
    ) -> PlatformPublicationObservation: ...


class PublicationReconciliationStore(Protocol):
    async def get_existing(
        self, request: PlatformReconciliationRequest,
    ) -> PublicationReconciliationRecord | None: ...

    async def load_target(
        self, request: PlatformReconciliationRequest,
    ) -> PublicationReconciliationTarget: ...

    async def record(
        self, *, request: PlatformReconciliationRequest,
        target: PublicationReconciliationTarget,
        observation: PlatformPublicationObservation,
        verdict: ReconciliationVerdict,
    ) -> PublicationReconciliationRecord: ...


class PlatformPublicationReconciler:
    """Compare an immutable local snapshot with one independent remote read."""

    def __init__(
        self, *, store: PublicationReconciliationStore,
        observer: PlatformPublicationObserver,
        policy: PlatformReconciliationPolicy | None = None,
    ) -> None:
        self._store = store
        self._observer = observer
        self._policy = policy or PlatformReconciliationPolicy()

    async def reconcile(
        self, request: PlatformReconciliationRequest,
    ) -> PublicationReconciliationRecord:
        if not isinstance(request, PlatformReconciliationRequest):
            raise ValueError("platform reconciliation request is required")
        existing = await self._store.get_existing(request)
        if existing is not None:
            return existing
        if not self._policy.enabled:
            raise PlatformReconciliationError(
                "CAPABILITY_DISABLED", "platform reconciliation is disabled",
            )
        target = await self._store.load_target(request)
        if target.remote_object_id is None:
            raise PlatformReconciliationError(
                "REMOTE_ID_UNAVAILABLE", "exact remote publication identity is unavailable",
            )
        try:
            observation = await self._observer.observe(
                request_id=request.request_id,
                publication_id=target.publication_id,
                platform=target.platform,
                credentials_ref=target.credentials_ref,
                destination_id=target.destination_id,
                remote_object_id=target.remote_object_id,
            )
        except PlatformReconciliationError:
            raise
        except Exception as exc:
            raise PlatformReconciliationError(
                "OBSERVATION_UNAVAILABLE", "platform observation is unavailable",
            ) from exc
        self._validate_observation(request, target, observation)
        verdict = self.classify(target.local_status, observation.state)
        return await self._store.record(
            request=request, target=target, observation=observation, verdict=verdict,
        )

    def _validate_observation(
        self, request: PlatformReconciliationRequest,
        target: PublicationReconciliationTarget,
        observation: PlatformPublicationObservation,
    ) -> None:
        if not isinstance(observation, PlatformPublicationObservation):
            raise PlatformReconciliationError(
                "OBSERVATION_INVALID", "platform observation is invalid",
            )
        now = datetime.now(timezone.utc)
        if (observation.request_id != request.request_id
                or observation.publication_id != target.publication_id
                or observation.platform is not target.platform
                or observation.destination_id != target.destination_id
                or observation.remote_object_id != target.remote_object_id
                or (target.remote_url is not None
                    and observation.remote_url is not None
                    and observation.remote_url != target.remote_url)):
            raise PlatformReconciliationError(
                "OBSERVATION_IDENTITY_MISMATCH", "platform observation identity is invalid",
            )
        if (observation.observed_at > now + timedelta(
                seconds=self._policy.maximum_clock_skew_seconds,
            ) or now - observation.observed_at > timedelta(
                seconds=self._policy.maximum_observation_age_seconds,
            )):
            raise PlatformReconciliationError(
                "OBSERVATION_STALE", "platform observation is outside the allowed time window",
            )

    @staticmethod
    def classify(local_status: str, remote_state: RemotePublicationState) -> ReconciliationVerdict:
        if local_status not in _LOCAL_STATUSES or not isinstance(remote_state, RemotePublicationState):
            raise ValueError("publication states are invalid")
        if remote_state is RemotePublicationState.UNKNOWN:
            return ReconciliationVerdict.UNKNOWN
        if local_status == "PUBLISHED":
            if remote_state is RemotePublicationState.PUBLISHED:
                return ReconciliationVerdict.IN_SYNC
            if remote_state is RemotePublicationState.PROCESSING:
                return ReconciliationVerdict.LOCAL_AHEAD
            return ReconciliationVerdict.CONFLICT
        if local_status == "CANCELLED":
            return (
                ReconciliationVerdict.IN_SYNC
                if remote_state in {RemotePublicationState.ABSENT, RemotePublicationState.DELETED}
                else ReconciliationVerdict.CONFLICT
            )
        if local_status == "FAILED":
            return (
                ReconciliationVerdict.IN_SYNC
                if remote_state is RemotePublicationState.FAILED
                else ReconciliationVerdict.CONFLICT
            )
        if remote_state is RemotePublicationState.PUBLISHED:
            return ReconciliationVerdict.REMOTE_AHEAD
        if remote_state is RemotePublicationState.PROCESSING:
            return ReconciliationVerdict.IN_SYNC
        if remote_state is RemotePublicationState.ABSENT:
            return (
                ReconciliationVerdict.IN_SYNC
                if local_status == "DRAFT" else ReconciliationVerdict.LOCAL_AHEAD
            )
        return ReconciliationVerdict.CONFLICT
