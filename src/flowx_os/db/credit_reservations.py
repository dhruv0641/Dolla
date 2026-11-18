"""Transactional, account-scoped credit reservation persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

from flowx_os.credits.reservations import (
    CreditQuoteEvidence,
    CreditQuoteSource,
    CreditReservationRecord,
    CreditReservationState,
)
from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.flow_accounts import OwnedFlowAccountNotFound
from flowx_os.db.transaction import ConnectionPool, unit_of_work


class CreditReservationError(RuntimeError):
    """Base for safe reservation precondition failures."""


class CreditAccountIneligible(CreditReservationError):
    pass


class CreditBalanceUnknown(CreditReservationError):
    pass


class CreditLimitExceeded(CreditReservationError):
    pass


class CreditReservationConflict(CreditReservationError):
    pass


_RESERVATION_COLUMNS = """id, flow_account_id, request_id, model_name, duration_seconds,
    quote_ref, quoted_credits, quote_source, quoted_at, quote_expires_at, state, created_at"""


class FlowCreditReservationRepository:
    """Lock an eligible account wallet and reserve only from fresh observed limits."""

    def __init__(self, pool: ConnectionPool, *, now: Callable[[], datetime] | None = None):
        self._pool = pool
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def assert_account_owned(self, *, account_id: UUID, owner_user_id: str) -> None:
        """Reject foreign account IDs before service calls external quote providers."""
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    "SELECT 1 FROM flow_accounts WHERE id = %s AND owner_user_id = %s",
                    (account_id, owner_user_id),
                )
                row = await cursor.fetchone()
        except Exception as exc:
            raise RepositoryUnavailable("Flow account storage is unavailable") from exc
        if row is None:
            raise OwnedFlowAccountNotFound("Flow account not found")

    async def reserve(
        self,
        *,
        account_id: UUID,
        owner_user_id: str,
        request_id: UUID,
        quote: CreditQuoteEvidence,
        now: datetime,
        max_quote_age: timedelta,
        max_balance_age: timedelta,
    ) -> CreditReservationRecord:
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT session_health, paused, compliance_approved,
                              observed_daily_available, observed_monthly_available,
                              last_reconciled_at, next_daily_reset_at, monthly_cycle_starts_at,
                              max_inflight
                       FROM flow_accounts
                       WHERE id = %s AND owner_user_id = %s
                       FOR UPDATE""",
                    (account_id, owner_user_id),
                )
                account = await cursor.fetchone()
                if account is None:
                    raise OwnedFlowAccountNotFound("Flow account not found")

                cursor = await connection.execute(
                    f"""SELECT {_RESERVATION_COLUMNS} FROM flow_credit_reservations
                         WHERE flow_account_id = %s AND request_id = %s""",
                    (account_id, request_id),
                )
                existing = await cursor.fetchone()
                if existing is not None:
                    record = self._to_record(existing)
                    if not self._same_request(record, quote):
                        raise CreditReservationConflict("request id is already bound to a different quote")
                    if record.state not in {
                        CreditReservationState.RESERVED,
                        CreditReservationState.RECONCILE_PENDING,
                    }:
                        raise CreditReservationConflict("request id is already closed")
                    return record

                self._require_eligible_account(account, now=now, max_balance_age=max_balance_age)
                cursor = await connection.execute(
                    """SELECT COUNT(*), COALESCE(SUM(quoted_credits), 0)
                       FROM flow_credit_reservations
                       WHERE flow_account_id = %s AND state IN ('RESERVED', 'RECONCILE_PENDING')""",
                    (account_id,),
                )
                active = await cursor.fetchone()
                if active is None:
                    raise RepositoryUnavailable("credit reservation query returned no result")
                active_count, active_credits = active
                if active_count >= account[8]:
                    raise CreditLimitExceeded("account concurrency limit is reached")
                daily_available = account[3] - active_credits
                monthly_available = account[4] - active_credits
                if quote.quoted_credits > daily_available or quote.quoted_credits > monthly_available:
                    raise CreditLimitExceeded("verified account credit limit is insufficient")
                # Database operations above may have waited. Revalidate both
                # quote and observed balance against a fresh decision time while
                # the account row is still locked, immediately before INSERT.
                decision_now = self._now()
                if (
                    quote.expires_at <= decision_now
                    or quote.quoted_at > decision_now
                    or quote.quoted_at < decision_now - max_quote_age
                ):
                    raise CreditBalanceUnknown("quote expired before reservation")
                self._require_eligible_account(
                    account,
                    now=decision_now,
                    max_balance_age=max_balance_age,
                )

                cursor = await connection.execute(
                    f"""INSERT INTO flow_credit_reservations
                           (flow_account_id, request_id, model_name, duration_seconds,
                            quote_ref, quoted_credits, quote_source, quoted_at, quote_expires_at)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                         ON CONFLICT (flow_account_id, request_id) DO NOTHING
                         RETURNING {_RESERVATION_COLUMNS}""",
                    (
                        account_id,
                        request_id,
                        quote.model_name,
                        quote.duration_seconds,
                        quote.quote_ref,
                        quote.quoted_credits,
                        quote.source.value,
                        quote.quoted_at,
                        quote.expires_at,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise CreditReservationConflict("reservation request was concurrently reused")
        except (
            OwnedFlowAccountNotFound,
            CreditReservationError,
            RepositoryUnavailable,
        ):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("credit reservation storage is unavailable") from exc
        return self._to_record(row)

    @staticmethod
    def _same_request(record: CreditReservationRecord, quote: CreditQuoteEvidence) -> bool:
        return (
            record.model_name == quote.model_name
            and record.duration_seconds == quote.duration_seconds
            and record.quote_ref == quote.quote_ref
            and record.quoted_credits == quote.quoted_credits
            and record.quote_source == quote.source
        )

    @staticmethod
    def _require_eligible_account(account, *, now: datetime, max_balance_age: timedelta) -> None:
        health, paused, compliance, daily, monthly, reconciled, daily_reset, cycle_start, max_inflight = account
        if health != "HEALTHY" or paused is not False or compliance is not True:
            raise CreditAccountIneligible("account is not verified, compliant, and enabled")
        if (
            isinstance(max_inflight, bool)
            or not isinstance(max_inflight, int)
            or max_inflight <= 0
        ):
            raise CreditAccountIneligible("account concurrency limit is invalid")
        if (
            isinstance(daily, bool)
            or not isinstance(daily, int)
            or daily < 0
            or isinstance(monthly, bool)
            or not isinstance(monthly, int)
            or monthly < 0
            or reconciled is None
            or reconciled.tzinfo is None
            or reconciled.utcoffset() is None
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise CreditBalanceUnknown("verified credit balance is unavailable")
        if not isinstance(max_balance_age, timedelta) or max_balance_age <= timedelta(0):
            raise CreditBalanceUnknown("credit balance freshness policy is invalid")
        if reconciled > now or now - reconciled > max_balance_age:
            raise CreditBalanceUnknown("verified credit balance is stale")
        if daily_reset is None:
            raise CreditBalanceUnknown("verified daily reset time is unavailable")
        if daily_reset.tzinfo is None or daily_reset.utcoffset() is None:
            raise CreditBalanceUnknown("daily reset time is invalid")
        if now >= daily_reset:
            raise CreditBalanceUnknown("daily credit balance crossed its reset window")
        if cycle_start is None:
            raise CreditBalanceUnknown("verified monthly cycle time is unavailable")
        if cycle_start.tzinfo is None or cycle_start.utcoffset() is None:
            raise CreditBalanceUnknown("monthly cycle time is invalid")
        if reconciled < cycle_start:
            raise CreditBalanceUnknown("monthly credit balance predates its current cycle")

    @staticmethod
    def _to_record(row) -> CreditReservationRecord:
        try:
            values = list(row)
            values[7] = CreditQuoteSource(values[7])
            values[10] = CreditReservationState(values[10])
            return CreditReservationRecord(*values)
        except (ValueError, TypeError, IndexError) as exc:
            raise RepositoryUnavailable("credit reservation record is invalid") from exc
