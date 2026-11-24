"""PostgreSQL persistence for inert community research proposals."""

from __future__ import annotations

from flowx_os.community.analysis import CommunityTheme, ThemeCluster
from flowx_os.community.insights import (
    CommunityInsightRecord, CommunityInsightRequest, CommunityInsightSource,
    ResearchPriority, ResearchProposal,
)
from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work


class CommunityInsightNotFound(RuntimeError):
    pass


class CommunityInsightConflict(RuntimeError):
    pass


_RECORD_COLUMNS = """request_id, owner_user_id, publication_id, request_fingerprint,
    policy_version, analysis_request_id, analysis_report_fingerprint,
    source_snapshot_fingerprint, insight_source_fingerprint, proposal_count,
    requested_at, created_at, record_fingerprint, external_browsing_authorized,
    model_execution_authorized, provider_action_authorized,
    account_action_authorized, publishing_authorized, spend_authorized,
    flow_authorized"""


class CommunityInsightRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def get_existing(self, request: CommunityInsightRequest) -> CommunityInsightRecord | None:
        if not isinstance(request, CommunityInsightRequest):
            raise ValueError("community insight request is required")
        try:
            async with unit_of_work(self._pool) as connection:
                row = await self._find(connection, request)
                return None if row is None else await self._hydrate(connection, row)
        except (CommunityInsightConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community insight storage is unavailable") from exc

    async def load_source(self, request: CommunityInsightRequest) -> CommunityInsightSource:
        if not isinstance(request, CommunityInsightRequest):
            raise ValueError("community insight request is required")
        try:
            async with unit_of_work(self._pool) as connection:
                return await self._load_source(connection, request, lock_publication=False)
        except (CommunityInsightNotFound, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community insight storage is unavailable") from exc

    async def persist(self, request: CommunityInsightRequest, source: CommunityInsightSource,
                      record: CommunityInsightRecord) -> CommunityInsightRecord:
        if (not isinstance(request, CommunityInsightRequest)
                or not isinstance(source, CommunityInsightSource)
                or not isinstance(record, CommunityInsightRecord)
                or record.request_id != request.request_id
                or record.request_fingerprint != request.fingerprint
                or record.insight_source_fingerprint != source.fingerprint
                or record.analysis_request_id != source.analysis_request_id):
            raise ValueError("community insight persistence identity is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find(connection, request)
                if existing is not None:
                    return self._require_replay(await self._hydrate(connection, existing), record)
                current = await self._load_source(connection, request, lock_publication=True)
                if current != source:
                    raise CommunityInsightConflict("community analysis changed during insight creation")
                cursor = await connection.execute(
                    f"""INSERT INTO community_insight_records ({_RECORD_COLUMNS})
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING RETURNING {_RECORD_COLUMNS}""",
                    (record.request_id, record.owner_user_id, record.publication_id,
                     record.request_fingerprint, record.policy_version,
                     record.analysis_request_id, record.analysis_report_fingerprint,
                     record.source_snapshot_fingerprint, record.insight_source_fingerprint,
                     len(record.proposals), record.requested_at, record.created_at,
                     record.record_fingerprint, record.external_browsing_authorized,
                     record.model_execution_authorized, record.provider_action_authorized,
                     record.account_action_authorized, record.publishing_authorized,
                     record.spend_authorized, record.flow_authorized),
                )
                if await cursor.fetchone() is None:
                    existing = await self._find(connection, request)
                    if existing is None:
                        raise CommunityInsightConflict("community insight source already has another identity")
                    return self._require_replay(await self._hydrate(connection, existing), record)
                for proposal in record.proposals:
                    cursor = await connection.execute(
                        """INSERT INTO community_research_proposals
                        (insight_request_id, theme, question_key, priority, member_count,
                         review_required_count, source_cluster_fingerprint,
                         proposal_fingerprint, requires_human_review,
                         research_execution_authorized)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING theme""",
                        (record.request_id, proposal.theme.value, proposal.question_key,
                         proposal.priority.value, proposal.member_count,
                         proposal.review_required_count, proposal.source_cluster_fingerprint,
                         proposal.proposal_fingerprint, proposal.requires_human_review,
                         proposal.research_execution_authorized),
                    )
                    if await cursor.fetchone() is None:
                        raise CommunityInsightConflict("research proposal could not be persisted")
                return record
        except (CommunityInsightConflict, CommunityInsightNotFound, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community insight storage is unavailable") from exc

    @staticmethod
    async def _find(connection, request):
        cursor = await connection.execute(
            f"SELECT {_RECORD_COLUMNS} FROM community_insight_records WHERE request_id=%s AND owner_user_id=%s",
            (request.request_id, request.owner_user_id),
        )
        row = await cursor.fetchone()
        if row is not None and (row[2] != request.publication_id or row[3] != request.fingerprint
                                or row[4] != request.policy_version or row[10] != request.requested_at):
            raise CommunityInsightConflict("community insight request identifies different work")
        return row

    @staticmethod
    async def _load_source(connection, request, *, lock_publication):
        if lock_publication:
            cursor = await connection.execute(
                """SELECT p.id FROM publication_jobs p
                   JOIN social_channels ch ON ch.id=p.channel_id
                   JOIN brands b ON b.id=ch.brand_id
                   WHERE p.id=%s AND b.owner_user_id=%s FOR UPDATE OF p""",
                (request.publication_id, request.owner_user_id),
            )
            if await cursor.fetchone() is None:
                raise CommunityInsightNotFound("owned publication not found")
        cursor = await connection.execute(
            """SELECT r.owner_user_id,r.publication_id,r.request_id,r.report_fingerprint,
                      r.source_snapshot_fingerprint,r.created_at,r.total_comment_count,
                      r.review_required_count
               FROM community_analysis_reports r
               JOIN publication_jobs p ON p.id=r.publication_id
               JOIN social_channels ch ON ch.id=p.channel_id
               JOIN brands b ON b.id=ch.brand_id
               WHERE r.publication_id=%s AND b.owner_user_id=%s
                 AND r.owner_user_id=b.owner_user_id AND r.outbound_action_authorized=false
               ORDER BY r.created_at DESC,r.request_id DESC LIMIT 1"""
            + (" FOR SHARE OF r" if lock_publication else ""),
            (request.publication_id, request.owner_user_id),
        )
        report = await cursor.fetchone()
        if report is None:
            raise CommunityInsightNotFound("community analysis report not found")
        cursor = await connection.execute(
            """SELECT theme,member_count,review_required_count,
                      classification_fingerprints,cluster_fingerprint
               FROM community_theme_clusters WHERE report_request_id=%s ORDER BY theme""",
            (report[2],),
        )
        clusters = tuple(ThemeCluster(CommunityTheme(row[0]), row[1], row[2],
                                      tuple(row[3]), row[4]) for row in await cursor.fetchall())
        return CommunityInsightSource(
            owner_user_id=report[0], publication_id=report[1], analysis_request_id=report[2],
            analysis_report_fingerprint=report[3], source_snapshot_fingerprint=report[4],
            analysis_created_at=report[5], total_comment_count=report[6],
            review_required_count=report[7], clusters=clusters,
        )

    @staticmethod
    async def _hydrate(connection, row):
        cursor = await connection.execute(
            """SELECT theme,question_key,priority,member_count,review_required_count,
                      source_cluster_fingerprint,proposal_fingerprint,
                      requires_human_review,research_execution_authorized
               FROM community_research_proposals WHERE insight_request_id=%s ORDER BY theme""",
            (row[0],),
        )
        proposals = tuple(ResearchProposal(
            CommunityTheme(item[0]), item[1], ResearchPriority(item[2]), item[3], item[4],
            item[5], item[6], item[7], item[8],
        ) for item in await cursor.fetchall())
        return CommunityInsightRecord(
            request_id=row[0], owner_user_id=row[1], publication_id=row[2],
            request_fingerprint=row[3], policy_version=row[4], analysis_request_id=row[5],
            analysis_report_fingerprint=row[6], source_snapshot_fingerprint=row[7],
            insight_source_fingerprint=row[8], proposals=proposals, requested_at=row[10],
            created_at=row[11], record_fingerprint=row[12],
            external_browsing_authorized=row[13], model_execution_authorized=row[14],
            provider_action_authorized=row[15], account_action_authorized=row[16],
            publishing_authorized=row[17], spend_authorized=row[18], flow_authorized=row[19],
        )

    @staticmethod
    def _require_replay(stored, expected):
        if stored != expected or stored.record_fingerprint != expected.record_fingerprint:
            raise CommunityInsightConflict("stored community insight differs from exact replay")
        return stored
