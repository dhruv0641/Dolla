"""Durable idempotent submission claims for Flow generation jobs."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from uuid import UUID
from datetime import datetime, timedelta, timezone

from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.db.credit_reservations import FlowCreditReservationRepository
from flowx_os.flow_mcp.jobs import JobSubmissionClaim, JobSubmissionRequest, PersistedJobResumeContext


_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class FlowGenerationJobRepository:
    """Persist one credit-reserved submission claim per canonical fingerprint."""

    def __init__(self, pool: ConnectionPool, *, max_quote_age: timedelta = timedelta(minutes=5),
                 max_balance_age: timedelta = timedelta(minutes=15), now=None):
        self._pool = pool
        if max_quote_age <= timedelta(0) or max_balance_age <= timedelta(0):
            raise ValueError("quote and balance freshness windows must be positive")
        self._max_quote_age = max_quote_age
        self._max_balance_age = max_balance_age
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def claim_or_get(
        self, *, account_ref: str, request: JobSubmissionRequest, fingerprint: str,
    ) -> JobSubmissionClaim:
        if (
            not isinstance(account_ref, str) or not account_ref.strip()
            or not isinstance(request, JobSubmissionRequest)
            or not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint)
            or isinstance(request.quoted_credits, bool)
            or not isinstance(request.quoted_credits, int) or request.quoted_credits <= 0
        ):
            raise ValueError("generation job claim is invalid")
        try:
            request_json = json.dumps({
                "model": request.model,
                "prompt": request.prompt,
                "request_id": str(request.request_id),
                "duration_seconds": request.duration_seconds,
                "settings": request.settings,
                "arguments": request.arguments,
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("generation job request is not canonical JSON") from exc

        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT reservation.id, account.id, reservation.quoted_credits,
                              reservation.quoted_at, reservation.quote_expires_at,
                              account.session_health, account.paused, account.compliance_approved,
                              account.observed_daily_available, account.observed_monthly_available,
                              account.last_reconciled_at, account.next_daily_reset_at,
                              account.monthly_cycle_starts_at, account.max_inflight
                       FROM flow_accounts AS account
                       JOIN flow_credit_reservations AS reservation
                         ON reservation.flow_account_id = account.id
                       JOIN scenes AS scene ON scene.id = %s
                       JOIN content_items AS content ON content.id = scene.content_id
                       JOIN brands AS brand ON brand.id = content.brand_id
                       WHERE account.alias = %s AND account.owner_user_id = %s
                         AND brand.owner_user_id = %s
                         AND reservation.request_id = %s
                         AND reservation.state = 'RESERVED'
                         AND reservation.model_name = %s
                         AND reservation.duration_seconds = %s
                       FOR UPDATE OF account, reservation, scene""",
                    (request.scene_id, account_ref, request.owner_user_id,
                     request.owner_user_id, request.request_id, request.model,
                     request.duration_seconds),
                )
                eligible = await cursor.fetchone()
                if eligible is None:
                    raise RepositoryUnavailable("matching owner-scoped credit reservation is unavailable")
                (reservation_id, account_id, quoted_credits, quoted_at, quote_expires_at,
                 health, paused, compliant, daily, monthly, reconciled, daily_reset,
                 cycle_start, max_inflight) = eligible
                decision_now = self._now()
                if (not isinstance(decision_now, datetime) or decision_now.tzinfo is None
                        or quoted_at is None or quoted_at.tzinfo is None
                        or quote_expires_at is None or quote_expires_at.tzinfo is None
                        or quote_expires_at <= decision_now
                        or quoted_at > decision_now
                        or quoted_at < decision_now - self._max_quote_age):
                    raise RepositoryUnavailable("generation quote is stale or invalid")
                FlowCreditReservationRepository._require_eligible_account(
                    (health, paused, compliant, daily, monthly, reconciled,
                     daily_reset, cycle_start, max_inflight),
                    now=decision_now, max_balance_age=self._max_balance_age,
                )
                cursor = await connection.execute(
                    """SELECT COUNT(*), COALESCE(SUM(quoted_credits), 0)
                       FROM flow_credit_reservations
                       WHERE flow_account_id = %s AND state IN ('RESERVED','RECONCILE_PENDING')""",
                    (account_id,),
                )
                active = await cursor.fetchone()
                if active is None:
                    raise RepositoryUnavailable("active credit reservation state is unavailable")
                active_count, active_credits = active
                if active_count > max_inflight or active_credits > daily or active_credits > monthly:
                    raise RepositoryUnavailable("current reservation no longer fits account health or credit limits")
                if quoted_credits != request.quoted_credits:
                    raise RepositoryUnavailable("generation quote differs from the reserved credit amount")

                cursor = await connection.execute(
                    """SELECT id, flow_account_id, scene_id, credit_reservation_id,
                              attempt_index, status, external_job_id
                       FROM generation_jobs WHERE idempotency_fingerprint = %s FOR UPDATE""",
                    (fingerprint,),
                )
                existing = await cursor.fetchone()
                if existing is not None:
                    job_id, existing_account, existing_scene, existing_reservation, existing_attempt, status, external_id = existing
                    if (existing_account != account_id or existing_scene != request.scene_id
                            or existing_reservation != reservation_id
                            or existing_attempt != request.attempt_index):
                        raise RepositoryUnavailable("generation idempotency fingerprint conflict")
                    return JobSubmissionClaim(job_id, str(status), external_id, False)

                cursor = await connection.execute(
                    """INSERT INTO generation_jobs
                         (scene_id, flow_account_id, credit_reservation_id, attempt_index,
                          idempotency_fingerprint, request_json, quoted_credits, status)
                       VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, 'RESERVED')
                       ON CONFLICT (idempotency_fingerprint) DO NOTHING
                       RETURNING id, status, external_job_id""",
                    (request.scene_id, account_id, reservation_id, request.attempt_index, fingerprint,
                     request_json, quoted_credits),
                )
                inserted = await cursor.fetchone()
                if inserted is not None:
                    return JobSubmissionClaim(inserted[0], str(inserted[1]), inserted[2], True)

                # A concurrent transaction won the unique insert after our initial read.
                cursor = await connection.execute(
                    """SELECT id, flow_account_id, scene_id, credit_reservation_id,
                              attempt_index, status, external_job_id
                       FROM generation_jobs WHERE idempotency_fingerprint = %s FOR UPDATE""",
                    (fingerprint,),
                )
                existing = await cursor.fetchone()
                if existing is None:
                    raise RepositoryUnavailable("idempotent generation claim disappeared")
                job_id, existing_account, existing_scene, existing_reservation, existing_attempt, status, external_id = existing
                if (existing_account != account_id or existing_scene != request.scene_id
                        or existing_reservation != reservation_id
                        or existing_attempt != request.attempt_index):
                    raise RepositoryUnavailable("generation idempotency fingerprint conflict")
                return JobSubmissionClaim(job_id, str(status), external_id, False)
        except RepositoryUnavailable:
            raise
        except Exception as exc:
            raise RepositoryUnavailable("generation job storage is unavailable") from exc

    async def mark_submitted(self, *, job_id: UUID, external_job_id: str) -> None:
        if (not isinstance(job_id, UUID) or not isinstance(external_job_id, str)
                or not external_job_id.strip() or len(external_job_id) > 300
                or any(ord(char) < 32 or ord(char) == 127 for char in external_job_id)):
            raise ValueError("external Flow job identity is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """UPDATE generation_jobs SET external_job_id = %s, status = 'SUBMITTED',
                              submitted_at = now()
                       WHERE id = %s AND status = 'RESERVED' AND external_job_id IS NULL""",
                    (external_job_id.strip(), job_id),
                )
                if cursor.rowcount != 1:
                    raise RepositoryUnavailable("generation job is not in a claimable state")
        except RepositoryUnavailable:
            raise
        except Exception as exc:
            raise RepositoryUnavailable("generation job storage is unavailable") from exc

    async def mark_remote_submission_unknown(self, *, job_id: UUID) -> None:
        if not isinstance(job_id, UUID):
            raise ValueError("job_id must be a UUID")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """UPDATE generation_jobs SET status = 'REMOTE_SUBMISSION_UNKNOWN',
                              error_code = 'SUBMISSION_OUTCOME_UNKNOWN'
                       WHERE id = %s AND status = 'RESERVED' AND external_job_id IS NULL""",
                    (job_id,),
                )
                if cursor.rowcount != 1:
                    raise RepositoryUnavailable("generation job is not in an unknownable state")
        except RepositoryUnavailable:
            raise
        except Exception as exc:
            raise RepositoryUnavailable("generation job storage is unavailable") from exc

    async def get_resume_context(self, *, job_id: UUID, account_ref: str,
                                 owner_user_id: str) -> PersistedJobResumeContext | None:
        if (not isinstance(job_id, UUID) or not isinstance(account_ref, str)
                or not account_ref.strip() or not isinstance(owner_user_id, str)
                or not owner_user_id.strip()):
            raise ValueError("job and account owner identity are required")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT job.external_job_id,
                              request_json->'arguments'->>'project_url',
                              request_json->'arguments'->>'prompt',
                              request_json->'arguments'->>'output_dir'
                       FROM generation_jobs AS job
                       JOIN flow_accounts AS account ON account.id = job.flow_account_id
                       WHERE job.id = %s AND account.alias = %s
                         AND account.owner_user_id = %s
                         AND job.status IN ('SUBMITTED','RUNNING','REMOTE_SUBMISSION_UNKNOWN')""",
                    (job_id, account_ref.strip(), owner_user_id.strip()),
                )
                row = await cursor.fetchone()
        except Exception as exc:
            raise RepositoryUnavailable("generation job storage is unavailable") from exc
        if row is None or any(not isinstance(value, str) or not value.strip() for value in row):
            return None
        return PersistedJobResumeContext(*(value.strip() for value in row))
