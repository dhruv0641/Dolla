"""Owner-scoped, idempotent persistence for observed credit balances."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from flowx_os.credits.ledger import (
    CreditBalanceObservation,
    CreditLedgerEntry,
    CreditReconciliationConflict,
)
from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.flow_accounts import OwnedFlowAccountNotFound
from flowx_os.db.transaction import ConnectionPool, unit_of_work


_ENTRY_COLUMNS = """id, flow_account_id, generation_job_id, wallet_type, action,
    credit_delta, source, external_receipt, idempotency_key, details, created_at"""
_QUALIFIED_ENTRY_COLUMNS = """entry.id, entry.flow_account_id, entry.generation_job_id,
    entry.wallet_type, entry.action, entry.credit_delta, entry.source,
    entry.external_receipt, entry.idempotency_key, entry.details, entry.created_at"""


class FlowCreditLedgerRepository:
    """Write both observed wallets under one account lock and one transaction."""

    def __init__(self, pool: ConnectionPool, *, now=None):
        self._pool = pool
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def assert_account_owned(self, *, account_id: UUID, owner_user_id: str) -> None:
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

    async def reconcile(
        self, *, account_id: UUID, owner_user_id: str, request_id: UUID,
        observation: CreditBalanceObservation, max_observation_age: timedelta,
    ) -> tuple[CreditLedgerEntry, CreditLedgerEntry]:
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT observed_daily_available, observed_monthly_available,
                              last_reconciled_at, next_daily_reset_at, monthly_cycle_starts_at
                       FROM flow_accounts WHERE id = %s AND owner_user_id = %s FOR UPDATE""",
                    (account_id, owner_user_id),
                )
                account = await cursor.fetchone()
                if account is None:
                    raise OwnedFlowAccountNotFound("Flow account not found")

                fingerprint = self._fingerprint(observation)
                keys = (f"reconcile:{request_id}:DAILY", f"reconcile:{request_id}:MONTHLY")
                cursor = await connection.execute(
                    f"""SELECT {_ENTRY_COLUMNS} FROM flow_credit_entries
                         WHERE flow_account_id = %s AND idempotency_key = ANY(%s)
                         ORDER BY wallet_type""",
                    (account_id, list(keys)),
                )
                existing = await cursor.fetchall()
                if existing:
                    records = [self._to_record(row) for row in existing]
                    by_wallet = {record.wallet_type: record for record in records}
                    if (
                        len(records) != 2
                        or set(by_wallet) != {"DAILY", "MONTHLY"}
                        or any(record.idempotency_key not in keys for record in records)
                        or any(record.details.get("observation_fingerprint") != fingerprint for record in records)
                    ):
                        raise CreditReconciliationConflict("reconciliation request id was reused with different evidence")
                    return by_wallet["DAILY"], by_wallet["MONTHLY"]

                decision_now = self._now()
                if (
                    decision_now.tzinfo is None
                    or decision_now.utcoffset() is None
                    or observation.observed_at > decision_now
                    or decision_now - observation.observed_at > max_observation_age
                ):
                    raise CreditReconciliationConflict("credit observation became stale before commit")
                previous_reconciled = account[2]
                observed_at = observation.observed_at.astimezone(timezone.utc)
                if previous_reconciled is not None and (
                    previous_reconciled.tzinfo is None
                    or previous_reconciled.utcoffset() is None
                    or previous_reconciled >= observed_at
                ):
                    raise CreditReconciliationConflict("credit observation does not advance the account snapshot")

                # Without a reconciliation timestamp, prior scalar fields are
                # not trusted as a verified snapshot and must not create a delta.
                previous_daily = account[0] if previous_reconciled is not None else None
                previous_monthly = account[1] if previous_reconciled is not None else None
                daily_delta = 0 if previous_daily is None else observation.daily_available - previous_daily
                monthly_delta = 0 if previous_monthly is None else observation.monthly_available - previous_monthly
                values = (
                    ("DAILY", daily_delta, previous_daily, observation.daily_available, keys[0]),
                    ("MONTHLY", monthly_delta, previous_monthly, observation.monthly_available, keys[1]),
                )
                records: dict[str, CreditLedgerEntry] = {}
                for wallet, delta, previous, available, idempotency_key in values:
                    details = json.dumps({
                        "available_after": available,
                        "available_before": previous,
                        "observation_fingerprint": fingerprint,
                        "observed_at": observed_at.isoformat(),
                        "baseline": previous is None,
                        "delta_semantics": "available_after_minus_available_before; baseline delta is zero",
                        "previous_daily_reset_at": account[3].isoformat() if account[3] else None,
                        "next_daily_reset_at": observation.next_daily_reset_at.isoformat() if wallet == "DAILY" and observation.next_daily_reset_at else None,
                        "previous_monthly_cycle_starts_at": account[4].isoformat() if account[4] else None,
                        "monthly_cycle_starts_at": observation.monthly_cycle_starts_at.isoformat() if wallet == "MONTHLY" and observation.monthly_cycle_starts_at else None,
                    }, separators=(",", ":"))
                    cursor = await connection.execute(
                        f"""INSERT INTO flow_credit_entries
                               (flow_account_id, wallet_type, action, credit_delta, source,
                                idempotency_key, details, created_at)
                             VALUES (%s, %s, 'RECONCILE', %s, 'FLOW_OBSERVED', %s, %s::jsonb, %s)
                             ON CONFLICT (flow_account_id, idempotency_key) DO NOTHING
                             RETURNING {_ENTRY_COLUMNS}""",
                        (account_id, wallet, delta, idempotency_key, details, decision_now),
                    )
                    row = await cursor.fetchone()
                    if row is None:
                        raise CreditReconciliationConflict("reconciliation request was concurrently reused")
                    records[wallet] = self._to_record(row)

                await connection.execute(
                    """UPDATE flow_accounts
                       SET observed_daily_available = %s,
                           observed_monthly_available = %s,
                           next_daily_reset_at = COALESCE(%s, next_daily_reset_at),
                           monthly_cycle_starts_at = COALESCE(%s, monthly_cycle_starts_at),
                           last_reconciled_at = %s
                       WHERE id = %s AND owner_user_id = %s""",
                    (
                        observation.daily_available, observation.monthly_available,
                        observation.next_daily_reset_at, observation.monthly_cycle_starts_at,
                        observed_at, account_id, owner_user_id,
                    ),
                )
                return records["DAILY"], records["MONTHLY"]
        except (OwnedFlowAccountNotFound, CreditReconciliationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("credit ledger storage is unavailable") from exc

    async def list_entries(
        self, *, account_id: UUID, owner_user_id: str, limit: int,
    ) -> list[CreditLedgerEntry]:
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""SELECT {_QUALIFIED_ENTRY_COLUMNS}
                         FROM flow_credit_entries AS entry
                         JOIN flow_accounts AS account ON account.id = entry.flow_account_id
                         WHERE account.id = %s AND account.owner_user_id = %s
                         ORDER BY entry.created_at DESC, entry.id DESC LIMIT %s""",
                    (account_id, owner_user_id, limit),
                )
                rows = await cursor.fetchall()
        except Exception as exc:
            raise RepositoryUnavailable("credit ledger storage is unavailable") from exc
        # Hide both absent and foreign account IDs using the same result.
        if not rows:
            await self.assert_account_owned(account_id=account_id, owner_user_id=owner_user_id)
        return [self._to_record(row) for row in rows]

    @staticmethod
    def _fingerprint(observation: CreditBalanceObservation) -> str:
        payload = {
            "account_ref": observation.account_ref,
            "request_id": str(observation.request_id),
            "daily_available": observation.daily_available,
            "monthly_available": observation.monthly_available,
            "observed_at": observation.observed_at.astimezone(timezone.utc).isoformat(),
            "next_daily_reset_at": observation.next_daily_reset_at.isoformat() if observation.next_daily_reset_at else None,
            "monthly_cycle_starts_at": observation.monthly_cycle_starts_at.isoformat() if observation.monthly_cycle_starts_at else None,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _to_record(row) -> CreditLedgerEntry:
        try:
            values = list(row)
            if isinstance(values[9], str):
                values[9] = json.loads(values[9])
            if not isinstance(values[9], dict) or any(not isinstance(key, str) for key in values[9]):
                raise ValueError("credit ledger details must be a JSON object")
            return CreditLedgerEntry(*values)
        except (TypeError, ValueError, IndexError, json.JSONDecodeError) as exc:
            raise RepositoryUnavailable("credit ledger entry is invalid") from exc

