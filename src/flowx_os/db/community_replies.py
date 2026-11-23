"""Owner-scoped persistence for inert reply drafts and escalation records."""

from __future__ import annotations

from flowx_os.community.analysis import CommunityTheme, SafetyCategory, SafetySeverity
from flowx_os.community.comments import CommentState
from flowx_os.community.replies import (
    EscalationPriority,
    ReplyDisposition,
    ReplyDraftRecord,
    ReplyDraftRequest,
    ReplyDraftTarget,
)
from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work


class ReplyDraftNotFound(RuntimeError):
    """The owned current classification evidence is unavailable."""


class ReplyDraftConflict(RuntimeError):
    """An idempotency or current-evidence identity conflicts."""


_RECORD_COLUMNS = """request_id, owner_user_id, publication_id,
    analysis_request_id, comment_version_id, request_fingerprint,
    target_fingerprint, analysis_report_fingerprint, classification_fingerprint,
    policy_version, disposition, escalation_priority, escalation_reasons,
    draft_text, human_approval_required, outbound_action_authorized,
    created_at, record_fingerprint"""

_TARGET_SELECT = """SELECT r.owner_user_id, r.publication_id, r.request_id,
    r.report_fingerprint, c.comment_version_id, c.remote_comment_id,
    v.comment_fingerprint, v.state, c.theme, c.theme_rule_id,
    c.safety_category, c.safety_severity, c.safety_rule_ids,
    c.requires_human_review, c.classification_fingerprint
  FROM community_analysis_reports AS r
  JOIN community_comment_classifications AS c
    ON c.report_request_id = r.request_id
  JOIN community_comment_versions AS v ON v.id = c.comment_version_id
  JOIN publication_jobs AS p ON p.id = r.publication_id
  JOIN social_channels AS ch ON ch.id = p.channel_id
  JOIN brands AS b ON b.id = ch.brand_id
  JOIN community_comments_current AS current ON current.id = v.id
  WHERE r.request_id = %s AND r.publication_id = %s
    AND c.comment_version_id = %s AND b.owner_user_id = %s
    AND r.owner_user_id = b.owner_user_id
    AND c.classification_fingerprint = %s
    AND NOT EXISTS (
      SELECT 1 FROM community_analysis_reports AS newer
      WHERE newer.publication_id = r.publication_id
        AND (newer.created_at, newer.request_id::text) >
            (r.created_at, r.request_id::text)
    )"""


class ReplyDraftRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def get_existing(self, request: ReplyDraftRequest) -> ReplyDraftRecord | None:
        if not isinstance(request, ReplyDraftRequest):
            raise ValueError("reply draft request is required")
        try:
            async with unit_of_work(self._pool) as connection:
                row = await self._find_existing(connection, request)
                return None if row is None else self._record(row)
        except (ReplyDraftConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("reply draft storage is unavailable") from exc

    async def load_target(self, request: ReplyDraftRequest) -> ReplyDraftTarget:
        if not isinstance(request, ReplyDraftRequest):
            raise ValueError("reply draft request is required")
        try:
            async with unit_of_work(self._pool) as connection:
                row = await self._target_row(connection, request, lock_publication=False)
                if row is None:
                    raise ReplyDraftNotFound("current classified comment not found")
                return self._target(row)
        except (ReplyDraftNotFound, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("reply draft storage is unavailable") from exc

    async def persist(
        self, request: ReplyDraftRequest, target: ReplyDraftTarget,
        record: ReplyDraftRecord,
    ) -> ReplyDraftRecord:
        if (
            not isinstance(request, ReplyDraftRequest)
            or not isinstance(target, ReplyDraftTarget)
            or not isinstance(record, ReplyDraftRecord)
            or record.request_id != request.request_id
            or record.request_fingerprint != request.fingerprint
            or record.target_fingerprint != target.fingerprint
            or record.classification_fingerprint != target.classification_fingerprint
        ):
            raise ValueError("reply draft persistence identity is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find_existing(connection, request)
                if existing is not None:
                    return self._require_replay(self._record(existing), record)
                current_row = await self._target_row(
                    connection, request, lock_publication=True,
                )
                if current_row is None:
                    raise ReplyDraftNotFound("current classified comment not found")
                if self._target(current_row) != target:
                    raise ReplyDraftConflict("reply evidence changed before persistence")
                cursor = await connection.execute(
                    f"""INSERT INTO community_reply_draft_records
                      ({_RECORD_COLUMNS})
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING {_RECORD_COLUMNS}""",
                    (
                        record.request_id, record.owner_user_id,
                        record.publication_id, record.analysis_request_id,
                        record.comment_version_id, record.request_fingerprint,
                        record.target_fingerprint, record.analysis_report_fingerprint,
                        record.classification_fingerprint, record.policy_version,
                        record.disposition.value, record.escalation_priority.value,
                        list(record.escalation_reasons), record.draft_text,
                        record.human_approval_required,
                        record.outbound_action_authorized, record.created_at,
                        record.record_fingerprint,
                    ),
                )
                inserted = await cursor.fetchone()
                if inserted is not None:
                    return self._record(inserted)
                existing = await self._find_existing(connection, request)
                if existing is None:
                    raise ReplyDraftConflict(
                        "classification already has another draft identity"
                    )
                return self._require_replay(self._record(existing), record)
        except (ReplyDraftConflict, ReplyDraftNotFound, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("reply draft storage is unavailable") from exc

    @staticmethod
    async def _find_existing(connection, request):
        cursor = await connection.execute(
            f"""SELECT {_RECORD_COLUMNS}
                FROM community_reply_draft_records
                WHERE request_id = %s AND owner_user_id = %s""",
            (request.request_id, request.owner_user_id),
        )
        row = await cursor.fetchone()
        if row is not None and (
            row[2] != request.publication_id
            or row[3] != request.analysis_request_id
            or row[4] != request.comment_version_id
            or row[5] != request.fingerprint
            or row[8] != request.classification_fingerprint
            or row[9] != request.policy_version
            or row[16] != request.requested_at
        ):
            raise ReplyDraftConflict("reply draft request identifies different work")
        return row

    @staticmethod
    async def _target_row(connection, request, *, lock_publication: bool):
        if lock_publication:
            cursor = await connection.execute(
                """SELECT p.id FROM publication_jobs AS p
                   JOIN social_channels AS ch ON ch.id = p.channel_id
                   JOIN brands AS b ON b.id = ch.brand_id
                   WHERE p.id = %s AND b.owner_user_id = %s
                   FOR UPDATE OF p""",
                (request.publication_id, request.owner_user_id),
            )
            if await cursor.fetchone() is None:
                return None
        cursor = await connection.execute(
            _TARGET_SELECT + (" FOR SHARE OF r, c, v" if lock_publication else ""),
            (
                request.analysis_request_id, request.publication_id,
                request.comment_version_id, request.owner_user_id,
                request.classification_fingerprint,
            ),
        )
        return await cursor.fetchone()

    @staticmethod
    def _target(row) -> ReplyDraftTarget:
        return ReplyDraftTarget(
            owner_user_id=row[0], publication_id=row[1], analysis_request_id=row[2],
            analysis_report_fingerprint=row[3], comment_version_id=row[4],
            remote_comment_id=row[5], comment_fingerprint=row[6],
            comment_state=CommentState(row[7]), theme=CommunityTheme(row[8]),
            theme_rule_id=row[9], safety_category=SafetyCategory(row[10]),
            safety_severity=SafetySeverity(row[11]),
            safety_rule_ids=tuple(row[12]), requires_human_review=row[13],
            classification_fingerprint=row[14],
        )

    @staticmethod
    def _record(row) -> ReplyDraftRecord:
        return ReplyDraftRecord(
            request_id=row[0], owner_user_id=row[1], publication_id=row[2],
            analysis_request_id=row[3], comment_version_id=row[4],
            request_fingerprint=row[5], target_fingerprint=row[6],
            analysis_report_fingerprint=row[7], classification_fingerprint=row[8],
            policy_version=row[9], disposition=ReplyDisposition(row[10]),
            escalation_priority=EscalationPriority(row[11]),
            escalation_reasons=tuple(row[12]), draft_text=row[13],
            human_approval_required=row[14], outbound_action_authorized=row[15],
            created_at=row[16], record_fingerprint=row[17],
        )

    @staticmethod
    def _require_replay(stored, expected):
        if stored != expected or stored.record_fingerprint != expected.record_fingerprint:
            raise ReplyDraftConflict("stored reply draft differs from exact replay")
        return stored
