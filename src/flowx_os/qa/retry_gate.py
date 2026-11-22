"""Fail-closed approval and reservation gate for scene regeneration retries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import re
from typing import Protocol
from uuid import UUID

from flowx_os.credits.reservations import CreditReservationRecord, CreditReservationState
from flowx_os.flow_mcp.adapter import SpendAuthorizationVerifier
from flowx_os.flow_mcp.capabilities import FlowOperation
from flowx_os.domain.scene_jobs import SceneJobState


_SAFE_FAILURE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SAFE_APPROVAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class RetryGateReason(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    FAILURE_NOT_RETRYABLE = "FAILURE_NOT_RETRYABLE"
    ATTEMPT_LIMIT_EXHAUSTED = "ATTEMPT_LIMIT_EXHAUSTED"
    RESERVATION_UNAVAILABLE = "RESERVATION_UNAVAILABLE"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    APPROVAL_UNAVAILABLE = "APPROVAL_UNAVAILABLE"
    SPEND_STATE_INVALID = "SPEND_STATE_INVALID"


@dataclass(frozen=True, slots=True)
class RetrySpendEvidence:
    reservation_id: UUID
    account_id: UUID
    request_id: UUID
    quoted_credits: int
    quote_expires_at: datetime
    approval_fingerprint: str
    verified_at: datetime


@dataclass(frozen=True, slots=True)
class SceneRetryGateDecision:
    scene_id: UUID
    job_id: UUID
    attempt_index: int
    retry_count: int
    scene_state: SceneJobState
    retry_scheduled: bool
    reason: RetryGateReason
    retry_reservation_id: UUID | None
    approval_fingerprint: str | None


class RetryGateStore(Protocol):
    async def assert_failure_owned(
        self, *, job_id: UUID, owner_user_id: str,
    ) -> SceneRetryGateDecision | None: ...

    async def get_owned_retry_reservation(
        self, *, reservation_id: UUID, account_id: UUID, owner_user_id: str,
    ) -> CreditReservationRecord: ...

    async def record_failure_retry_gate(
        self, *, job_id: UUID, owner_user_id: str, retryable: bool,
        failure_code: str, spend_evidence: RetrySpendEvidence | None,
        denial_reason: RetryGateReason,
    ) -> SceneRetryGateDecision: ...


def retry_approval_fingerprint(
    *, reservation: CreditReservationRecord, approval_ref: str,
) -> str:
    if (not isinstance(reservation, CreditReservationRecord)
            or not isinstance(approval_ref, str)
            or not _SAFE_APPROVAL.fullmatch(approval_ref)):
        raise ValueError("retry approval evidence is invalid")
    payload = {
        "reservation_id": str(reservation.id),
        "account_id": str(reservation.flow_account_id),
        "request_id": str(reservation.request_id),
        "quoted_credits": reservation.quoted_credits,
        "approval_ref": approval_ref,
        "operation": FlowOperation.VIDEO_GENERATE.value,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SceneRetrySpendGateService:
    """Verify approval out of transaction, then persist one atomic gate decision.

    This service never submits or resumes a Flow job. A scheduled retry merely
    permits the existing submission path to claim the exact reserved request.
    """

    def __init__(
        self, store: RetryGateStore,
        spend_authorizer: SpendAuthorizationVerifier | None,
        *, now=None,
    ) -> None:
        self._store = store
        self._authorizer = spend_authorizer
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def record_failure(
        self, *, job_id: UUID, owner_user_id: str, retryable: bool,
        failure_code: str, reservation: CreditReservationRecord | None = None,
        approval_ref: str | None = None,
    ) -> SceneRetryGateDecision:
        if (not isinstance(job_id, UUID) or not isinstance(owner_user_id, str)
                or not owner_user_id.strip() or len(owner_user_id.strip()) > 200
                or any(ord(char) < 32 or ord(char) == 127 for char in owner_user_id)
                or not isinstance(retryable, bool)
                or not isinstance(failure_code, str)
                or not _SAFE_FAILURE.fullmatch(failure_code)):
            raise ValueError("scene retry gate request is invalid")
        owner = owner_user_id.strip()
        # Prove job ownership before disclosing any account/reservation identity
        # to an injected approval provider. The transactional record repeats it.
        existing = await self._store.assert_failure_owned(
            job_id=job_id, owner_user_id=owner,
        )
        if existing is not None:
            if not isinstance(existing, SceneRetryGateDecision):
                raise RuntimeError("retry gate store returned an invalid decision")
            return existing

        evidence = None
        reason = RetryGateReason.FAILURE_NOT_RETRYABLE
        if retryable:
            reason = RetryGateReason.RESERVATION_UNAVAILABLE
            if isinstance(reservation, CreditReservationRecord):
                observed_now = self._now()
                if (not isinstance(observed_now, datetime)
                        or observed_now.tzinfo is None or observed_now.utcoffset() is None
                        or not isinstance(reservation.id, UUID)
                        or not isinstance(reservation.flow_account_id, UUID)
                        or not isinstance(reservation.request_id, UUID)
                        or isinstance(reservation.quoted_credits, bool)
                        or not isinstance(reservation.quoted_credits, int)
                        or reservation.quoted_credits <= 0
                        or not isinstance(reservation.quote_expires_at, datetime)
                        or reservation.quote_expires_at.tzinfo is None
                        or reservation.quote_expires_at.utcoffset() is None
                        or reservation.quote_expires_at <= observed_now):
                    reason = RetryGateReason.SPEND_STATE_INVALID
                else:
                    trusted = await self._store.get_owned_retry_reservation(
                        reservation_id=reservation.id,
                        account_id=reservation.flow_account_id,
                        owner_user_id=owner,
                    )
                    if (not isinstance(trusted, CreditReservationRecord)
                            or trusted.id != reservation.id
                            or trusted.flow_account_id != reservation.flow_account_id
                            or not isinstance(trusted.request_id, UUID)
                            or not isinstance(trusted.quote_expires_at, datetime)
                            or trusted.quote_expires_at.tzinfo is None
                            or trusted.quote_expires_at.utcoffset() is None):
                        raise RuntimeError("retry gate store returned an invalid reservation")
                    reservation = trusted
                    if (reservation.state != CreditReservationState.RESERVED
                            or reservation.quote_expires_at <= observed_now
                            or isinstance(reservation.quoted_credits, bool)
                            or not isinstance(reservation.quoted_credits, int)
                            or reservation.quoted_credits <= 0):
                        reason = RetryGateReason.SPEND_STATE_INVALID
                    elif (not isinstance(approval_ref, str)
                          or not _SAFE_APPROVAL.fullmatch(approval_ref)):
                        reason = RetryGateReason.APPROVAL_REQUIRED
                    elif self._authorizer is None:
                        reason = RetryGateReason.APPROVAL_UNAVAILABLE
                    else:
                        try:
                            approved = await self._authorizer.is_authorized(
                                approval_ref=approval_ref,
                                account_ref=str(reservation.flow_account_id),
                                operation=FlowOperation.VIDEO_GENERATE,
                                max_allowed_credits=reservation.quoted_credits,
                            )
                        except Exception:
                            reason = RetryGateReason.APPROVAL_UNAVAILABLE
                        else:
                            if approved is not True:
                                reason = RetryGateReason.APPROVAL_REJECTED
                            else:
                                verified_at = self._now()
                                if (not isinstance(verified_at, datetime)
                                        or verified_at.tzinfo is None
                                        or verified_at.utcoffset() is None):
                                    reason = RetryGateReason.SPEND_STATE_INVALID
                                else:
                                    evidence = RetrySpendEvidence(
                                        reservation_id=reservation.id,
                                        account_id=reservation.flow_account_id,
                                        request_id=reservation.request_id,
                                        quoted_credits=reservation.quoted_credits,
                                        quote_expires_at=reservation.quote_expires_at,
                                        approval_fingerprint=retry_approval_fingerprint(
                                            reservation=reservation, approval_ref=approval_ref,
                                        ),
                                        verified_at=verified_at,
                                    )
                                    reason = RetryGateReason.ELIGIBLE
        return await self._store.record_failure_retry_gate(
            job_id=job_id, owner_user_id=owner, retryable=retryable,
            failure_code=failure_code, spend_evidence=evidence,
            denial_reason=reason,
        )
