"""Owner-scoped persistence for deterministic community analysis evidence."""

from __future__ import annotations

from flowx_os.community.analysis import (
    AnalysisStatus,
    CommentClassification,
    CommunityAnalysisError,
    CommunityAnalysisReport,
    CommunityAnalysisRequest,
    CommunityCommentEvidence,
    CommunityEvidenceSnapshot,
    CommunityTheme,
    SafetyCategory,
    SafetySeverity,
    ThemeCluster,
)
from flowx_os.community.comments import CommentState
from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.publishing.reconciliation import PublicationPlatform


class CommunityAnalysisNotFound(RuntimeError):
    """The publication or complete authorized comment snapshot is unavailable."""


class CommunityAnalysisConflict(RuntimeError):
    """An idempotency key or immutable evidence identity conflicts."""


_REPORT_COLUMNS = """request_id, owner_user_id, publication_id,
    request_fingerprint, ingestion_sync_id, ingestion_target_fingerprint,
    source_snapshot_fingerprint, theme_taxonomy_version, safety_policy_version,
    status, total_comment_count, analyzed_comment_count, deleted_comment_count,
    review_required_count, cluster_count, requested_at, created_at,
    report_fingerprint, outbound_action_authorized"""

_COMMENT_COLUMNS = """id, publication_id, remote_comment_id,
    comment_fingerprint, comment_text, state, provider_updated_at"""


class CommunityAnalysisRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def get_existing(
        self, request: CommunityAnalysisRequest,
    ) -> CommunityAnalysisReport | None:
        if not isinstance(request, CommunityAnalysisRequest):
            raise ValueError("community analysis request is required")
        try:
            async with unit_of_work(self._pool) as connection:
                row = await self._find_report(connection, request)
                if row is None:
                    return None
                return await self._hydrate(connection, row, request=request)
        except (CommunityAnalysisConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community analysis storage is unavailable") from exc

    async def load_snapshot(
        self, request: CommunityAnalysisRequest, *, maximum_comments: int,
    ) -> CommunityEvidenceSnapshot:
        if (
            not isinstance(request, CommunityAnalysisRequest)
            or type(maximum_comments) is not int
            or not 1 <= maximum_comments <= 5_000
        ):
            raise ValueError("community analysis snapshot request is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                run = await self._latest_run(connection, request, lock_publication=False)
                if run is None:
                    raise CommunityAnalysisNotFound("authorized comment evidence not found")
                if run[5] != "COMPLETE":
                    raise CommunityAnalysisError(
                        "INGESTION_NOT_COMPLETE",
                        "latest authorized comment ingestion is not complete",
                    )
                comments = await self._current_comments(
                    connection, request.publication_id, maximum_comments=maximum_comments,
                )
                return self._snapshot(run, comments, request=request)
        except (
            CommunityAnalysisError,
            CommunityAnalysisNotFound,
            ValueError,
        ):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community analysis storage is unavailable") from exc

    async def persist(
        self, request: CommunityAnalysisRequest, snapshot: CommunityEvidenceSnapshot,
        report: CommunityAnalysisReport,
    ) -> CommunityAnalysisReport:
        if (
            not isinstance(request, CommunityAnalysisRequest)
            or not isinstance(snapshot, CommunityEvidenceSnapshot)
            or not isinstance(report, CommunityAnalysisReport)
            or report.request_id != request.request_id
            or report.owner_user_id != request.owner_user_id
            or report.publication_id != request.publication_id
            or report.request_fingerprint != request.fingerprint
            or report.ingestion_sync_id != snapshot.ingestion_sync_id
            or report.ingestion_target_fingerprint != snapshot.ingestion_target_fingerprint
            or report.source_snapshot_fingerprint != snapshot.fingerprint
            or report.theme_taxonomy_version != request.theme_taxonomy_version
            or report.safety_policy_version != request.safety_policy_version
            or report.requested_at != request.requested_at
        ):
            raise ValueError("community analysis persistence identity is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find_report(connection, request)
                if existing is not None:
                    stored = await self._hydrate(connection, existing, request=request)
                    return self._require_replay(stored, report)

                run = await self._latest_run(connection, request, lock_publication=True)
                if run is None:
                    raise CommunityAnalysisNotFound("authorized comment evidence not found")
                if run[5] != "COMPLETE":
                    raise CommunityAnalysisError(
                        "INGESTION_NOT_COMPLETE",
                        "latest authorized comment ingestion is not complete",
                    )
                comments = await self._current_comments(
                    connection, request.publication_id,
                    maximum_comments=max(1, len(snapshot.comments)),
                )
                current = self._snapshot(run, comments, request=request)
                if current != snapshot:
                    raise CommunityAnalysisConflict(
                        "comment evidence changed during community analysis"
                    )

                cursor = await connection.execute(
                    f"""INSERT INTO community_analysis_reports
                      ({_REPORT_COLUMNS})
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING {_REPORT_COLUMNS}""",
                    (
                        report.request_id, report.owner_user_id, report.publication_id,
                        report.request_fingerprint, report.ingestion_sync_id,
                        report.ingestion_target_fingerprint,
                        report.source_snapshot_fingerprint,
                        report.theme_taxonomy_version, report.safety_policy_version,
                        report.status.value, report.total_comment_count,
                        report.analyzed_comment_count, report.deleted_comment_count,
                        report.review_required_count, len(report.clusters),
                        report.requested_at, report.created_at,
                        report.report_fingerprint, report.outbound_action_authorized,
                    ),
                )
                inserted = await cursor.fetchone()
                if inserted is None:
                    existing = await self._find_report(connection, request)
                    if existing is None:
                        raise CommunityAnalysisConflict(
                            "community analysis snapshot already has another identity"
                        )
                    stored = await self._hydrate(connection, existing, request=request)
                    return self._require_replay(stored, report)

                for item in report.classifications:
                    cursor = await connection.execute(
                        """INSERT INTO community_comment_classifications
                          (report_request_id, comment_version_id, remote_comment_id,
                           comment_fingerprint, theme, theme_rule_id, safety_category,
                           safety_severity, safety_rule_ids, requires_human_review,
                           classification_fingerprint)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING comment_version_id""",
                        (
                            report.request_id, item.comment_version_id,
                            item.remote_comment_id, item.comment_fingerprint,
                            item.theme.value, item.theme_rule_id,
                            item.safety_category.value, item.safety_severity.value,
                            list(item.safety_rule_ids), item.requires_human_review,
                            item.classification_fingerprint,
                        ),
                    )
                    if await cursor.fetchone() is None:
                        raise CommunityAnalysisConflict(
                            "comment classification could not be persisted"
                        )
                for cluster in report.clusters:
                    cursor = await connection.execute(
                        """INSERT INTO community_theme_clusters
                          (report_request_id, theme, member_count,
                           review_required_count, classification_fingerprints,
                           cluster_fingerprint)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING theme""",
                        (
                            report.request_id, cluster.theme.value,
                            cluster.member_count, cluster.review_required_count,
                            list(cluster.classification_fingerprints),
                            cluster.cluster_fingerprint,
                        ),
                    )
                    if await cursor.fetchone() is None:
                        raise CommunityAnalysisConflict(
                            "theme cluster could not be persisted"
                        )
                return report
        except (
            CommunityAnalysisConflict,
            CommunityAnalysisError,
            CommunityAnalysisNotFound,
            ValueError,
        ):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community analysis storage is unavailable") from exc

    @staticmethod
    async def _find_report(connection, request: CommunityAnalysisRequest):
        cursor = await connection.execute(
            f"""SELECT {_REPORT_COLUMNS}
                FROM community_analysis_reports
                WHERE request_id = %s AND owner_user_id = %s""",
            (request.request_id, request.owner_user_id),
        )
        row = await cursor.fetchone()
        if row is not None and (
            row[2] != request.publication_id
            or row[3] != request.fingerprint
            or row[7] != request.theme_taxonomy_version
            or row[8] != request.safety_policy_version
            or row[15] != request.requested_at
        ):
            raise CommunityAnalysisConflict(
                "community analysis request identifies different work"
            )
        return row

    @staticmethod
    async def _latest_run(connection, request, *, lock_publication: bool):
        if lock_publication:
            cursor = await connection.execute(
                """SELECT p.id
                   FROM publication_jobs AS p
                   JOIN social_channels AS ch ON ch.id = p.channel_id
                   JOIN brands AS b ON b.id = ch.brand_id
                   WHERE p.id = %s AND b.owner_user_id = %s
                   FOR UPDATE OF p""",
                (request.publication_id, request.owner_user_id),
            )
            if await cursor.fetchone() is None:
                return None
        cursor = await connection.execute(
            """SELECT r.sync_id, r.publication_id, r.owner_user_id, r.platform,
                      r.target_fingerprint, r.status, r.updated_at
               FROM comment_ingestion_runs AS r
               JOIN publication_jobs AS p ON p.id = r.publication_id
               JOIN social_channels AS ch ON ch.id = p.channel_id
               JOIN brands AS b ON b.id = ch.brand_id
               WHERE r.publication_id = %s AND b.owner_user_id = %s
                 AND r.owner_user_id = b.owner_user_id
               ORDER BY r.created_at DESC, r.sync_id DESC
               LIMIT 1""" + (" FOR SHARE OF r" if lock_publication else ""),
            (request.publication_id, request.owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    async def _current_comments(connection, publication_id, *, maximum_comments: int):
        cursor = await connection.execute(
            f"""SELECT {_COMMENT_COLUMNS}
                FROM community_comments_current
                WHERE publication_id = %s
                ORDER BY remote_comment_id COLLATE "C"
                LIMIT %s""",
            (publication_id, maximum_comments + 1),
        )
        rows = await cursor.fetchall()
        if len(rows) > maximum_comments:
            raise CommunityAnalysisError(
                "COMMENT_LIMIT_EXCEEDED", "comment snapshot exceeds configured limit",
            )
        return rows

    @staticmethod
    def _snapshot(run, comments, *, request) -> CommunityEvidenceSnapshot:
        return CommunityEvidenceSnapshot(
            publication_id=run[1], owner_user_id=run[2],
            platform=PublicationPlatform(run[3]), ingestion_sync_id=run[0],
            ingestion_target_fingerprint=run[4], ingestion_completed_at=run[6],
            comments=tuple(CommunityCommentEvidence(
                version_id=row[0], publication_id=row[1], remote_comment_id=row[2],
                comment_fingerprint=row[3], text=row[4], state=CommentState(row[5]),
                provider_updated_at=row[6],
            ) for row in comments),
        )

    @staticmethod
    async def _hydrate(connection, row, *, request) -> CommunityAnalysisReport:
        cursor = await connection.execute(
            """SELECT comment_version_id, remote_comment_id, comment_fingerprint,
                      theme, theme_rule_id, safety_category, safety_severity,
                      safety_rule_ids, requires_human_review,
                      classification_fingerprint
               FROM community_comment_classifications
               WHERE report_request_id = %s
               ORDER BY remote_comment_id COLLATE "C"
            """,
            (request.request_id,),
        )
        classifications = tuple(CommentClassification(
            comment_version_id=item[0], remote_comment_id=item[1],
            comment_fingerprint=item[2], theme=CommunityTheme(item[3]),
            theme_rule_id=item[4], safety_category=SafetyCategory(item[5]),
            safety_severity=SafetySeverity(item[6]),
            safety_rule_ids=tuple(item[7]), requires_human_review=item[8],
            classification_fingerprint=item[9],
        ) for item in await cursor.fetchall())
        cursor = await connection.execute(
            """SELECT theme, member_count, review_required_count,
                      classification_fingerprints, cluster_fingerprint
               FROM community_theme_clusters
               WHERE report_request_id = %s
               ORDER BY theme""",
            (request.request_id,),
        )
        clusters = tuple(ThemeCluster(
            theme=CommunityTheme(item[0]), member_count=item[1],
            review_required_count=item[2],
            classification_fingerprints=tuple(item[3]), cluster_fingerprint=item[4],
        ) for item in await cursor.fetchall())
        return CommunityAnalysisReport(
            request_id=row[0], owner_user_id=row[1], publication_id=row[2],
            request_fingerprint=row[3], ingestion_sync_id=row[4],
            ingestion_target_fingerprint=row[5], source_snapshot_fingerprint=row[6],
            theme_taxonomy_version=row[7], safety_policy_version=row[8],
            status=AnalysisStatus(row[9]), total_comment_count=row[10],
            analyzed_comment_count=row[11], deleted_comment_count=row[12],
            review_required_count=row[13], classifications=classifications,
            clusters=clusters, requested_at=row[15], created_at=row[16],
            report_fingerprint=row[17], outbound_action_authorized=row[18],
        )

    @staticmethod
    def _require_replay(
        stored: CommunityAnalysisReport, expected: CommunityAnalysisReport,
    ) -> CommunityAnalysisReport:
        if stored.report_fingerprint != expected.report_fingerprint or stored != expected:
            raise CommunityAnalysisConflict(
                "stored community analysis differs from exact replay"
            )
        return stored
