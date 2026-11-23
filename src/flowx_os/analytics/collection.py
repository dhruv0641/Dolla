"""Fail-closed contracts for immutable, platform-specific metric collection."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from flowx_os.analytics.metrics import MetricKind, MetricRegistry, MetricUnit
from flowx_os.publishing.reconciliation import PublicationPlatform


_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_SAFE_REMOTE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_SAFE_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SAFE_STRUCTURED_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
_METRIC_ID = re.compile(r"^(youtube|instagram|facebook)[.][a-z][a-z0-9_]{0,63}$")
_SECRET_REF = re.compile(r"^secretref://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MAX_INTEGER = 9_223_372_036_854_775_807


class CollectionWindow(StrEnum):
    ONE_HOUR = "1H"
    TWENTY_FOUR_HOURS = "24H"
    SEVENTY_TWO_HOURS = "72H"
    SEVEN_DAYS = "7D"
    TWENTY_EIGHT_DAYS = "28D"

    @property
    def duration(self) -> timedelta:
        return {
            CollectionWindow.ONE_HOUR: timedelta(hours=1),
            CollectionWindow.TWENTY_FOUR_HOURS: timedelta(hours=24),
            CollectionWindow.SEVENTY_TWO_HOURS: timedelta(hours=72),
            CollectionWindow.SEVEN_DAYS: timedelta(days=7),
            CollectionWindow.TWENTY_EIGHT_DAYS: timedelta(days=28),
        }[self]


class AnalyticsSource(StrEnum):
    YOUTUBE_ANALYTICS = "YOUTUBE_ANALYTICS"
    INSTAGRAM_GRAPH = "INSTAGRAM_GRAPH"
    FACEBOOK_VIDEO_INSIGHTS = "FACEBOOK_VIDEO_INSIGHTS"

    @classmethod
    def for_platform(cls, platform: PublicationPlatform) -> AnalyticsSource:
        try:
            return {
                PublicationPlatform.YOUTUBE: cls.YOUTUBE_ANALYTICS,
                PublicationPlatform.INSTAGRAM: cls.INSTAGRAM_GRAPH,
                PublicationPlatform.FACEBOOK: cls.FACEBOOK_VIDEO_INSIGHTS,
            }[platform]
        except (KeyError, TypeError):
            raise ValueError("analytics platform is invalid") from None


class MetricAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class MetricUnavailableReason(StrEnum):
    FIELD_NOT_RETURNED = "FIELD_NOT_RETURNED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    PROVIDER_REDACTED = "PROVIDER_REDACTED"


class MetricCollectionStatus(StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"


class AnalyticsCollectionError(RuntimeError):
    """Stable, operator-safe collection failure."""

    def __init__(self, code: str, message: str) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) is None:
            raise ValueError("analytics error code is invalid")
        self.code = code
        super().__init__(message)


def _aware_utc(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
        and value.utcoffset() == timedelta(0)
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class MetricCollectionRequest:
    request_id: UUID
    publication_id: UUID
    owner_user_id: str
    window: CollectionWindow
    metric_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        owner = self.owner_user_id.strip() if isinstance(self.owner_user_id, str) else ""
        metrics = tuple(sorted(self.metric_ids)) if isinstance(self.metric_ids, tuple) else ()
        if (
            not isinstance(self.request_id, UUID)
            or not isinstance(self.publication_id, UUID)
            or _SAFE_OWNER.fullmatch(owner) is None
            or not isinstance(self.window, CollectionWindow)
            or not 1 <= len(metrics) <= 100
            or len(metrics) != len(set(metrics))
            or any(_METRIC_ID.fullmatch(item) is None for item in metrics)
        ):
            raise ValueError("metric collection request is invalid")
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "metric_ids", metrics)

    @property
    def fingerprint(self) -> str:
        values = (
            str(self.request_id), str(self.publication_id), self.owner_user_id,
            self.window.value, *self.metric_ids,
        )
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MetricCollectionTarget:
    request_id: UUID
    publication_id: UUID
    owner_user_id: str
    platform: PublicationPlatform
    publication_state_version: int
    publication_request_fingerprint: str
    channel_id: UUID
    destination_id: str
    destination_fingerprint: str
    credentials_ref: str
    remote_object_id: str
    published_at: datetime
    window: CollectionWindow
    window_started_at: datetime
    window_ended_at: datetime
    source: AnalyticsSource
    registry_version: str
    registry_fingerprint: str
    metric_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        expected_end = self.window_started_at + self.window.duration
        if (
            not isinstance(self.request_id, UUID)
            or not isinstance(self.publication_id, UUID)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or not isinstance(self.platform, PublicationPlatform)
            or type(self.publication_state_version) is not int
            or not 0 <= self.publication_state_version <= _MAX_INTEGER
            or _HEX64.fullmatch(self.publication_request_fingerprint or "") is None
            or not isinstance(self.channel_id, UUID)
            or _SAFE_REMOTE_ID.fullmatch(self.destination_id or "") is None
            or _HEX64.fullmatch(self.destination_fingerprint or "") is None
            or _SECRET_REF.fullmatch(self.credentials_ref or "") is None
            or _SAFE_REMOTE_ID.fullmatch(self.remote_object_id or "") is None
            or not _aware_utc(self.published_at)
            or not isinstance(self.window, CollectionWindow)
            or not _aware_utc(self.window_started_at)
            or not _aware_utc(self.window_ended_at)
            or self.window_started_at != self.published_at
            or self.window_ended_at != expected_end
            or self.source is not AnalyticsSource.for_platform(self.platform)
            or not self.registry_version
            or _HEX64.fullmatch(self.registry_fingerprint or "") is None
            or not 1 <= len(self.metric_ids) <= 100
            or tuple(sorted(self.metric_ids)) != self.metric_ids
            or len(set(self.metric_ids)) != len(self.metric_ids)
        ):
            raise ValueError("metric collection target is invalid")

    @property
    def fingerprint(self) -> str:
        values = (
            str(self.request_id), str(self.publication_id), self.owner_user_id,
            self.platform.value, str(self.publication_state_version),
            self.publication_request_fingerprint, str(self.channel_id),
            self.destination_id, self.destination_fingerprint, self.remote_object_id,
            _timestamp(self.published_at), self.window.value,
            _timestamp(self.window_started_at), _timestamp(self.window_ended_at),
            self.source.value, self.registry_version, self.registry_fingerprint,
            *self.metric_ids,
        )
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MetricDatum:
    metric_id: str
    availability: MetricAvailability
    value: int | float | tuple[tuple[str, int], ...] | Mapping[str, int] | None
    unavailable_reason: MetricUnavailableReason | None = None

    def __post_init__(self) -> None:
        value = self.value
        if isinstance(value, Mapping):
            if not 1 <= len(value) <= 100:
                raise ValueError("structured metric value is invalid")
            pairs = tuple(sorted(value.items()))
            if any(
                not isinstance(key, str)
                or _SAFE_STRUCTURED_KEY.fullmatch(key) is None
                or type(item) is not int
                or not 0 <= item <= _MAX_INTEGER
                for key, item in pairs
            ):
                raise ValueError("structured metric value is invalid")
            value = pairs
            object.__setattr__(self, "value", value)
        if (
            not isinstance(self.metric_id, str)
            or not 1 <= len(self.metric_id) <= 80
            or not isinstance(self.availability, MetricAvailability)
        ):
            raise ValueError("metric datum is invalid")
        if self.availability is MetricAvailability.UNAVAILABLE:
            if value is not None or not isinstance(self.unavailable_reason, MetricUnavailableReason):
                raise ValueError("unavailable metric must have a reason and no value")
            return
        if self.unavailable_reason is not None or value is None or isinstance(value, bool):
            raise ValueError("available metric must have a value and no unavailable reason")
        if isinstance(value, tuple):
            if (
                not 1 <= len(value) <= 100
                or any(
                    not isinstance(pair, tuple)
                    or len(pair) != 2
                    or not isinstance(pair[0], str)
                    or _SAFE_STRUCTURED_KEY.fullmatch(pair[0]) is None
                    or type(pair[1]) is not int
                    or not 0 <= pair[1] <= _MAX_INTEGER
                    for pair in value
                )
                or tuple(sorted(value)) != value
                or len({pair[0] for pair in value}) != len(value)
            ):
                raise ValueError("structured metric value is invalid")
        elif type(value) is int:
            if not 0 <= value <= _MAX_INTEGER:
                raise ValueError("numeric metric value is invalid")
        elif type(value) is float:
            if not math.isfinite(value) or not 0 <= value <= float(_MAX_INTEGER):
                raise ValueError("numeric metric value is invalid")
        else:
            raise ValueError("metric value type is invalid")

    def validate_for(self, registry: MetricRegistry) -> None:
        definition = registry.require(self.metric_id)
        if self.availability is MetricAvailability.UNAVAILABLE:
            return
        if definition.kind is MetricKind.DERIVED:
            raise ValueError("provider observations cannot supply derived metrics")
        if definition.unit is MetricUnit.STRUCTURED:
            if not isinstance(self.value, tuple):
                raise ValueError("structured metric value has the wrong unit")
        elif definition.unit is MetricUnit.COUNT:
            if type(self.value) is not int:
                raise ValueError("count metric value must be an integer")
        elif isinstance(self.value, tuple):
            raise ValueError("numeric metric value has the wrong unit")

    def canonical(self) -> dict[str, object]:
        value: object = self.value
        if isinstance(value, tuple):
            value = {key: item for key, item in value}
        return {
            "metric_id": self.metric_id,
            "availability": self.availability.value,
            "value": value,
            "unavailable_reason": (
                self.unavailable_reason.value if self.unavailable_reason else None
            ),
        }


@dataclass(frozen=True, slots=True)
class PlatformMetricObservation:
    request_id: UUID
    publication_id: UUID
    platform: PublicationPlatform
    destination_id: str
    remote_object_id: str
    window: CollectionWindow
    window_started_at: datetime
    window_ended_at: datetime
    source: AnalyticsSource
    observed_at: datetime
    evidence_id: str
    registry_version: str
    registry_fingerprint: str
    values: tuple[MetricDatum, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.values, tuple) or not all(
            isinstance(item, MetricDatum) for item in self.values
        ):
            raise ValueError("platform metric observation is invalid")
        values = tuple(sorted(self.values, key=lambda item: item.metric_id))
        if (
            not isinstance(self.request_id, UUID)
            or not isinstance(self.publication_id, UUID)
            or not isinstance(self.platform, PublicationPlatform)
            or _SAFE_REMOTE_ID.fullmatch(self.destination_id or "") is None
            or _SAFE_REMOTE_ID.fullmatch(self.remote_object_id or "") is None
            or not isinstance(self.window, CollectionWindow)
            or not _aware_utc(self.window_started_at)
            or not _aware_utc(self.window_ended_at)
            or self.window_ended_at != self.window_started_at + self.window.duration
            or self.source is not AnalyticsSource.for_platform(self.platform)
            or not _aware_utc(self.observed_at)
            or _SAFE_EVIDENCE_ID.fullmatch(self.evidence_id or "") is None
            or not self.registry_version
            or _HEX64.fullmatch(self.registry_fingerprint or "") is None
            or not 1 <= len(values) <= 100
            or len({item.metric_id for item in values}) != len(values)
        ):
            raise ValueError("platform metric observation is invalid")
        object.__setattr__(self, "values", values)

    @property
    def status(self) -> MetricCollectionStatus:
        return (
            MetricCollectionStatus.OK
            if all(item.availability is MetricAvailability.AVAILABLE for item in self.values)
            else MetricCollectionStatus.PARTIAL
        )

    @property
    def fingerprint(self) -> str:
        payload = {
            "request_id": str(self.request_id),
            "publication_id": str(self.publication_id),
            "platform": self.platform.value,
            "destination_id": self.destination_id,
            "remote_object_id": self.remote_object_id,
            "window": self.window.value,
            "window_started_at": self.window_started_at.isoformat(),
            "window_ended_at": self.window_ended_at.isoformat(),
            "source": self.source.value,
            "observed_at": self.observed_at.isoformat(),
            "evidence_id": self.evidence_id,
            "registry_version": self.registry_version,
            "registry_fingerprint": self.registry_fingerprint,
            "values": [item.canonical() for item in self.values],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredMetricObservation:
    observation: PlatformMetricObservation
    owner_user_id: str
    target_fingerprint: str
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.observation, PlatformMetricObservation)
            or _SAFE_OWNER.fullmatch(self.owner_user_id or "") is None
            or _HEX64.fullmatch(self.target_fingerprint or "") is None
            or not _aware_utc(self.created_at)
        ):
            raise ValueError("stored metric observation is invalid")


@dataclass(frozen=True, slots=True)
class MetricCollectionPolicy:
    enabled: bool = False
    maximum_observation_age_seconds: int = 900
    maximum_clock_skew_seconds: int = 30

    def __post_init__(self) -> None:
        if (
            type(self.enabled) is not bool
            or type(self.maximum_observation_age_seconds) is not int
            or not 60 <= self.maximum_observation_age_seconds <= 3_600
            or type(self.maximum_clock_skew_seconds) is not int
            or not 0 <= self.maximum_clock_skew_seconds <= 120
        ):
            raise ValueError("metric collection policy is invalid")


class PlatformMetricProvider(Protocol):
    async def collect(
        self, *, request_id: UUID, publication_id: UUID,
        platform: PublicationPlatform, credentials_ref: str,
        destination_id: str, remote_object_id: str,
        window: CollectionWindow, window_started_at: datetime,
        window_ended_at: datetime, source: AnalyticsSource,
        metric_ids: tuple[str, ...], registry_version: str,
        registry_fingerprint: str,
    ) -> PlatformMetricObservation: ...


class MetricObservationStore(Protocol):
    async def get_existing(
        self, request: MetricCollectionRequest,
    ) -> StoredMetricObservation | None: ...

    async def reserve(
        self, request: MetricCollectionRequest, *, registry: MetricRegistry,
    ) -> MetricCollectionTarget | StoredMetricObservation: ...

    async def record(
        self, *, request: MetricCollectionRequest, target: MetricCollectionTarget,
        observation: PlatformMetricObservation, registry: MetricRegistry,
    ) -> StoredMetricObservation: ...


class PlatformMetricCollector:
    """Perform one bounded provider read and persist exact immutable evidence."""

    def __init__(
        self, *, store: MetricObservationStore,
        provider: PlatformMetricProvider | None, registry: MetricRegistry,
        policy: MetricCollectionPolicy | None = None,
        now=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._store = store
        self._provider = provider
        self._registry = registry
        self._policy = policy or MetricCollectionPolicy()
        self._now = now

    async def collect(self, request: MetricCollectionRequest) -> StoredMetricObservation:
        if not isinstance(request, MetricCollectionRequest):
            raise ValueError("metric collection request is required")
        existing = await self._store.get_existing(request)
        if existing is not None:
            self._validate_existing(request, existing)
            return existing
        if not self._policy.enabled:
            raise AnalyticsCollectionError("CAPABILITY_DISABLED", "analytics collection is disabled")
        if self._provider is None:
            raise AnalyticsCollectionError("PROVIDER_UNAVAILABLE", "analytics provider is unavailable")
        target_or_record = await self._store.reserve(request, registry=self._registry)
        if isinstance(target_or_record, StoredMetricObservation):
            self._validate_existing(request, target_or_record)
            return target_or_record
        target = target_or_record
        self._validate_target(request, target)
        now = self._now()
        if not _aware_utc(now):
            raise AnalyticsCollectionError("CLOCK_INVALID", "analytics collection clock is invalid")
        if now + timedelta(seconds=self._policy.maximum_clock_skew_seconds) < target.window_ended_at:
            raise AnalyticsCollectionError("WINDOW_NOT_READY", "analytics collection window is not complete")
        try:
            observation = await self._provider.collect(
                request_id=request.request_id,
                publication_id=target.publication_id,
                platform=target.platform,
                credentials_ref=target.credentials_ref,
                destination_id=target.destination_id,
                remote_object_id=target.remote_object_id,
                window=target.window,
                window_started_at=target.window_started_at,
                window_ended_at=target.window_ended_at,
                source=target.source,
                metric_ids=target.metric_ids,
                registry_version=target.registry_version,
                registry_fingerprint=target.registry_fingerprint,
            )
        except Exception as exc:
            raise AnalyticsCollectionError(
                "PROVIDER_FAILURE", "analytics provider read failed",
            ) from exc
        self._validate_observation(target, observation, now=now)
        return await self._store.record(
            request=request, target=target, observation=observation,
            registry=self._registry,
        )

    def _validate_existing(
        self, request: MetricCollectionRequest, stored: StoredMetricObservation,
    ) -> None:
        if not isinstance(stored, StoredMetricObservation):
            raise AnalyticsCollectionError("REPLAY_INVALID", "stored analytics evidence is invalid")
        observation = stored.observation
        if (
            stored.owner_user_id != request.owner_user_id
            or observation.request_id != request.request_id
            or observation.publication_id != request.publication_id
            or observation.window is not request.window
            or observation.registry_version != self._registry.version
            or observation.registry_fingerprint != self._registry.fingerprint
            or tuple(item.metric_id for item in observation.values) != request.metric_ids
        ):
            raise AnalyticsCollectionError("REPLAY_CONFLICT", "stored analytics evidence identifies different work")
        try:
            for datum in observation.values:
                definition = self._registry.require(datum.metric_id)
                if definition.platform is not observation.platform or definition.kind is not MetricKind.RAW:
                    raise ValueError("stored metric definition is invalid")
                datum.validate_for(self._registry)
        except ValueError as exc:
            raise AnalyticsCollectionError("REPLAY_INVALID", "stored analytics evidence is invalid") from exc

    def _validate_target(
        self, request: MetricCollectionRequest, target: MetricCollectionTarget,
    ) -> None:
        if not isinstance(target, MetricCollectionTarget):
            raise AnalyticsCollectionError("TARGET_INVALID", "metric collection target is invalid")
        if (
            target.request_id != request.request_id
            or target.publication_id != request.publication_id
            or target.owner_user_id != request.owner_user_id
            or target.window is not request.window
            or target.metric_ids != request.metric_ids
            or target.registry_version != self._registry.version
            or target.registry_fingerprint != self._registry.fingerprint
        ):
            raise AnalyticsCollectionError("TARGET_MISMATCH", "metric collection target does not match request")
        for metric_id in target.metric_ids:
            definition = self._registry.require(metric_id)
            if definition.platform is not target.platform or definition.kind is not MetricKind.RAW:
                raise AnalyticsCollectionError(
                    "METRIC_NOT_COLLECTIBLE", "metric is not collectible for the target platform",
                )

    def _validate_observation(
        self, target: MetricCollectionTarget,
        observation: PlatformMetricObservation,
        *, now: datetime,
    ) -> None:
        if not isinstance(observation, PlatformMetricObservation):
            raise AnalyticsCollectionError("OBSERVATION_INVALID", "analytics observation is invalid")
        if (
            observation.request_id != target.request_id
            or observation.publication_id != target.publication_id
            or observation.platform is not target.platform
            or observation.destination_id != target.destination_id
            or observation.remote_object_id != target.remote_object_id
            or observation.window is not target.window
            or observation.window_started_at != target.window_started_at
            or observation.window_ended_at != target.window_ended_at
            or observation.source is not target.source
            or observation.registry_version != target.registry_version
            or observation.registry_fingerprint != target.registry_fingerprint
            or tuple(item.metric_id for item in observation.values) != target.metric_ids
        ):
            raise AnalyticsCollectionError("OBSERVATION_MISMATCH", "analytics observation identity is invalid")
        if (
            observation.observed_at < target.window_ended_at
            or observation.observed_at > now + timedelta(seconds=self._policy.maximum_clock_skew_seconds)
            or now - observation.observed_at
            > timedelta(seconds=self._policy.maximum_observation_age_seconds)
        ):
            raise AnalyticsCollectionError("OBSERVATION_STALE", "analytics observation time is invalid")
        try:
            for datum in observation.values:
                datum.validate_for(self._registry)
        except ValueError as exc:
            raise AnalyticsCollectionError("OBSERVATION_INVALID", "analytics metric value is invalid") from exc

