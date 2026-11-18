"""Typed interfaces for durable credit-risk alarms and fail-closed controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class CreditRiskError(RuntimeError):
    """Base class for safe unknown-spend alarm failures."""


class CreditRiskAlarmConflict(CreditRiskError):
    pass


class CreditRiskReservationUnavailable(CreditRiskError):
    pass


class UnknownSpendReason(StrEnum):
    SUBMISSION_OUTCOME_UNKNOWN = "SUBMISSION_OUTCOME_UNKNOWN"
    REMOTE_JOB_STATE_UNKNOWN = "REMOTE_JOB_STATE_UNKNOWN"
    ACTUAL_COST_UNKNOWN = "ACTUAL_COST_UNKNOWN"
    PROVIDER_RESPONSE_AMBIGUOUS = "PROVIDER_RESPONSE_AMBIGUOUS"


class CreditRiskAlarmState(StrEnum):
    OPEN = "OPEN"


SYSTEM_CREDIT_RISK_ACTOR = "system:credit-risk"


@dataclass(frozen=True, slots=True)
class CreditRiskAlarmRecord:
    id: UUID
    flow_account_id: UUID
    request_id: UUID
    alarm_type: str
    reason_code: UnknownSpendReason
    state: CreditRiskAlarmState
    created_at: datetime


class CreditRiskAlarmStore(Protocol):
    async def report_unknown_spend(
        self, *, account_id: UUID, owner_user_id: str,
        request_id: UUID, reason: UnknownSpendReason, actor: str,
    ) -> CreditRiskAlarmRecord: ...

    async def list_open_alarms(
        self, *, account_id: UUID, owner_user_id: str, limit: int,
    ) -> list[CreditRiskAlarmRecord]: ...


class CreditRiskAlarmService:
    """Keep ambiguous spend allocated and make its alarm owner-visible."""

    def __init__(self, store: CreditRiskAlarmStore):
        self._store = store

    async def report_unknown_spend(
        self, *, account_id: UUID, owner_user_id: str,
        request_id: UUID, reason: UnknownSpendReason, actor: str,
    ) -> CreditRiskAlarmRecord:
        if not isinstance(account_id, UUID) or not isinstance(request_id, UUID):
            raise ValueError("account and reservation request IDs must be UUIDs")
        if not isinstance(reason, UnknownSpendReason):
            raise ValueError("unknown-spend reason code is unsupported")
        if (
            not isinstance(actor, str)
            or not actor.strip()
            or len(actor) > 200
            or any(ord(char) < 32 or ord(char) == 127 for char in actor)
        ):
            raise ValueError("audit actor is invalid")
        return await self._store.report_unknown_spend(
            account_id=account_id, owner_user_id=owner_user_id,
            request_id=request_id, reason=reason, actor=actor.strip(),
        )

    async def list_open_alarms(
        self, *, account_id: UUID, owner_user_id: str, limit: int = 100,
    ) -> list[CreditRiskAlarmRecord]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("alarm page size must be between 1 and 200")
        return await self._store.list_open_alarms(
            account_id=account_id, owner_user_id=owner_user_id, limit=limit,
        )

