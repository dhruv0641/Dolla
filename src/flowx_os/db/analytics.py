"""Owner-scoped persistence for immutable platform metric observations."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from flowx_os.analytics.collection import (
    AnalyticsCollectionError,
    AnalyticsSource,
    CollectionWindow,
    MetricAvailability,
    MetricCollectionRequest,
    MetricCollectionTarget,
    MetricDatum,
    MetricUnavailableReason,
    PlatformMetricObservation,
    StoredMetricObservation,
)
from flowx_os.analytics.metrics import MetricDefinitionError, MetricKind, MetricRegistry
from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.publishing.reconciliation import PublicationPlatform


class MetricObservationNotFound(RuntimeError):
    """The publication is absent or not owned by the requesting principal."""


class MetricObservationConflict(RuntimeError):
    """An idempotency key or stored snapshot identifies different evidence."""


_TARGET_SELECT = """SELECT p.id, b.owner_user_id, ch.platform,
    p.publication_state_version, p.request_fingerprint, p.channel_id,
    p.channel_external_id_snapshot, p.destination_fingerprint,
    p.credentials_ref_snapshot,
    CASE ch.platform
      WHEN 'YOUTUBE' THEN p.remote_post_id
      WHEN 'INSTAGRAM' THEN p.remote_post_id
      WHEN 'FACEBOOK' THEN p.remote_upload_id
    END AS remote_object_id,
    p.published_at
  FROM publication_jobs AS p
  JOIN social_channels AS ch ON ch.id = p.channel_id
  JOIN brands AS b ON b.id = ch.brand_id
  WHERE p.id = %s AND b.owner_user_id = %s
    AND p.status = 'PUBLISHED' AND p.published_at IS NOT NULL
    AND ch.enabled = true AND ch.permissions_status = 'VALID'
    AND ch.external_channel_id = p.channel_external_id_snapshot
    AND ch.credentials_ref = p.credentials_ref_snapshot
    AND (
      (ch.platform = 'YOUTUBE' AND p.publication_contract = 'YOUTUBE_V1') OR
      (ch.platform = 'INSTAGRAM' AND p.publication_contract = 'INSTAGRAM_REELS_V1') OR
      (ch.platform = 'FACEBOOK' AND p.publication_contract = 'FACEBOOK_REELS_V1')
    )"""

_RECORD_COLUMNS = """o.request_id, o.publication_id, o.owner_user_id,
    o.platform, o.destination_id, o.remote_object_id, o.window_name,
    o.window_started_at, o.window_ended_at, o.source, o.observed_at,
    o.provider_evidence_id, o.registry_version, o.registry_fingerprint,
    o.metric_data, o.target_fingerprint, o.observation_fingerprint, o.created_at"""
_RETURN_COLUMNS = """request_id, publication_id, owner_user_id,
    platform, destination_id, remote_object_id, window_name,
    window_started_at, window_ended_at, source, observed_at,
    provider_evidence_id, registry_version, registry_fingerprint,
    metric_data, target_fingerprint, observation_fingerprint, created_at"""


class MetricObservationRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def get_existing(
        self, request: MetricCollectionRequest,
    ) -> StoredMetricObservation | None:
        if not isinstance(request, MetricCollectionRequest):
            raise ValueError("metric collection request is required")
        try:
            async with unit_of_work(self._pool) as connection:
                row = await self._find_existing(connection, request)
                return None if row is None else self._record(row)
        except (MetricObservationConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("metric observation storage is unavailable") from exc

    async def reserve(
        self, request: MetricCollectionRequest, *, registry: MetricRegistry,
        now: datetime,
    ) -> MetricCollectionTarget | StoredMetricObservation:
        if (
            not isinstance(request, MetricCollectionRequest)
            or not isinstance(registry, MetricRegistry)
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() != timedelta(0)
        ):
            raise ValueError("metric collection reservation is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    _TARGET_SELECT + " FOR UPDATE OF p",
                    (request.publication_id, request.owner_user_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise MetricObservationNotFound("published object not found")
                target = self._target(row, request=request, registry=registry)
                if target.window_ended_at > now:
                    raise AnalyticsCollectionError(
                        "WINDOW_NOT_READY", "metric collection window is not complete",
                    )
                cursor = await connection.execute(
                    """SELECT publication_id, owner_user_id, request_fingerprint,
                              target_fingerprint, window_name, metric_ids,
                              registry_version, registry_fingerprint, status
                       FROM analytics_metric_collection_attempts
                       WHERE request_id = %s
                       FOR UPDATE""",
                    (request.request_id,),
                )
                attempt = await cursor.fetchone()
                metric_ids_json = json.dumps(request.metric_ids, separators=(",", ":"))
                if attempt is not None:
                    self._require_attempt(attempt, request=request, target=target)
                    if attempt[-1] == "RECORDED":
                        existing = await self._find_existing(connection, request)
                        if existing is None:
                            raise RepositoryUnavailable("recorded metric evidence is unavailable")
                        stored = self._record(existing)
                        if stored.target_fingerprint != target.fingerprint:
                            raise MetricObservationConflict(
                                "stored metric evidence identifies a different target"
                            )
                        return stored
                    raise AnalyticsCollectionError(
                        "REQUEST_OUTCOME_UNKNOWN",
                        "metric collection request is already reserved and requires operator review",
                    )
                cursor = await connection.execute(
                    """SELECT request_id
                       FROM analytics_metric_collection_attempts
                       WHERE publication_id = %s AND window_name = %s
                         AND registry_version = %s AND metric_ids = %s::jsonb
                       FOR UPDATE""",
                    (
                        request.publication_id, request.window.value,
                        registry.version, metric_ids_json,
                    ),
                )
                if await cursor.fetchone() is not None:
                    raise MetricObservationConflict(
                        "snapshot identity already belongs to another request"
                    )
                cursor = await connection.execute(
                    """INSERT INTO analytics_metric_collection_attempts
                         (request_id, publication_id, owner_user_id,
                          request_fingerprint, target_fingerprint, window_name,
                          metric_ids, registry_version, registry_fingerprint, status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, 'RESERVED')
                       ON CONFLICT (request_id) DO NOTHING
                       RETURNING request_id""",
                    (
                        request.request_id, request.publication_id,
                        request.owner_user_id, request.fingerprint,
                        target.fingerprint, request.window.value, metric_ids_json,
                        registry.version, registry.fingerprint,
                    ),
                )
                if await cursor.fetchone() is None:
                    raise MetricObservationConflict("metric collection request could not be reserved")
                return target
        except (
            AnalyticsCollectionError,
            MetricObservationConflict,
            MetricObservationNotFound,
            ValueError,
        ):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("metric observation storage is unavailable") from exc

    async def record(
        self, *, request: MetricCollectionRequest, target: MetricCollectionTarget,
        observation: PlatformMetricObservation, registry: MetricRegistry,
    ) -> StoredMetricObservation:
        if (
            not isinstance(request, MetricCollectionRequest)
            or not isinstance(target, MetricCollectionTarget)
            or not isinstance(observation, PlatformMetricObservation)
            or not isinstance(registry, MetricRegistry)
        ):
            raise ValueError("metric observation evidence is invalid")
        if (
            target.request_id != request.request_id
            or target.publication_id != request.publication_id
            or target.owner_user_id != request.owner_user_id
            or target.window is not request.window
            or target.metric_ids != request.metric_ids
            or observation.request_id != request.request_id
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
            or registry.version != target.registry_version
            or registry.fingerprint != target.registry_fingerprint
        ):
            raise ValueError("metric observation identity is invalid")
        try:
            for datum in observation.values:
                definition = registry.require(datum.metric_id)
                if definition.platform is not target.platform or definition.kind is not MetricKind.RAW:
                    raise ValueError("metric observation definition is invalid")
                datum.validate_for(registry)
        except (ValueError, LookupError) as exc:
            raise ValueError("metric observation values are invalid") from exc
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find_existing(connection, request)
                if existing is not None:
                    return self._require_replay(
                        existing, target=target, observation=observation,
                    )
                cursor = await connection.execute(
                    _TARGET_SELECT + " FOR UPDATE OF p",
                    (request.publication_id, request.owner_user_id),
                )
                current_row = await cursor.fetchone()
                if current_row is None:
                    raise MetricObservationNotFound("published object not found")
                current = self._target_from_snapshot(current_row, target=target)
                if current != target:
                    raise MetricObservationConflict(
                        "published object changed during metric collection"
                    )
                cursor = await connection.execute(
                    """SELECT publication_id, owner_user_id, request_fingerprint,
                              target_fingerprint, window_name, metric_ids,
                              registry_version, registry_fingerprint, status
                       FROM analytics_metric_collection_attempts
                       WHERE request_id = %s
                       FOR UPDATE""",
                    (request.request_id,),
                )
                attempt = await cursor.fetchone()
                if attempt is None:
                    raise MetricObservationConflict("metric collection request was not reserved")
                self._require_attempt(attempt, request=request, target=target)
                if attempt[-1] == "RECORDED":
                    existing = await self._find_existing(connection, request)
                    if existing is None:
                        raise RepositoryUnavailable("recorded metric evidence is unavailable")
                    return self._require_replay(
                        existing, target=target, observation=observation,
                    )
                metric_data = json.dumps(
                    [item.canonical() for item in observation.values],
                    sort_keys=True, separators=(",", ":"), allow_nan=False,
                )
                if len(metric_data.encode("utf-8")) > 65_536:
                    raise ValueError("metric observation exceeds its byte limit")
                cursor = await connection.execute(
                    f"""INSERT INTO analytics_metric_observations
                        (request_id, publication_id, owner_user_id, platform,
                         publication_state_version, publication_request_fingerprint,
                         channel_id, destination_id, destination_fingerprint,
                         remote_object_id, published_at, window_name,
                         window_started_at, window_ended_at, source,
                         registry_version, registry_fingerprint, metric_data,
                         collection_status, provider_evidence_id, observed_at,
                         target_fingerprint)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                               %s, %s, %s, %s)
                       ON CONFLICT (request_id) DO NOTHING
                       RETURNING {_RETURN_COLUMNS}""",
                    (
                        request.request_id, target.publication_id,
                        target.owner_user_id, target.platform.value,
                        target.publication_state_version,
                        target.publication_request_fingerprint,
                        target.channel_id, target.destination_id,
                        target.destination_fingerprint, target.remote_object_id,
                        target.published_at, target.window.value,
                        target.window_started_at, target.window_ended_at,
                        target.source.value, target.registry_version,
                        target.registry_fingerprint, metric_data,
                        observation.status.value, observation.evidence_id,
                        observation.observed_at, target.fingerprint,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    existing = await self._find_existing(connection, request)
                    if existing is None:
                        raise MetricObservationConflict(
                            "metric observation could not be persisted"
                        )
                    return self._require_replay(
                        existing, target=target, observation=observation,
                    )
                cursor = await connection.execute(
                    """UPDATE analytics_metric_collection_attempts
                       SET status = 'RECORDED', recorded_at = now()
                       WHERE request_id = %s AND status = 'RESERVED'
                       RETURNING request_id""",
                    (request.request_id,),
                )
                if await cursor.fetchone() is None:
                    raise MetricObservationConflict(
                        "metric collection reservation could not be completed"
                    )
                return self._record(row)
        except (
            MetricObservationConflict,
            MetricObservationNotFound,
            ValueError,
        ):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("metric observation storage is unavailable") from exc

    @staticmethod
    async def _find_existing(connection, request: MetricCollectionRequest):
        cursor = await connection.execute(
            f"""SELECT {_RECORD_COLUMNS}
                FROM analytics_metric_observations AS o
                JOIN publication_jobs AS p ON p.id = o.publication_id
                JOIN social_channels AS ch ON ch.id = p.channel_id
                JOIN brands AS b ON b.id = ch.brand_id
                WHERE o.request_id = %s AND b.owner_user_id = %s""",
            (request.request_id, request.owner_user_id),
        )
        row = await cursor.fetchone()
        if row is not None:
            if row[1] != request.publication_id or row[2] != request.owner_user_id:
                raise MetricObservationConflict(
                    "metric collection request already identifies different work"
                )
            stored = MetricObservationRepository._record(row)
            if (
                stored.observation.window is not request.window
                or tuple(item.metric_id for item in stored.observation.values)
                != request.metric_ids
            ):
                raise MetricObservationConflict(
                    "metric collection request already identifies different work"
                )
        return row

    @classmethod
    def _require_replay(
        cls, row, *, target: MetricCollectionTarget,
        observation: PlatformMetricObservation,
    ) -> StoredMetricObservation:
        stored = cls._record(row)
        if (
            stored.target_fingerprint != target.fingerprint
            or stored.observation.fingerprint != observation.fingerprint
        ):
            raise MetricObservationConflict(
                "metric collection request already identifies different evidence"
            )
        return stored

    @staticmethod
    def _require_attempt(
        row, *, request: MetricCollectionRequest, target: MetricCollectionTarget,
    ) -> None:
        try:
            (
                publication_id, owner_user_id, request_fingerprint,
                target_fingerprint, window_name, metric_ids,
                registry_version, registry_fingerprint, status,
            ) = row
            if isinstance(metric_ids, str):
                metric_ids = json.loads(metric_ids)
            if (
                publication_id != request.publication_id
                or owner_user_id != request.owner_user_id
                or request_fingerprint.strip() != request.fingerprint
                or target_fingerprint.strip() != target.fingerprint
                or window_name != request.window.value
                or tuple(metric_ids) != request.metric_ids
                or registry_version != target.registry_version
                or registry_fingerprint.strip() != target.registry_fingerprint
                or status not in {"RESERVED", "RECORDED"}
            ):
                raise MetricObservationConflict(
                    "metric collection request already identifies different work"
                )
        except MetricObservationConflict:
            raise
        except Exception as exc:
            raise RepositoryUnavailable("stored metric collection attempt is invalid") from exc

    @classmethod
    def _target(
        cls, row, *, request: MetricCollectionRequest, registry: MetricRegistry,
    ) -> MetricCollectionTarget:
        try:
            platform = PublicationPlatform(row[2])
            for metric_id in request.metric_ids:
                try:
                    definition = registry.require(metric_id)
                except MetricDefinitionError as exc:
                    raise AnalyticsCollectionError(
                        "METRIC_NOT_COLLECTIBLE",
                        "metric is not collectible for the published platform",
                    ) from exc
                if definition.platform is not platform or definition.kind is not MetricKind.RAW:
                    raise AnalyticsCollectionError(
                        "METRIC_NOT_COLLECTIBLE",
                        "metric is not collectible for the published platform",
                    )
            published_at = row[10]
            return MetricCollectionTarget(
                request_id=request.request_id,
                publication_id=row[0], owner_user_id=row[1], platform=platform,
                publication_state_version=row[3],
                publication_request_fingerprint=row[4].strip(), channel_id=row[5],
                destination_id=row[6], destination_fingerprint=row[7].strip(),
                credentials_ref=row[8], remote_object_id=row[9],
                published_at=published_at, window=request.window,
                window_started_at=published_at,
                window_ended_at=published_at + request.window.duration,
                source=AnalyticsSource.for_platform(platform),
                registry_version=registry.version,
                registry_fingerprint=registry.fingerprint,
                metric_ids=request.metric_ids,
            )
        except AnalyticsCollectionError:
            raise
        except Exception as exc:
            raise RepositoryUnavailable("stored metric collection target is invalid") from exc

    @classmethod
    def _target_from_snapshot(
        cls, row, *, target: MetricCollectionTarget,
    ) -> MetricCollectionTarget:
        try:
            published_at = row[10]
            platform = PublicationPlatform(row[2])
            return MetricCollectionTarget(
                request_id=target.request_id, publication_id=row[0],
                owner_user_id=row[1], platform=platform,
                publication_state_version=row[3],
                publication_request_fingerprint=row[4].strip(), channel_id=row[5],
                destination_id=row[6], destination_fingerprint=row[7].strip(),
                credentials_ref=row[8], remote_object_id=row[9],
                published_at=published_at, window=target.window,
                window_started_at=published_at,
                window_ended_at=published_at + target.window.duration,
                source=AnalyticsSource.for_platform(platform),
                registry_version=target.registry_version,
                registry_fingerprint=target.registry_fingerprint,
                metric_ids=target.metric_ids,
            )
        except Exception as exc:
            raise RepositoryUnavailable("stored metric collection target is invalid") from exc

    @staticmethod
    def _record(row) -> StoredMetricObservation:
        try:
            (
                request_id, publication_id, owner_user_id, platform,
                destination_id, remote_object_id, window_name,
                window_started_at, window_ended_at, source, observed_at,
                evidence_id, registry_version, registry_fingerprint,
                metric_data, target_fingerprint, storage_fingerprint, created_at,
            ) = row
            if isinstance(metric_data, str):
                metric_data = json.loads(metric_data)
            values = tuple(
                MetricDatum(
                    metric_id=item["metric_id"],
                    availability=MetricAvailability(item["availability"]),
                    value=item["value"],
                    unavailable_reason=(
                        MetricUnavailableReason(item["unavailable_reason"])
                        if item["unavailable_reason"] is not None else None
                    ),
                )
                for item in metric_data
            )
            observation = PlatformMetricObservation(
                request_id=request_id, publication_id=publication_id,
                platform=PublicationPlatform(platform), destination_id=destination_id,
                remote_object_id=remote_object_id, window=CollectionWindow(window_name),
                window_started_at=window_started_at, window_ended_at=window_ended_at,
                source=AnalyticsSource(source), observed_at=observed_at,
                evidence_id=evidence_id, registry_version=registry_version,
                registry_fingerprint=registry_fingerprint.strip(), values=values,
            )
            return StoredMetricObservation(
                observation=observation, owner_user_id=owner_user_id,
                target_fingerprint=target_fingerprint.strip(),
                storage_fingerprint=storage_fingerprint.strip(), created_at=created_at,
            )
        except Exception as exc:
            raise RepositoryUnavailable("stored metric observation is invalid") from exc
