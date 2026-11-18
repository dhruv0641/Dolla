"""Owner-scoped persistence for registered Flow account references."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work


class FlowAccountAliasConflict(ValueError):
    """Raised when an alias is already registered."""


class OwnedFlowAccountNotFound(LookupError):
    """Raised when an account is absent or belongs to another principal."""


@dataclass(frozen=True, slots=True)
class FlowAccountRecord:
    id: UUID
    alias: str
    owner_user_id: str
    mcp_adapter: str
    plan_name: str | None
    monthly_allowance_estimate: int | None
    daily_allowance_estimate: int | None
    observed_monthly_available: int | None
    observed_daily_available: int | None
    monthly_cycle_starts_at: datetime | None
    next_daily_reset_at: datetime | None
    last_reconciled_at: datetime | None
    session_health: str
    paused: bool
    compliance_approved: bool
    max_inflight: int
    created_at: datetime


_RETURNING = """id, alias, owner_user_id, mcp_adapter, plan_name,
    monthly_allowance_estimate, daily_allowance_estimate,
    observed_monthly_available, observed_daily_available,
    monthly_cycle_starts_at, next_daily_reset_at, last_reconciled_at,
    session_health, paused, compliance_approved, max_inflight, created_at"""


class FlowAccountRepository:
    """Register and list accounts without returning secret references."""

    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    async def register(
        self, *, owner_user_id: str, alias: str, credentials_ref: str, mcp_adapter: str
    ) -> FlowAccountRecord:
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""INSERT INTO flow_accounts
                           (alias, owner_user_id, credentials_ref, mcp_adapter,
                            session_health, paused, compliance_approved)
                         VALUES (%s, %s, %s, %s, 'UNVERIFIED', TRUE, FALSE)
                         ON CONFLICT (owner_user_id, alias) DO NOTHING
                         RETURNING {_RETURNING}""",
                    (alias, owner_user_id, credentials_ref, mcp_adapter),
                )
                row = await cursor.fetchone()
        except Exception as exc:
            raise RepositoryUnavailable("Flow account storage is unavailable") from exc
        if row is None:
            raise FlowAccountAliasConflict("account alias is unavailable")
        return FlowAccountRecord(*row)

    async def list_for_owner(self, *, owner_user_id: str) -> list[FlowAccountRecord]:
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""SELECT {_RETURNING} FROM flow_accounts
                         WHERE owner_user_id = %s ORDER BY created_at, id""",
                    (owner_user_id,),
                )
                rows = await cursor.fetchall()
        except Exception as exc:
            raise RepositoryUnavailable("Flow account storage is unavailable") from exc
        return [FlowAccountRecord(*row) for row in rows]

    async def pause(self, *, account_id: UUID, owner_user_id: str) -> FlowAccountRecord:
        """Idempotently pause an owned account; this repository never activates accounts."""
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""UPDATE flow_accounts SET paused = TRUE
                         WHERE id = %s AND owner_user_id = %s
                         RETURNING {_RETURNING}""",
                    (account_id, owner_user_id),
                )
                row = await cursor.fetchone()
        except Exception as exc:
            raise RepositoryUnavailable("Flow account storage is unavailable") from exc
        if row is None:
            raise OwnedFlowAccountNotFound("Flow account not found")
        return FlowAccountRecord(*row)
