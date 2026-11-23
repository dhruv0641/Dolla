"""Versioned analytics contracts."""

from flowx_os.analytics.collection import (
    AnalyticsCollectionError,
    AnalyticsSource,
    CollectionWindow,
    MetricAvailability,
    MetricCollectionPolicy,
    MetricCollectionRequest,
    MetricCollectionStatus,
    MetricCollectionTarget,
    MetricDatum,
    MetricUnavailableReason,
    PlatformMetricCollector,
    PlatformMetricObservation,
    StoredMetricObservation,
)
from flowx_os.analytics.metrics import (
    MetricDefinition,
    MetricDefinitionError,
    MetricKind,
    MetricRegistry,
    MetricUnit,
    MissingValuePolicy,
    load_metric_registry,
)
from flowx_os.analytics.snapshots import (
    SnapshotWindowState,
    SnapshotWindowView,
    WindowedSnapshotCoordinator,
    WindowedSnapshotPlan,
    WindowedSnapshotSeries,
)

__all__ = [
    "AnalyticsCollectionError", "AnalyticsSource", "CollectionWindow",
    "MetricAvailability", "MetricCollectionPolicy", "MetricCollectionRequest",
    "MetricCollectionStatus", "MetricCollectionTarget", "MetricDatum",
    "MetricUnavailableReason", "PlatformMetricCollector",
    "PlatformMetricObservation", "StoredMetricObservation",
    "MetricDefinition", "MetricDefinitionError", "MetricKind",
    "MetricRegistry", "MetricUnit", "MissingValuePolicy", "load_metric_registry",
    "SnapshotWindowState", "SnapshotWindowView", "WindowedSnapshotCoordinator",
    "WindowedSnapshotPlan", "WindowedSnapshotSeries",
]
