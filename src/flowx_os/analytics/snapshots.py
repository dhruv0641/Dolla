"""Deterministic publish-relative snapshot scheduling and missing-value views."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID, uuid5

from flowx_os.analytics.collection import (
    AnalyticsCollectionError,
    CollectionWindow,
    MetricAvailability,
    MetricCollectionRequest,
    MetricCollectionStatus,
    PlatformMetricCollector,
    StoredMetricObservation,
)
from flowx_os.analytics.metrics import MetricKind, MetricRegistry


_SAFE_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
_REQUEST_NAMESPACE = UUID("2f95ac67-20e5-5c8f-90ae-cb6bb09a863d")
_WINDOWS = tuple(CollectionWindow)


def _aware_utc(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
        and value.utcoffset() == timedelta(0)
    )


class SnapshotWindowState(StrEnum):
    FUTURE = "FUTURE"
    DUE = "DUE"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


@dataclass(frozen=True, slots=True)
class WindowedSnapshotPlan:
    publication_id: UUID
    owner_user_id: str
    published_at: datetime
    metric_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        owner = self.owner_user_id.strip() if isinstance(self.owner_user_id, str) else ""
        metrics = self.metric_ids if isinstance(self.metric_ids, tuple) else ()
        if (
            not isinstance(self.publication_id, UUID)
            or _SAFE_OWNER.fullmatch(owner) is None
            or not _aware_utc(self.published_at)
            or not 1 <= len(metrics) <= 100
            or any(not isinstance(metric_id, str) for metric_id in metrics)
            or len(metrics) != len(set(metrics))
        ):
            raise ValueError("windowed snapshot plan is invalid")
        metrics = tuple(sorted(metrics))
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "metric_ids", metrics)

    def validate_registry(self, registry: MetricRegistry) -> None:
        if not isinstance(registry, MetricRegistry):
            raise ValueError("metric registry is required")
        platform = None
        for metric_id in self.metric_ids:
            definition = registry.require(metric_id)
            if definition.kind is not MetricKind.RAW:
                raise ValueError("snapshot plans may request raw metrics only")
            if platform is None:
                platform = definition.platform
            elif definition.platform is not platform:
                raise ValueError("snapshot plan metrics must share one platform")

    def request_for(
        self, window: CollectionWindow, *, registry: MetricRegistry,
    ) -> MetricCollectionRequest:
        if not isinstance(window, CollectionWindow):
            raise ValueError("snapshot window is invalid")
        self.validate_registry(registry)
        identity = "|".join((
            "flowx-windowed-snapshot-v1", str(self.publication_id),
            self.owner_user_id, window.value, registry.version,
            registry.fingerprint, *self.metric_ids,
        ))
        return MetricCollectionRequest(
            request_id=uuid5(_REQUEST_NAMESPACE, identity),
            publication_id=self.publication_id,
            owner_user_id=self.owner_user_id,
            window=window,
            metric_ids=self.metric_ids,
        )

    def window_ends_at(self, window: CollectionWindow) -> datetime:
        if not isinstance(window, CollectionWindow):
            raise ValueError("snapshot window is invalid")
        return self.published_at + window.duration

    def due_requests(
        self, *, registry: MetricRegistry, now: datetime,
    ) -> tuple[MetricCollectionRequest, ...]:
        if not _aware_utc(now):
            raise ValueError("snapshot scheduling clock must be UTC")
        return tuple(
            self.request_for(window, registry=registry)
            for window in _WINDOWS
            if self.window_ends_at(window) <= now
        )


@dataclass(frozen=True, slots=True)
class SnapshotWindowView:
    window: CollectionWindow
    scheduled_at: datetime
    state: SnapshotWindowState
    observed_at: datetime | None
    unavailable_metric_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.window, CollectionWindow)
            or not _aware_utc(self.scheduled_at)
            or not isinstance(self.state, SnapshotWindowState)
            or (self.observed_at is not None and not _aware_utc(self.observed_at))
            or tuple(sorted(self.unavailable_metric_ids)) != self.unavailable_metric_ids
            or len(set(self.unavailable_metric_ids)) != len(self.unavailable_metric_ids)
            or (self.state in {
                SnapshotWindowState.FUTURE, SnapshotWindowState.DUE,
                SnapshotWindowState.REQUIRES_REVIEW,
            }
                and (self.observed_at is not None or self.unavailable_metric_ids))
            or (self.state in {SnapshotWindowState.COMPLETE, SnapshotWindowState.PARTIAL}
                and self.observed_at is None)
            or (self.state is SnapshotWindowState.COMPLETE and self.unavailable_metric_ids)
            or (self.state is SnapshotWindowState.PARTIAL and not self.unavailable_metric_ids)
        ):
            raise ValueError("snapshot window view is invalid")


@dataclass(frozen=True, slots=True)
class WindowedSnapshotSeries:
    plan: WindowedSnapshotPlan
    registry_version: str
    registry_fingerprint: str
    windows: tuple[SnapshotWindowView, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.plan, WindowedSnapshotPlan)
            or not self.registry_version
            or not re.fullmatch(r"[0-9a-f]{64}", self.registry_fingerprint or "")
            or tuple(item.window for item in self.windows) != _WINDOWS
        ):
            raise ValueError("windowed snapshot series is invalid")

    @classmethod
    def build(
        cls, *, plan: WindowedSnapshotPlan, registry: MetricRegistry,
        now: datetime, records: tuple[StoredMetricObservation, ...] = (),
        unresolved_windows: tuple[CollectionWindow, ...] = (),
    ) -> WindowedSnapshotSeries:
        if not isinstance(plan, WindowedSnapshotPlan) or not _aware_utc(now):
            raise ValueError("snapshot series inputs are invalid")
        plan.validate_registry(registry)
        if (
            not isinstance(unresolved_windows, tuple)
            or any(not isinstance(window, CollectionWindow) for window in unresolved_windows)
            or len(unresolved_windows) != len(set(unresolved_windows))
            or any(plan.window_ends_at(window) > now for window in unresolved_windows)
        ):
            raise ValueError("unresolved snapshot windows are invalid")
        unresolved = frozenset(unresolved_windows)
        expected = {
            plan.request_for(window, registry=registry).request_id: window
            for window in _WINDOWS
        }
        by_window: dict[CollectionWindow, StoredMetricObservation] = {}
        lineage = None
        for record in records:
            if not isinstance(record, StoredMetricObservation):
                raise ValueError("snapshot series record is invalid")
            observation = record.observation
            window = expected.get(observation.request_id)
            current_lineage = (
                observation.platform, observation.destination_id,
                observation.remote_object_id,
            )
            if (
                window is None
                or record.owner_user_id != plan.owner_user_id
                or observation.publication_id != plan.publication_id
                or observation.window is not window
                or observation.window_started_at != plan.published_at
                or observation.window_ended_at != plan.window_ends_at(window)
                or observation.observed_at < observation.window_ended_at
                or observation.observed_at > now
                or observation.registry_version != registry.version
                or observation.registry_fingerprint != registry.fingerprint
                or tuple(item.metric_id for item in observation.values) != plan.metric_ids
                or window in by_window
                or window in unresolved
                or (lineage is not None and current_lineage != lineage)
            ):
                raise ValueError("snapshot series record lineage is invalid")
            lineage = current_lineage
            by_window[window] = record
        views: list[SnapshotWindowView] = []
        for window in _WINDOWS:
            scheduled_at = plan.window_ends_at(window)
            record = by_window.get(window)
            if record is None:
                views.append(SnapshotWindowView(
                    window=window, scheduled_at=scheduled_at,
                    state=(
                        SnapshotWindowState.REQUIRES_REVIEW if window in unresolved
                        else SnapshotWindowState.DUE if scheduled_at <= now
                        else SnapshotWindowState.FUTURE
                    ),
                    observed_at=None, unavailable_metric_ids=(),
                ))
                continue
            unavailable = tuple(
                item.metric_id for item in record.observation.values
                if item.availability is MetricAvailability.UNAVAILABLE
            )
            views.append(SnapshotWindowView(
                window=window, scheduled_at=scheduled_at,
                state=(SnapshotWindowState.COMPLETE
                       if record.observation.status is MetricCollectionStatus.OK
                       else SnapshotWindowState.PARTIAL),
                observed_at=record.observation.observed_at,
                unavailable_metric_ids=unavailable,
            ))
        return cls(
            plan=plan, registry_version=registry.version,
            registry_fingerprint=registry.fingerprint, windows=tuple(views),
        )


class WindowedSnapshotCoordinator:
    """Authorize only deterministic snapshot requests whose fixed window is due."""

    def __init__(
        self, *, collector: PlatformMetricCollector, registry: MetricRegistry,
        now=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._collector = collector
        self._registry = registry
        self._now = now

    async def collect(
        self, *, plan: WindowedSnapshotPlan, window: CollectionWindow,
    ) -> StoredMetricObservation:
        if not isinstance(plan, WindowedSnapshotPlan) or not isinstance(window, CollectionWindow):
            raise ValueError("windowed snapshot collection inputs are invalid")
        now = self._now()
        if not _aware_utc(now):
            raise AnalyticsCollectionError("CLOCK_INVALID", "snapshot scheduling clock is invalid")
        if plan.window_ends_at(window) > now:
            raise AnalyticsCollectionError("WINDOW_NOT_READY", "snapshot window is not complete")
        return await self._collector.collect(plan.request_for(window, registry=self._registry))

