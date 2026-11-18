"""Typed, fail-closed contracts for observed Flow credit reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

class CreditLedgerError(RuntimeError):
    """Base class for stable credit-ledger failures."""


class CreditObservationUnavailable(CreditLedgerError):
    pass


class InvalidCreditObservation(CreditLedgerError):
    pass


class CreditReconciliationConflict(CreditLedgerError):
    pass


@dataclass(frozen=True, slots=True)
class CreditBalanceObservation:
    """A provider observation bound to one local account and request."""

    account_ref: str
    request_id: UUID
    daily_available: int
    monthly_available: int
    observed_at: datetime
    next_daily_reset_at: datetime | None = None
    monthly_cycle_starts_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CreditLedgerEntry:
    id: UUID
    flow_account_id: UUID
    generation_job_id: UUID | None
    wallet_type: str
    action: str
    credit_delta: int
    source: str
    external_receipt: str | None
    idempotency_key: str
    details: dict[str, object]
    created_at: datetime


class CreditBalanceObservationProvider(Protocol):
    async def observe(
        self, *, account_ref: str, request_id: UUID
    ) -> CreditBalanceObservation | None:
        """Return provider evidence, never caller-supplied balances."""


class CreditLedgerStore(Protocol):
    async def assert_account_owned(self, *, account_id: UUID, owner_user_id: str) -> None: ...

    async def reconcile(
        self, *, account_id: UUID, owner_user_id: str, request_id: UUID,
        observation: CreditBalanceObservation, max_observation_age: timedelta,
    ) -> tuple[CreditLedgerEntry, CreditLedgerEntry]: ...

    async def list_entries(
        self, *, account_id: UUID, owner_user_id: str, limit: int,
    ) -> list[CreditLedgerEntry]: ...


def _aware(value: datetime | None) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


class CreditReconciliationService:
    """Validate live-provider evidence and commit both wallet snapshots atomically."""

    def __init__(
        self,
        store: CreditLedgerStore,
        provider: CreditBalanceObservationProvider | None,
        *,
        max_observation_age: timedelta = timedelta(minutes=10),
        now=None,
    ) -> None:
        if max_observation_age <= timedelta(0):
            raise ValueError("observation freshness window must be positive")
        self._store = store
        self._provider = provider
        self._max_age = max_observation_age
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def reconcile(
        self, *, account_id: UUID, owner_user_id: str, request_id: UUID
    ) -> tuple[CreditLedgerEntry, CreditLedgerEntry]:
        # This check is deliberately before passing the account reference to a provider.
        await self._store.assert_account_owned(account_id=account_id, owner_user_id=owner_user_id)
        if self._provider is None:
            raise CreditObservationUnavailable("credit observation provider is not configured")
        try:
            observation = await self._provider.observe(account_ref=str(account_id), request_id=request_id)
        except Exception as exc:
            raise CreditObservationUnavailable("credit observation provider is unavailable") from exc
        now = self._now()
        self._validate(observation, account_id=account_id, request_id=request_id, now=now)
        return await self._store.reconcile(
            account_id=account_id, owner_user_id=owner_user_id,
            request_id=request_id, observation=observation,
            max_observation_age=self._max_age,
        )

    async def list_entries(self, *, account_id: UUID, owner_user_id: str, limit: int = 100):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("credit ledger page size must be between 1 and 200")
        return await self._store.list_entries(
            account_id=account_id, owner_user_id=owner_user_id, limit=limit
        )

    def _validate(
        self, evidence: CreditBalanceObservation | None, *, account_id: UUID,
        request_id: UUID, now: datetime,
    ) -> None:
        if not isinstance(evidence, CreditBalanceObservation):
            raise InvalidCreditObservation("provider returned no supported credit observation")
        if (
            evidence.account_ref != str(account_id)
            or evidence.request_id != request_id
            or isinstance(evidence.daily_available, bool)
            or not isinstance(evidence.daily_available, int)
            or evidence.daily_available < 0
            or isinstance(evidence.monthly_available, bool)
            or not isinstance(evidence.monthly_available, int)
            or evidence.monthly_available < 0
            or not _aware(evidence.observed_at)
            or not _aware(now)
            or (evidence.next_daily_reset_at is not None and not _aware(evidence.next_daily_reset_at))
            or (evidence.monthly_cycle_starts_at is not None and not _aware(evidence.monthly_cycle_starts_at))
        ):
            raise InvalidCreditObservation("provider observation did not match the requested account or schema")
        observed = evidence.observed_at.astimezone(timezone.utc)
        current = now.astimezone(timezone.utc)
        if observed > current or current - observed > self._max_age:
            raise InvalidCreditObservation("provider observation is stale or from the future")
        if evidence.next_daily_reset_at is not None and evidence.next_daily_reset_at <= evidence.observed_at:
            raise InvalidCreditObservation("daily reset must occur after the observation")
        if evidence.monthly_cycle_starts_at is not None and evidence.monthly_cycle_starts_at > evidence.observed_at:
            raise InvalidCreditObservation("monthly cycle must begin no later than the observation")

