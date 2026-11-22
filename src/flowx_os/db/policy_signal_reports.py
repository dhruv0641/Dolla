"""Owner-scoped immutable persistence for policy/factuality/copyright signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from uuid import UUID

from flowx_os.db.content import OwnedContentNotFound, RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.qa.policy_signals import (
    ContentSignalReport,
    SignalFindingSeverity,
)


class PolicySignalReportConflict(RuntimeError):
    """An asset/version already identifies different signal evidence."""


@dataclass(frozen=True, slots=True)
class StoredPolicySignalReport:
    report_id: UUID
    report: ContentSignalReport
    created_at: datetime


class PolicySignalReportRepository:
    """Save one immutable `signals-v1` report per AV-passed active asset."""

    VERSION = "signals-v1"

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def create_or_get(
        self, *, report_id: UUID, brand_id: UUID, owner_user_id: str,
        report: ContentSignalReport,
    ) -> StoredPolicySignalReport:
        if (not isinstance(report_id, UUID) or not isinstance(brand_id, UUID)
                or not isinstance(owner_user_id, str) or not owner_user_id.strip()
                or len(owner_user_id.strip()) > 200
                or any(ord(character) < 32 or ord(character) == 127 for character in owner_user_id)
                or not isinstance(report, ContentSignalReport)):
            raise ValueError("owner-scoped policy signal report is invalid")
        checks_json = json.dumps(
            report.model_dump(mode="json"), sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
        blockers = [
            finding.code.value for finding in report.findings
            if finding.severity == SignalFindingSeverity.BLOCKER
        ]
        blockers_json = json.dumps(blockers, separators=(",", ":"))
        if len(checks_json.encode("utf-8")) > 131_072:
            raise ValueError("policy signal evidence exceeds its byte limit")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT 1 FROM assets AS a
                       JOIN content_items AS c ON c.id = a.content_id
                       JOIN brands AS b ON b.id = c.brand_id
                       JOIN qa_reports AS av
                         ON av.asset_id = a.id
                        AND av.version = 'av-v1'
                        AND av.decision = 'PASS'
                       WHERE a.id = %s AND a.content_id = %s AND b.id = %s
                         AND b.owner_user_id = %s AND a.retention_state = 'ACTIVE'
                         AND a.asset_kind IN ('FINAL_VIDEO', 'EXPORT_VARIANT')
                         AND a.scene_id IS NULL
                         AND av.checks->>'evidence_fingerprint' = %s
                       FOR KEY SHARE OF a, av""",
                    (report.asset_id, report.content_id, brand_id,
                     owner_user_id.strip(), report.av_evidence_fingerprint),
                )
                if await cursor.fetchone() is None:
                    raise OwnedContentNotFound("AV-passed policy signal asset not found")
                cursor = await connection.execute(
                    """INSERT INTO qa_reports
                         (id, content_id, scene_id, asset_id, version, score,
                          hard_blockers, checks, decision, reviewer_type)
                       VALUES (%s, %s, NULL, %s, %s, NULL, %s::jsonb, %s::jsonb, %s, 'AUTO')
                       ON CONFLICT (asset_id, version)
                         WHERE version = 'signals-v1' DO NOTHING
                       RETURNING id, checks, hard_blockers, decision,
                                 reviewer_type, created_at""",
                    (report_id, report.content_id, report.asset_id, self.VERSION,
                     blockers_json, checks_json, report.decision.value),
                )
                row = await cursor.fetchone()
                if row is None:
                    cursor = await connection.execute(
                        """SELECT q.id, q.checks, q.hard_blockers, q.decision,
                                  q.reviewer_type, q.created_at
                           FROM qa_reports AS q
                           JOIN assets AS a ON a.id = q.asset_id
                           JOIN content_items AS c ON c.id = a.content_id
                           JOIN brands AS b ON b.id = c.brand_id
                           WHERE q.asset_id = %s AND q.version = %s
                             AND q.content_id = %s AND b.id = %s
                             AND b.owner_user_id = %s
                           FOR UPDATE OF q""",
                        (report.asset_id, self.VERSION, report.content_id,
                         brand_id, owner_user_id.strip()),
                    )
                    row = await cursor.fetchone()
                    if row is None:
                        raise PolicySignalReportConflict("policy signal report is unavailable")
                stored = self._stored(row)
                if stored.report_id != report_id or stored.report != report:
                    raise PolicySignalReportConflict(
                        "policy signal report already contains different evidence"
                    )
                return stored
        except (OwnedContentNotFound, PolicySignalReportConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("policy signal report storage is unavailable") from exc

    @staticmethod
    def _stored(row: tuple[object, ...]) -> StoredPolicySignalReport:
        try:
            report_id, checks, blockers, decision, reviewer_type, created_at = row
            encoded = checks if isinstance(checks, str) else json.dumps(
                checks, sort_keys=True, separators=(",", ":"), allow_nan=False,
            )
            report = ContentSignalReport.model_validate_json(encoded)
            if isinstance(blockers, str):
                blockers = json.loads(blockers)
            expected_blockers = [
                finding.code.value for finding in report.findings
                if finding.severity == SignalFindingSeverity.BLOCKER
            ]
            if (not isinstance(report_id, UUID) or not isinstance(created_at, datetime)
                    or blockers != expected_blockers or decision != report.decision.value
                    or reviewer_type != "AUTO"):
                raise ValueError("stored policy signal envelope is invalid")
            return StoredPolicySignalReport(report_id, report, created_at)
        except Exception as exc:
            raise RepositoryUnavailable("stored policy signal report is invalid") from exc
