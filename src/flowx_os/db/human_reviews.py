"""Owner-scoped, immutable persistence for human QA decisions."""

from __future__ import annotations

from datetime import datetime
import json
from uuid import UUID

from flowx_os.db.content import OwnedContentNotFound, RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.domain.content_state import ContentStatus
from flowx_os.qa.human_review import (
    HumanReviewDecision,
    HumanReviewRecord,
    HumanReviewRequest,
    HumanReviewRevisionTarget,
)


class HumanReviewConflict(RuntimeError):
    """The idempotency key or QA report already identifies another decision."""


class HumanReviewNotAllowed(RuntimeError):
    """The content or automated QA evidence cannot accept this decision."""


class HumanReviewRepository:
    """Record one human decision over one exact policy-signal report."""

    async def create_or_get(
        self, *, decision_id: UUID, brand_id: UUID, owner_user_id: str,
        request: HumanReviewRequest,
    ) -> HumanReviewRecord:
        if (not isinstance(decision_id, UUID) or not isinstance(brand_id, UUID)
                or not isinstance(owner_user_id, str)
                or not isinstance(request, HumanReviewRequest)
                or owner_user_id.strip() != request.reviewer_user_id):
            raise ValueError("owner-scoped human review is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT c.status
                       FROM content_items AS c
                       JOIN brands AS b ON b.id = c.brand_id
                       WHERE c.id = %s AND b.id = %s AND b.owner_user_id = %s
                       FOR UPDATE OF c""",
                    (request.content_id, brand_id, owner_user_id.strip()),
                )
                content = await cursor.fetchone()
                if content is None:
                    raise OwnedContentNotFound("content not found")

                existing = await self._find_existing(
                    connection, request_id=request.request_id,
                    brand_id=brand_id, owner_user_id=owner_user_id.strip(),
                )
                if existing is not None:
                    record = self._record(existing)
                    if record.decision_id != decision_id or record.request != request:
                        raise HumanReviewConflict(
                            "human review request already contains a different decision"
                        )
                    return record
                if content[0] != ContentStatus.NEEDS_REVIEW.value:
                    raise HumanReviewNotAllowed("content is not awaiting human review")

                cursor = await connection.execute(
                    """SELECT a.asset_kind, a.retention_state, q.version, q.decision,
                              q.reviewer_type, q.hard_blockers, q.checks
                       FROM assets AS a
                       JOIN qa_reports AS q
                         ON q.id = %s AND q.asset_id = a.id AND q.content_id = a.content_id
                       WHERE a.id = %s AND a.content_id = %s AND a.scene_id IS NULL
                       FOR KEY SHARE OF a, q""",
                    (request.qa_report_id, request.asset_id, request.content_id),
                )
                evidence = await cursor.fetchone()
                if evidence is None:
                    raise HumanReviewNotAllowed("exact human-review evidence is unavailable")
                (asset_kind, retention_state, version, qa_decision,
                 reviewer_type, blockers, checks) = evidence
                blockers_value = json.loads(blockers) if isinstance(blockers, str) else blockers
                checks_value = json.loads(checks) if isinstance(checks, str) else checks
                evidence_valid = bool(
                    asset_kind in {"FINAL_VIDEO", "EXPORT_VARIANT"}
                    and retention_state == "ACTIVE"
                    and version == "signals-v1"
                    and qa_decision in {"PASS", "NEEDS_HUMAN", "FAIL"}
                    and reviewer_type == "AUTO"
                    and isinstance(blockers_value, list)
                    and isinstance(checks_value, dict)
                    and checks_value.get("human_approval_required") is True
                    and checks_value.get("content_approved") is False
                )
                if not evidence_valid:
                    raise HumanReviewNotAllowed("human-review evidence is invalid")
                if (request.decision == HumanReviewDecision.APPROVE
                        and (qa_decision == "FAIL" or blockers_value)):
                    raise HumanReviewNotAllowed("blocked automated QA cannot be approved")

                cursor = await connection.execute(
                    """SELECT 1 FROM review_decisions
                       WHERE qa_report_id = %s AND request_id IS NOT NULL""",
                    (request.qa_report_id,),
                )
                if await cursor.fetchone() is not None:
                    raise HumanReviewConflict("QA evidence already has a human decision")

                cursor = await connection.execute(
                    """INSERT INTO review_decisions
                         (id, request_id, request_fingerprint, content_id, asset_id,
                          qa_report_id, reviewer_user_id, decision, reason,
                          approval_scope, revision_target)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                               'FINAL_VIDEO', %s)
                       ON CONFLICT (request_id) WHERE request_id IS NOT NULL DO NOTHING
                       RETURNING id, request_id, request_fingerprint, content_id,
                                 asset_id, qa_report_id, reviewer_user_id, decision,
                                 reason, revision_target, created_at""",
                    (
                        decision_id, request.request_id, request.fingerprint,
                        request.content_id, request.asset_id, request.qa_report_id,
                        request.reviewer_user_id, request.decision.value, request.reason,
                        request.revision_target.value if request.revision_target else None,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    row = await self._find_existing(
                        connection, request_id=request.request_id,
                        brand_id=brand_id, owner_user_id=owner_user_id.strip(),
                    )
                    if row is None:
                        raise HumanReviewConflict("human review request is unavailable")
                record = self._record(row)
                if record.decision_id != decision_id or record.request != request:
                    raise HumanReviewConflict(
                        "human review request already contains a different decision"
                    )
                return record
        except (OwnedContentNotFound, HumanReviewConflict, HumanReviewNotAllowed,
                RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("human review storage is unavailable") from exc

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    @staticmethod
    async def _find_existing(
        connection, *, request_id: UUID, brand_id: UUID, owner_user_id: str,
    ):
        cursor = await connection.execute(
            """SELECT r.id, r.request_id, r.request_fingerprint, r.content_id,
                      r.asset_id, r.qa_report_id, r.reviewer_user_id, r.decision,
                      r.reason, r.revision_target, r.created_at
               FROM review_decisions AS r
               JOIN content_items AS c ON c.id = r.content_id
               JOIN brands AS b ON b.id = c.brand_id
               WHERE r.request_id = %s AND b.id = %s AND b.owner_user_id = %s
               FOR UPDATE OF r""",
            (request_id, brand_id, owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    def _record(row) -> HumanReviewRecord:
        try:
            (decision_id, request_id, fingerprint, content_id, asset_id,
             qa_report_id, reviewer, raw_decision, reason,
             raw_revision, created_at) = row
            request = HumanReviewRequest(
                request_id=request_id, content_id=content_id, asset_id=asset_id,
                qa_report_id=qa_report_id, reviewer_user_id=reviewer,
                decision=HumanReviewDecision(raw_decision), reason=reason,
                revision_target=(HumanReviewRevisionTarget(raw_revision)
                                 if raw_revision is not None else None),
            )
            if (not isinstance(decision_id, UUID) or fingerprint != request.fingerprint
                    or not isinstance(created_at, datetime)):
                raise ValueError("stored human review envelope is invalid")
            return HumanReviewRecord(
                decision_id=decision_id, request=request,
                next_status=request.next_status, created_at=created_at,
            )
        except Exception as exc:
            raise RepositoryUnavailable("stored human review decision is invalid") from exc

