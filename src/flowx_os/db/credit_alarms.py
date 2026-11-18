"""Transactional, owner-scoped unknown-spend alarms and account controls."""

from __future__ import annotations

from uuid import UUID

from flowx_os.credits.alarms import (
    CreditRiskAlarmConflict,
    CreditRiskAlarmRecord,
    CreditRiskAlarmState,
    CreditRiskReservationUnavailable,
    UnknownSpendReason,
)
from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.flow_accounts import OwnedFlowAccountNotFound
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.db.workflow_events import WorkflowEventStore


_ALARM_COLUMNS = """id, flow_account_id, request_id, alarm_type,
    reason_code, state, created_at"""
_QUALIFIED_ALARM_COLUMNS = """alarm.id, alarm.flow_account_id, alarm.request_id,
    alarm.alarm_type, alarm.reason_code, alarm.state, alarm.created_at"""


class FlowCreditRiskAlarmRepository:
    """Atomically hold spend, pause an account, and create one durable alarm."""

    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    async def report_unknown_spend(
        self, *, account_id: UUID, owner_user_id: str,
        request_id: UUID, reason: UnknownSpendReason, actor: str,
    ) -> CreditRiskAlarmRecord:
        try:
            async with unit_of_work(self._pool) as connection:
                # Match reservation lock ordering: account first, then reservation.
                cursor = await connection.execute(
                    """SELECT id FROM flow_accounts
                       WHERE id = %s AND owner_user_id = %s FOR UPDATE""",
                    (account_id, owner_user_id),
                )
                account = await cursor.fetchone()
                if account is None:
                    raise OwnedFlowAccountNotFound("Flow account not found")

                cursor = await connection.execute(
                    """SELECT id, state FROM flow_credit_reservations
                       WHERE flow_account_id = %s AND request_id = %s FOR UPDATE""",
                    (account_id, request_id),
                )
                reservation = await cursor.fetchone()
                if reservation is None:
                    raise CreditRiskReservationUnavailable("credit reservation not found")
                if reservation[1] not in {"RESERVED", "RECONCILE_PENDING"}:
                    raise CreditRiskAlarmConflict("closed reservation cannot raise an unknown-spend alarm")

                cursor = await connection.execute(
                    """UPDATE flow_credit_reservations SET state = 'RECONCILE_PENDING'
                       WHERE id = %s AND flow_account_id = %s
                         AND state IN ('RESERVED', 'RECONCILE_PENDING')
                       RETURNING id""",
                    (reservation[0], account_id),
                )
                if await cursor.fetchone() is None:
                    raise CreditRiskAlarmConflict("credit reservation state changed")

                cursor = await connection.execute(
                    """UPDATE flow_accounts SET paused = TRUE
                       WHERE id = %s AND owner_user_id = %s RETURNING id""",
                    (account_id, owner_user_id),
                )
                if await cursor.fetchone() is None:
                    raise OwnedFlowAccountNotFound("Flow account not found")

                cursor = await connection.execute(
                    f"""INSERT INTO flow_credit_alarms
                           (flow_account_id, request_id, alarm_type, reason_code, state, created_by)
                         VALUES (%s, %s, 'UNKNOWN_SPEND', %s, 'OPEN', %s)
                         ON CONFLICT (flow_account_id, request_id, alarm_type) DO NOTHING
                         RETURNING {_ALARM_COLUMNS}""",
                    (account_id, request_id, reason.value, actor),
                )
                alarm_row = await cursor.fetchone()
                if alarm_row is None:
                    cursor = await connection.execute(
                        f"""SELECT {_ALARM_COLUMNS} FROM flow_credit_alarms
                             WHERE flow_account_id = %s AND request_id = %s
                               AND alarm_type = 'UNKNOWN_SPEND'""",
                        (account_id, request_id),
                    )
                    alarm_row = await cursor.fetchone()
                    if alarm_row is None or alarm_row[4] != reason.value:
                        raise CreditRiskAlarmConflict("reservation already has a different unknown-spend alarm")
                    return self._to_record(alarm_row)

                await WorkflowEventStore(connection).append(
                    entity_type="flow_credit_reservation",
                    entity_id=reservation[0],
                    event_name="credit.unknown_spend_detected",
                    correlation_id=request_id,
                    actor=actor,
                    payload={
                        "alarm_id": str(alarm_row[0]),
                        "alarm_type": "UNKNOWN_SPEND",
                        "reason_code": reason.value,
                        "reservation_state": "RECONCILE_PENDING",
                    },
                )
                return self._to_record(alarm_row)
        except (
            OwnedFlowAccountNotFound,
            CreditRiskAlarmConflict,
            CreditRiskReservationUnavailable,
            RepositoryUnavailable,
        ):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("credit risk alarm storage is unavailable") from exc

    async def list_open_alarms(
        self, *, account_id: UUID, owner_user_id: str, limit: int,
    ) -> list[CreditRiskAlarmRecord]:
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""SELECT {_QUALIFIED_ALARM_COLUMNS}
                         FROM flow_credit_alarms AS alarm
                         JOIN flow_accounts AS account ON account.id = alarm.flow_account_id
                         WHERE account.id = %s AND account.owner_user_id = %s
                           AND alarm.state = 'OPEN'
                         ORDER BY alarm.created_at DESC, alarm.id DESC LIMIT %s""",
                    (account_id, owner_user_id, limit),
                )
                rows = await cursor.fetchall()
                if rows:
                    return [self._to_record(row) for row in rows]
                cursor = await connection.execute(
                    "SELECT 1 FROM flow_accounts WHERE id = %s AND owner_user_id = %s",
                    (account_id, owner_user_id),
                )
                account = await cursor.fetchone()
                if account is None:
                    raise OwnedFlowAccountNotFound("Flow account not found")
                return []
        except (OwnedFlowAccountNotFound, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("credit risk alarm storage is unavailable") from exc

    @staticmethod
    def _to_record(row) -> CreditRiskAlarmRecord:
        try:
            values = list(row)
            values[4] = UnknownSpendReason(values[4])
            values[5] = CreditRiskAlarmState(values[5])
            return CreditRiskAlarmRecord(*values)
        except (TypeError, ValueError, IndexError) as exc:
            raise RepositoryUnavailable("credit risk alarm record is invalid") from exc

