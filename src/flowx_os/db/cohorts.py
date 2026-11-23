"""Owner-scoped immutable persistence for creative metadata and cohort reports."""

from __future__ import annotations

import json

from flowx_os.analytics.cohorts import (
    CohortAnalysisReport,
    CohortAnalysisRequest,
    CreativeMetadataSnapshot,
)
from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work


class CreativeCohortNotFound(RuntimeError):
    """Required owned publication or analytics evidence was not found."""


class CreativeCohortConflict(RuntimeError):
    """An immutable identity is already bound to different evidence."""


class CreativeCohortRepository:
    """Persist validated evidence without deriving or fabricating missing factors."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def create_snapshot(
        self, snapshot: CreativeMetadataSnapshot,
    ) -> CreativeMetadataSnapshot:
        if not isinstance(snapshot, CreativeMetadataSnapshot):
            raise ValueError("creative metadata snapshot is required")
        factors = json.dumps(
            [item.canonical() for item in snapshot.factors],
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        )
        if len(factors.encode("utf-8")) > 65_536:
            raise ValueError("creative metadata factors exceed their byte limit")
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find_snapshot(
                    connection, snapshot.snapshot_id, snapshot.owner_user_id,
                )
                if existing is not None:
                    return self._require_snapshot_replay(existing, snapshot)
                cursor = await connection.execute(
                    """SELECT b.owner_user_id, b.id, c.id, p.artifact_version,
                              c.storyboard_version, ch.platform, p.published_at
                       FROM publication_jobs AS p
                       JOIN content_items AS c ON c.id = p.content_id
                       JOIN brands AS b ON b.id = c.brand_id
                       JOIN social_channels AS ch
                         ON ch.id = p.channel_id AND ch.brand_id = b.id
                       JOIN storyboard_versions AS sv
                         ON sv.content_id = c.id AND sv.version = %s
                       WHERE p.id = %s AND b.owner_user_id = %s
                         AND p.status = 'PUBLISHED' AND p.published_at IS NOT NULL
                       FOR SHARE OF p, c, b, ch, sv""",
                    (
                        snapshot.storyboard_version, snapshot.publication_id,
                        snapshot.owner_user_id,
                    ),
                )
                source = await cursor.fetchone()
                if source is None:
                    raise CreativeCohortNotFound("owned published object not found")
                expected = (
                    snapshot.owner_user_id, snapshot.brand_id, snapshot.content_id,
                    snapshot.artifact_version, snapshot.storyboard_version,
                    snapshot.platform.value, snapshot.published_at,
                )
                if tuple(source) != expected:
                    raise CreativeCohortConflict("creative metadata lineage changed")
                cursor = await connection.execute(
                    """INSERT INTO creative_metadata_snapshots
                         (snapshot_id, publication_id, owner_user_id, brand_id,
                          content_id, artifact_version, storyboard_version,
                          platform, published_at, schema_version,
                          source_fingerprint, factors, snapshot_fingerprint,
                          storage_fingerprint, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s::jsonb, %s, repeat('0', 64), %s)
                       ON CONFLICT DO NOTHING
                       RETURNING snapshot_fingerprint""",
                    (
                        snapshot.snapshot_id, snapshot.publication_id,
                        snapshot.owner_user_id, snapshot.brand_id,
                        snapshot.content_id, snapshot.artifact_version,
                        snapshot.storyboard_version, snapshot.platform.value,
                        snapshot.published_at, snapshot.schema_version,
                        snapshot.source_fingerprint, factors,
                        snapshot.fingerprint, snapshot.created_at,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    existing = await self._find_snapshot(
                        connection, snapshot.snapshot_id, snapshot.owner_user_id,
                    )
                    if existing is None:
                        raise CreativeCohortConflict(
                            "creative metadata identity is already in use"
                        )
                    return self._require_snapshot_replay(existing, snapshot)
                if row[0] != snapshot.fingerprint:
                    raise CreativeCohortConflict("stored creative metadata changed")
                return snapshot
        except (CreativeCohortConflict, CreativeCohortNotFound, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("creative metadata storage is unavailable") from exc

    async def create_report(
        self, *, request: CohortAnalysisRequest, report: CohortAnalysisReport,
    ) -> CohortAnalysisReport:
        if (
            not isinstance(request, CohortAnalysisRequest)
            or not isinstance(report, CohortAnalysisReport)
            or report.request_fingerprint != request.fingerprint
        ):
            raise ValueError("cohort analysis evidence is invalid")
        bands = json.dumps(
            [item.canonical() for item in request.bands],
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        )
        report_data = json.dumps(
            report.canonical(), sort_keys=True, separators=(",", ":"),
            ensure_ascii=True,
        )
        if len(bands.encode("utf-8")) > 32_768 or len(report_data.encode("utf-8")) > 1_048_576:
            raise ValueError("cohort analysis evidence exceeds its byte limit")
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find_report(
                    connection, request.request_id, request.owner_user_id,
                )
                if existing is not None:
                    return self._require_report_replay(existing, request, report)
                cursor = await connection.execute(
                    """INSERT INTO cohort_analysis_reports
                         (request_id, owner_user_id, request_fingerprint,
                          definition_version, factor, metric_id, window_name,
                          registry_version, registry_fingerprint,
                          minimum_group_size, bands, report_data,
                          report_fingerprint, storage_fingerprint)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s::jsonb, %s::jsonb, %s, repeat('0', 64))
                       ON CONFLICT DO NOTHING
                       RETURNING request_fingerprint, report_fingerprint""",
                    (
                        request.request_id, request.owner_user_id,
                        request.fingerprint, request.definition_version,
                        request.factor.value, request.metric_id,
                        request.window.value, request.registry_version,
                        request.registry_fingerprint,
                        request.minimum_group_size, bands, report_data,
                        report.fingerprint,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    existing = await self._find_report(
                        connection, request.request_id, request.owner_user_id,
                    )
                    if existing is None:
                        raise CreativeCohortConflict(
                            "cohort analysis identity is already in use"
                        )
                    return self._require_report_replay(existing, request, report)
                return self._require_report_replay(row, request, report)
        except (CreativeCohortConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("cohort analysis storage is unavailable") from exc

    @staticmethod
    async def _find_snapshot(connection, snapshot_id, owner_user_id):
        cursor = await connection.execute(
            """SELECT snapshot_fingerprint
               FROM creative_metadata_snapshots
               WHERE snapshot_id = %s AND owner_user_id = %s""",
            (snapshot_id, owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    async def _find_report(connection, request_id, owner_user_id):
        cursor = await connection.execute(
            """SELECT request_fingerprint, report_fingerprint
               FROM cohort_analysis_reports
               WHERE request_id = %s AND owner_user_id = %s""",
            (request_id, owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    def _require_snapshot_replay(row, snapshot):
        if row[0] != snapshot.fingerprint:
            raise CreativeCohortConflict(
                "creative metadata identity identifies different evidence"
            )
        return snapshot

    @staticmethod
    def _require_report_replay(row, request, report):
        if tuple(row) != (request.fingerprint, report.fingerprint):
            raise CreativeCohortConflict(
                "cohort request identifies different immutable evidence"
            )
        return report
