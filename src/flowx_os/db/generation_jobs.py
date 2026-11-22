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
from flowx_os.domain.scene_jobs import (
    SceneJobState,
    SceneRetryPolicy,
)
from flowx_os.qa.retry_gate import (
    RetryGateReason,
    RetrySpendEvidence,
    SceneRetryGateDecision,
)


_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_SAFE_FAILURE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class FlowGenerationJobRepository:
    """Persist one credit-reserved submission claim per canonical fingerprint."""

    def __init__(self, pool: ConnectionPool, *, max_quote_age: timedelta = timedelta(minutes=5),
                 max_balance_age: timedelta = timedelta(minutes=15),
                 max_approval_age: timedelta = timedelta(minutes=5), now=None,
                 retry_policy: SceneRetryPolicy | None = None):
        self._pool = pool
        if (max_quote_age <= timedelta(0) or max_balance_age <= timedelta(0)
                or max_approval_age <= timedelta(0)):
            raise ValueError("quote, balance and approval freshness windows must be positive")
        self._max_quote_age = max_quote_age
        self._max_balance_age = max_balance_age
        self._max_approval_age = max_approval_age
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._retry_policy = retry_policy or SceneRetryPolicy()
        if not isinstance(self._retry_policy, SceneRetryPolicy):
            raise ValueError("retry_policy must be a SceneRetryPolicy")

    async def claim_or_get(
        self, *, account_ref: str, request: JobSubmissionRequest, fingerprint: str,
    ) -> JobSubmissionClaim:
        if (
            not isinstance(account_ref, str) or not account_ref.strip()
            or not isinstance(request, JobSubmissionRequest)
            or not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint)
            or isinstance(request.attempt_index, bool)
            or not isinstance(request.attempt_index, int) or request.attempt_index < 1
            or isinstance(request.quoted_credits, bool)
            or not isinstance(request.quoted_credits, int) or request.quoted_credits <= 0
        ):
            raise ValueError("generation job claim is invalid")
        self._retry_policy.require_index(request.attempt_index)
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
                              account.monthly_cycle_starts_at, account.max_inflight,
                              scene.state, scene.retry_count
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
                 cycle_start, max_inflight, scene_state, scene_retry_count) = eligible
                if request.attempt_index > self._retry_policy.max_attempts:
                    raise RepositoryUnavailable("scene regeneration limit is exhausted")
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

                try:
                    self._retry_policy.require_attempt(
                        attempt_index=request.attempt_index,
                        state=scene_state,
                        retry_count=scene_retry_count,
                    )
                except (ValueError, TypeError) as exc:
                    raise RepositoryUnavailable("scene state does not permit this generation attempt") from exc

                if request.attempt_index > 1:
                    cursor = await connection.execute(
                        """SELECT status, retry_scheduled, retry_gate_decision,
                                  retry_credit_reservation_id, retry_max_attempts
                           FROM generation_jobs
                           WHERE scene_id = %s AND attempt_index = %s FOR UPDATE""",
                        (request.scene_id, request.attempt_index - 1),
                    )
                    prior = await cursor.fetchone()
                    if (not isinstance(prior, tuple) or len(prior) != 5
                            or prior[0] != "FAILED" or prior[1] is not True
                            or prior[2] != "ALLOW" or prior[3] != reservation_id
                            or isinstance(prior[4], bool) or not isinstance(prior[4], int)
                            or request.attempt_index > prior[4]):
                        raise RepositoryUnavailable(
                            "scene retry claim lacks an exact eligible retry-gate reservation"
                        )

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

    async def _lock_attempt(self, connection, job_id: UUID):
        cursor = await connection.execute(
            """SELECT j.status, j.attempt_index, s.id, s.state, s.retry_count,
                      j.retry_scheduled
               FROM generation_jobs AS j JOIN scenes AS s ON s.id = j.scene_id
               WHERE j.id = %s FOR UPDATE OF j, s""",
            (job_id,),
        )
        return await cursor.fetchone()

    async def mark_submitted(self, *, job_id: UUID, external_job_id: str) -> None:
        if (not isinstance(job_id, UUID) or not isinstance(external_job_id, str)
                or not external_job_id.strip() or len(external_job_id) > 300
                or any(ord(char) < 32 or ord(char) == 127 for char in external_job_id)):
            raise ValueError("external Flow job identity is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                attempt = await self._lock_attempt(connection, job_id)
                if attempt is None:
                    raise RepositoryUnavailable("generation job is unavailable")
                status, attempt_index, scene_id, scene_state, retry_count, retry_scheduled = attempt
                if status != "RESERVED" or retry_scheduled:
                    raise RepositoryUnavailable("generation job is not in a claimable state")
                try:
                    self._retry_policy.require_attempt(
                        attempt_index=attempt_index, state=scene_state, retry_count=retry_count,
                    )
                except ValueError as exc:
                    raise RepositoryUnavailable("scene state does not permit submission") from exc
                cursor = await connection.execute(
                    """UPDATE generation_jobs SET external_job_id = %s, status = 'SUBMITTED',
                              submitted_at = now()
                       WHERE id = %s AND status = 'RESERVED' AND external_job_id IS NULL""",
                    (external_job_id.strip(), job_id),
                )
                if cursor.rowcount != 1:
                    raise RepositoryUnavailable("generation job is not in a claimable state")
                cursor = await connection.execute(
                    """UPDATE scenes SET state = 'SUBMITTED', updated_at = now()
                       WHERE id = %s AND state = %s AND retry_count = %s""",
                    (scene_id, scene_state, retry_count),
                )
                if cursor.rowcount != 1:
                    raise RepositoryUnavailable("scene changed before submission was recorded")
        except RepositoryUnavailable:
            raise
        except Exception as exc:
            raise RepositoryUnavailable("generation job storage is unavailable") from exc

    async def mark_remote_submission_unknown(self, *, job_id: UUID) -> None:
        if not isinstance(job_id, UUID):
            raise ValueError("job_id must be a UUID")
        try:
            async with unit_of_work(self._pool) as connection:
                attempt = await self._lock_attempt(connection, job_id)
                if attempt is None:
                    raise RepositoryUnavailable("generation job is unavailable")
                status, attempt_index, scene_id, scene_state, retry_count, retry_scheduled = attempt
                if status != "RESERVED" or retry_scheduled:
                    raise RepositoryUnavailable("generation job is not in an unknownable state")
                try:
                    self._retry_policy.require_attempt(
                        attempt_index=attempt_index, state=scene_state, retry_count=retry_count,
                    )
                except ValueError as exc:
                    raise RepositoryUnavailable("scene state does not permit unknown submission") from exc
                cursor = await connection.execute(
                    """UPDATE generation_jobs SET status = 'REMOTE_SUBMISSION_UNKNOWN',
                              error_code = 'SUBMISSION_OUTCOME_UNKNOWN'
                       WHERE id = %s AND status = 'RESERVED' AND external_job_id IS NULL""",
                    (job_id,),
                )
                if cursor.rowcount != 1:
                    raise RepositoryUnavailable("generation job is not in an unknownable state")
                cursor = await connection.execute(
                    """UPDATE scenes SET state = 'BLOCKED', updated_at = now()
                       WHERE id = %s AND state = %s AND retry_count = %s""",
                    (scene_id, scene_state, retry_count),
                )
                if cursor.rowcount != 1:
                    raise RepositoryUnavailable("scene changed while submission outcome was unknown")
        except RepositoryUnavailable:
            raise
        except Exception as exc:
            raise RepositoryUnavailable("generation job storage is unavailable") from exc

    async def assert_failure_owned(
        self, *, job_id: UUID, owner_user_id: str,
    ) -> SceneRetryGateDecision | None:
        """Reject foreign jobs before approval-provider calls expose spend identity."""
        if (not isinstance(job_id, UUID) or not isinstance(owner_user_id, str)
                or not owner_user_id.strip() or len(owner_user_id.strip()) > 200):
            raise ValueError("owner-scoped generation failure is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT j.status, j.attempt_index, s.id, j.retry_scheduled,
                              j.retry_gate_decision, j.retry_gate_reason,
                              j.retry_credit_reservation_id,
                              j.retry_approval_fingerprint, j.retry_max_attempts
                       FROM generation_jobs AS j
                       JOIN scenes AS s ON s.id = j.scene_id
                       JOIN content_items AS c ON c.id = s.content_id
                       JOIN brands AS b ON b.id = c.brand_id
                       WHERE j.id = %s AND b.owner_user_id = %s""",
                    (job_id, owner_user_id.strip()),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RepositoryUnavailable("owner-scoped generation job is unavailable")
                (status, attempt_index, scene_id, retry_scheduled, gate_decision,
                 gate_reason, gate_reservation, gate_fingerprint,
                 stored_max_attempts) = row
                if status != "FAILED":
                    return None
                if gate_decision not in {"ALLOW", "DENY"}:
                    raise RepositoryUnavailable("failed generation job lacks retry-gate evidence")
                try:
                    reason = RetryGateReason(gate_reason)
                except (TypeError, ValueError) as exc:
                    raise RepositoryUnavailable("stored retry-gate reason is invalid") from exc
                if (isinstance(attempt_index, bool) or not isinstance(attempt_index, int)
                        or attempt_index < 1 or isinstance(stored_max_attempts, bool)
                        or not isinstance(stored_max_attempts, int)
                        or not 1 <= stored_max_attempts <= 11):
                    raise RepositoryUnavailable("stored retry-gate attempt policy is invalid")
                return SceneRetryGateDecision(
                    scene_id, job_id, attempt_index,
                    attempt_index if retry_scheduled else attempt_index - 1,
                    SceneJobState.RETRY_WAIT if retry_scheduled else SceneJobState.FAILED,
                    bool(retry_scheduled), reason, gate_reservation, gate_fingerprint,
                )
        except RepositoryUnavailable:
            raise
        except Exception as exc:
            raise RepositoryUnavailable("generation job storage is unavailable") from exc

    async def get_owned_retry_reservation(
        self, *, reservation_id: UUID, account_id: UUID, owner_user_id: str,
    ):
        """Return only a repository-sourced reservation owned by the job owner."""
        if (not isinstance(reservation_id, UUID) or not isinstance(account_id, UUID)
                or not isinstance(owner_user_id, str) or not owner_user_id.strip()
                or len(owner_user_id.strip()) > 200
                or any(ord(char) < 32 or ord(char) == 127 for char in owner_user_id)):
            raise ValueError("owner-scoped retry reservation identity is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT r.id, r.flow_account_id, r.request_id, r.model_name,
                              r.duration_seconds, r.quote_ref, r.quoted_credits,
                              r.quote_source, r.quoted_at, r.quote_expires_at,
                              r.state, r.created_at
                       FROM flow_credit_reservations AS r
                       JOIN flow_accounts AS a ON a.id = r.flow_account_id
                       WHERE r.id = %s AND r.flow_account_id = %s
                         AND a.owner_user_id = %s""",
                    (reservation_id, account_id, owner_user_id.strip()),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RepositoryUnavailable("owner-scoped retry reservation is unavailable")
                return FlowCreditReservationRepository._to_record(row)
        except RepositoryUnavailable:
            raise
        except Exception as exc:
            raise RepositoryUnavailable("credit reservation storage is unavailable") from exc

    async def record_failure_retry_gate(
        self, *, job_id: UUID, owner_user_id: str, retryable: bool,
        failure_code: str, spend_evidence: RetrySpendEvidence | None,
        denial_reason: RetryGateReason,
    ) -> SceneRetryGateDecision:
        """Record one immutable failure/retry decision under account and scene locks."""
        if (not isinstance(job_id, UUID) or not isinstance(owner_user_id, str)
                or not owner_user_id.strip() or len(owner_user_id.strip()) > 200
                or any(ord(char) < 32 or ord(char) == 127 for char in owner_user_id)
                or not isinstance(retryable, bool)
                or not isinstance(failure_code, str)
                or not _SAFE_FAILURE_CODE.fullmatch(failure_code)
                or not isinstance(denial_reason, RetryGateReason)
                or (spend_evidence is None) != (denial_reason != RetryGateReason.ELIGIBLE)):
            raise ValueError("generation retry gate record is invalid")
        try:
            decision_now = self._now()
            if (not isinstance(decision_now, datetime) or decision_now.tzinfo is None
                    or decision_now.utcoffset() is None):
                raise RepositoryUnavailable("retry decision time is invalid")
            evidence_is_well_formed = bool(
                spend_evidence is not None
                and isinstance(spend_evidence.reservation_id, UUID)
                and isinstance(spend_evidence.account_id, UUID)
                and isinstance(spend_evidence.request_id, UUID)
                and not isinstance(spend_evidence.quoted_credits, bool)
                and isinstance(spend_evidence.quoted_credits, int)
                and spend_evidence.quoted_credits > 0
                and isinstance(spend_evidence.quote_expires_at, datetime)
                and spend_evidence.quote_expires_at.tzinfo is not None
                and spend_evidence.quote_expires_at.utcoffset() is not None
                and isinstance(spend_evidence.verified_at, datetime)
                and spend_evidence.verified_at.tzinfo is not None
                and spend_evidence.verified_at.utcoffset() is not None
                and spend_evidence.verified_at <= decision_now
                and spend_evidence.verified_at >= decision_now - self._max_approval_age
                and isinstance(spend_evidence.approval_fingerprint, str)
                and bool(_FINGERPRINT.fullmatch(spend_evidence.approval_fingerprint))
            )
            async with unit_of_work(self._pool) as connection:
                # Match the credit subsystem's global lock order.  The job and
                # scene are deliberately locked only after account -> reservation.
                locked_account = None
                locked_reservation = None
                if evidence_is_well_formed:
                    assert spend_evidence is not None
                    cursor = await connection.execute(
                        """SELECT session_health, paused, compliance_approved,
                                  observed_daily_available, observed_monthly_available,
                                  last_reconciled_at, next_daily_reset_at,
                                  monthly_cycle_starts_at, max_inflight
                           FROM flow_accounts
                           WHERE id = %s AND owner_user_id = %s FOR UPDATE""",
                        (spend_evidence.account_id, owner_user_id.strip()),
                    )
                    locked_account = await cursor.fetchone()
                    if locked_account is not None:
                        cursor = await connection.execute(
                            """SELECT id, flow_account_id, request_id, quoted_credits,
                                      quoted_at, quote_expires_at, state
                               FROM flow_credit_reservations
                               WHERE id = %s AND flow_account_id = %s FOR UPDATE""",
                            (spend_evidence.reservation_id, spend_evidence.account_id),
                        )
                        locked_reservation = await cursor.fetchone()
                cursor = await connection.execute(
                    """SELECT j.status, j.attempt_index, s.id, s.state, s.retry_count,
                              j.retry_scheduled, j.retry_gate_decision,
                              j.retry_gate_reason, j.retry_credit_reservation_id,
                              j.retry_approval_fingerprint, j.credit_reservation_id,
                              j.retry_max_attempts
                       FROM generation_jobs AS j
                       JOIN scenes AS s ON s.id = j.scene_id
                       JOIN content_items AS c ON c.id = s.content_id
                       JOIN brands AS b ON b.id = c.brand_id
                       WHERE j.id = %s AND b.owner_user_id = %s
                       FOR UPDATE OF j, s""",
                    (job_id, owner_user_id.strip()),
                )
                attempt = await cursor.fetchone()
                if attempt is None:
                    raise RepositoryUnavailable("owner-scoped generation job is unavailable")
                (status, attempt_index, scene_id, scene_state, retry_count,
                 retry_scheduled, gate_decision, gate_reason, gate_reservation,
                 gate_fingerprint, current_reservation, stored_max_attempts) = attempt
                try:
                    typed_scene_state = SceneJobState(scene_state)
                except (ValueError, TypeError) as exc:
                    raise RepositoryUnavailable("stored scene state is invalid") from exc
                if status == "FAILED":
                    if gate_decision not in {"ALLOW", "DENY"}:
                        raise RepositoryUnavailable("failed generation job lacks retry-gate evidence")
                    try:
                        stored_reason = RetryGateReason(gate_reason)
                    except (TypeError, ValueError) as exc:
                        raise RepositoryUnavailable("stored retry-gate reason is invalid") from exc
                    if (isinstance(stored_max_attempts, bool)
                            or not isinstance(stored_max_attempts, int)
                            or not 1 <= stored_max_attempts <= 11):
                        raise RepositoryUnavailable("stored retry-gate attempt policy is invalid")
                    return SceneRetryGateDecision(
                        scene_id, job_id, attempt_index,
                        attempt_index if retry_scheduled else attempt_index - 1,
                        SceneJobState.RETRY_WAIT if retry_scheduled else SceneJobState.FAILED,
                        bool(retry_scheduled), stored_reason,
                        gate_reservation, gate_fingerprint,
                    )
                if status not in {"SUBMITTED", "RUNNING", "DOWNLOADED", "QA_FAILED"}:
                    raise RepositoryUnavailable("generation job is not in a definitive failure state")
                if (typed_scene_state not in {
                        SceneJobState.SUBMITTED, SceneJobState.RUNNING,
                        SceneJobState.DOWNLOADED, SceneJobState.QA_FAILED,
                    } or retry_count != attempt_index - 1):
                    raise RepositoryUnavailable("scene state does not match the failed attempt")
                should_retry = False
                reason = denial_reason
                valid_spend = False
                if not retryable:
                    reason = RetryGateReason.FAILURE_NOT_RETRYABLE
                elif attempt_index >= self._retry_policy.max_attempts:
                    reason = RetryGateReason.ATTEMPT_LIMIT_EXHAUSTED
                elif spend_evidence is not None:
                    evidence = spend_evidence
                    if not evidence_is_well_formed:
                        reason = RetryGateReason.SPEND_STATE_INVALID
                    elif (isinstance(locked_account, tuple) and len(locked_account) == 9
                          and isinstance(locked_reservation, tuple)
                          and len(locked_reservation) == 7):
                        (health, paused, compliant, daily, monthly, reconciled,
                         daily_reset, cycle_start, max_inflight) = locked_account
                        (reservation_id, account_id, request_id, quoted_credits,
                         quoted_at, quote_expires_at, reservation_state) = locked_reservation
                        cursor = await connection.execute(
                            """SELECT COUNT(*), COALESCE(SUM(quoted_credits), 0)
                               FROM flow_credit_reservations
                               WHERE flow_account_id = %s
                                 AND state IN ('RESERVED','RECONCILE_PENDING')""",
                            (account_id,),
                        )
                        active = await cursor.fetchone()
                        cursor = await connection.execute(
                            """SELECT 1 FROM generation_jobs
                               WHERE credit_reservation_id = %s
                                  OR retry_credit_reservation_id = %s""",
                            (reservation_id, reservation_id),
                        )
                        used = await cursor.fetchone()
                        try:
                            FlowCreditReservationRepository._require_eligible_account(
                                (health, paused, compliant, daily, monthly, reconciled,
                                 daily_reset, cycle_start, max_inflight),
                                now=decision_now,
                                max_balance_age=self._max_balance_age,
                            )
                        except Exception:
                            eligible_account = False
                        else:
                            eligible_account = True
                        active_valid = bool(
                            isinstance(active, tuple) and len(active) == 2
                            and not isinstance(active[0], bool) and isinstance(active[0], int)
                            and not isinstance(active[1], bool) and isinstance(active[1], int)
                            and active[0] >= 0 and active[1] >= 0
                        )
                        valid_spend = bool(
                            reservation_id == evidence.reservation_id
                            and account_id == evidence.account_id
                            and request_id == evidence.request_id
                            and quoted_credits == evidence.quoted_credits
                            and quote_expires_at == evidence.quote_expires_at
                            and reservation_state == "RESERVED"
                            and reservation_id != current_reservation
                            and quote_expires_at is not None
                            and quote_expires_at.tzinfo is not None
                            and quote_expires_at > decision_now
                            and quoted_at is not None and quoted_at.tzinfo is not None
                            and quoted_at <= decision_now
                            and quoted_at >= decision_now - self._max_quote_age
                            and eligible_account
                            and active_valid
                            and active[0] <= max_inflight
                            and active[1] <= daily and active[1] <= monthly
                            and used is None
                        )
                        if valid_spend:
                            should_retry = True
                            reason = RetryGateReason.ELIGIBLE
                        else:
                            reason = RetryGateReason.SPEND_STATE_INVALID
                next_state = SceneJobState.RETRY_WAIT if should_retry else SceneJobState.FAILED
                next_retry_count = retry_count + 1 if should_retry else retry_count
                cursor = await connection.execute(
                    """UPDATE generation_jobs SET status = 'FAILED', error_code = %s,
                              retry_scheduled = %s, retry_gate_decision = %s,
                              retry_gate_reason = %s, retry_credit_reservation_id = %s,
                              retry_approval_fingerprint = %s,
                              retry_max_attempts = %s, retry_decided_at = %s,
                              completed_at = now()
                       WHERE id = %s AND status = %s AND retry_scheduled = false""",
                    (failure_code, should_retry, "ALLOW" if should_retry else "DENY",
                     reason.value,
                     spend_evidence.reservation_id if should_retry else None,
                     spend_evidence.approval_fingerprint if should_retry else None,
                     self._retry_policy.max_attempts, decision_now, job_id, status),
                )
                if cursor.rowcount != 1:
                    raise RepositoryUnavailable("generation job changed while failure was recorded")
                cursor = await connection.execute(
                    """UPDATE scenes SET state = %s, retry_count = %s, updated_at = now()
                       WHERE id = %s AND state = %s AND retry_count = %s""",
                    (next_state.value, next_retry_count, scene_id, typed_scene_state.value, retry_count),
                )
                if cursor.rowcount != 1:
                    raise RepositoryUnavailable("scene changed while retry decision was recorded")
                return SceneRetryGateDecision(
                    scene_id, job_id, attempt_index, next_retry_count, next_state, should_retry,
                    reason,
                    spend_evidence.reservation_id if should_retry else None,
                    spend_evidence.approval_fingerprint if should_retry else None,
                )
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
