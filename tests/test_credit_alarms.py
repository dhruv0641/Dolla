import time
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID

import httpx

from flowx_os.api.main import create_app
from flowx_os.credits.alarms import (
    CreditRiskAlarmConflict,
    CreditRiskAlarmRecord,
    CreditRiskAlarmService,
    CreditRiskReservationUnavailable,
    SYSTEM_CREDIT_RISK_ACTOR,
    UnknownSpendReason,
)
from flowx_os.db.credit_alarms import FlowCreditRiskAlarmRepository
from flowx_os.db.flow_accounts import OwnedFlowAccountNotFound


ACCOUNT_ID = UUID("1090bf84-9d8a-4a0b-91cb-0ee53c8d649d")
REQUEST_ID = UUID("2190bf84-9d8a-4a0b-91cb-0ee53c8d649d")
RESERVATION_ID = UUID("3290bf84-9d8a-4a0b-91cb-0ee53c8d649d")
ALARM_ID = UUID("4290bf84-9d8a-4a0b-91cb-0ee53c8d649d")
NOW = datetime(2026, 11, 19, 2, 10, tzinfo=timezone.utc)
ALARM_ROW = (
    ALARM_ID, ACCOUNT_ID, REQUEST_ID, "UNKNOWN_SPEND",
    "ACTUAL_COST_UNKNOWN", "OPEN", NOW,
)


class FakeCursor:
    def __init__(self, *, one=None, many=None):
        self.one = one
        self.many = many or []

    async def fetchone(self):
        return self.one

    async def fetchall(self):
        return self.many


class FakeConnection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query, params=None):
        self.queries.append((query, params))
        return self.responses.pop(0)


class FakePool:
    def __init__(self, connection):
        self.connection_value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.connection_value


class FakeAlarmStore:
    def __init__(self, record=None, error=None):
        self.record = record or CreditRiskAlarmRecord(
            ALARM_ID, ACCOUNT_ID, REQUEST_ID, "UNKNOWN_SPEND",
            UnknownSpendReason.ACTUAL_COST_UNKNOWN, "OPEN", NOW,
        )
        self.error = error
        self.calls = []

    async def report_unknown_spend(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.record

    async def list_open_alarms(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return [self.record]


def record():
    return CreditRiskAlarmRecord(
        ALARM_ID, ACCOUNT_ID, REQUEST_ID, "UNKNOWN_SPEND",
        UnknownSpendReason.ACTUAL_COST_UNKNOWN, "OPEN", NOW,
    )


class CreditRiskAlarmRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_spend_atomically_holds_pauses_alarms_and_audits(self):
        connection = FakeConnection([
            FakeCursor(one=(ACCOUNT_ID,)),
            FakeCursor(one=(RESERVATION_ID, "RESERVED")),
            FakeCursor(one=(RESERVATION_ID,)),
            FakeCursor(one=(ACCOUNT_ID,)),
            FakeCursor(one=ALARM_ROW),
            FakeCursor(one=None),
        ])
        repository = FlowCreditRiskAlarmRepository(FakePool(connection))
        result = await repository.report_unknown_spend(
            account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
            reason=UnknownSpendReason.ACTUAL_COST_UNKNOWN, actor=SYSTEM_CREDIT_RISK_ACTOR,
        )
        self.assertEqual(result, record())
        self.assertIn("FOR UPDATE", connection.queries[0][0])
        self.assertIn("FOR UPDATE", connection.queries[1][0])
        self.assertIn("RECONCILE_PENDING", connection.queries[2][0])
        self.assertIn("SET paused = TRUE", connection.queries[3][0])
        self.assertIn("INSERT INTO flow_credit_alarms", connection.queries[4][0])
        self.assertIn("INSERT INTO workflow_events", connection.queries[5][0])
        self.assertEqual(connection.queries[4][1], (
            ACCOUNT_ID, REQUEST_ID, "ACTUAL_COST_UNKNOWN", SYSTEM_CREDIT_RISK_ACTOR,
        ))
        self.assertIn("created_by", connection.queries[4][0])
        self.assertEqual(connection.queries[5][1][4], SYSTEM_CREDIT_RISK_ACTOR)

    async def test_repeated_unknown_spend_returns_existing_alarm_without_duplicate_event(self):
        connection = FakeConnection([
            FakeCursor(one=(ACCOUNT_ID,)),
            FakeCursor(one=(RESERVATION_ID, "RECONCILE_PENDING")),
            FakeCursor(one=(RESERVATION_ID,)),
            FakeCursor(one=(ACCOUNT_ID,)),
            FakeCursor(one=None),
            FakeCursor(one=ALARM_ROW),
        ])
        repository = FlowCreditRiskAlarmRepository(FakePool(connection))
        result = await repository.report_unknown_spend(
            account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
            reason=UnknownSpendReason.ACTUAL_COST_UNKNOWN, actor=SYSTEM_CREDIT_RISK_ACTOR,
        )
        self.assertEqual(result, record())
        self.assertEqual(len(connection.queries), 6)
        self.assertNotIn("INSERT INTO workflow_events", "\n".join(query for query, _ in connection.queries))

    async def test_reused_alarm_with_different_reason_conflicts(self):
        changed_alarm = (*ALARM_ROW[:4], "REMOTE_JOB_STATE_UNKNOWN", *ALARM_ROW[5:])
        connection = FakeConnection([
            FakeCursor(one=(ACCOUNT_ID,)),
            FakeCursor(one=(RESERVATION_ID, "RECONCILE_PENDING")),
            FakeCursor(one=(RESERVATION_ID,)),
            FakeCursor(one=(ACCOUNT_ID,)),
            FakeCursor(one=None),
            FakeCursor(one=changed_alarm),
        ])
        repository = FlowCreditRiskAlarmRepository(FakePool(connection))
        with self.assertRaises(CreditRiskAlarmConflict):
            await repository.report_unknown_spend(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                reason=UnknownSpendReason.ACTUAL_COST_UNKNOWN, actor=SYSTEM_CREDIT_RISK_ACTOR,
            )

    async def test_foreign_account_is_hidden_before_reservation_lookup(self):
        connection = FakeConnection([FakeCursor(one=None)])
        repository = FlowCreditRiskAlarmRepository(FakePool(connection))
        with self.assertRaises(OwnedFlowAccountNotFound):
            await repository.report_unknown_spend(
                account_id=ACCOUNT_ID, owner_user_id="other", request_id=REQUEST_ID,
                reason=UnknownSpendReason.ACTUAL_COST_UNKNOWN, actor=SYSTEM_CREDIT_RISK_ACTOR,
            )
        self.assertEqual(len(connection.queries), 1)

    async def test_missing_reservation_cannot_create_alarm(self):
        connection = FakeConnection([
            FakeCursor(one=(ACCOUNT_ID,)),
            FakeCursor(one=None),
        ])
        repository = FlowCreditRiskAlarmRepository(FakePool(connection))
        with self.assertRaises(CreditRiskReservationUnavailable):
            await repository.report_unknown_spend(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                reason=UnknownSpendReason.ACTUAL_COST_UNKNOWN, actor=SYSTEM_CREDIT_RISK_ACTOR,
            )
        self.assertEqual(len(connection.queries), 2)

    async def test_closed_reservation_cannot_be_marked_unknown_again(self):
        connection = FakeConnection([
            FakeCursor(one=(ACCOUNT_ID,)),
            FakeCursor(one=(RESERVATION_ID, "SETTLED")),
        ])
        repository = FlowCreditRiskAlarmRepository(FakePool(connection))
        with self.assertRaises(CreditRiskAlarmConflict):
            await repository.report_unknown_spend(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                reason=UnknownSpendReason.ACTUAL_COST_UNKNOWN, actor=SYSTEM_CREDIT_RISK_ACTOR,
            )
        self.assertEqual(len(connection.queries), 2)

    async def test_open_alarm_listing_is_owner_scoped(self):
        connection = FakeConnection([FakeCursor(many=[ALARM_ROW])])
        repository = FlowCreditRiskAlarmRepository(FakePool(connection))
        result = await repository.list_open_alarms(
            account_id=ACCOUNT_ID, owner_user_id="owner-1", limit=50,
        )
        self.assertEqual(result, [record()])
        self.assertIn("account.owner_user_id = %s", connection.queries[0][0])
        self.assertEqual(connection.queries[0][1], (ACCOUNT_ID, "owner-1", 50))


class CreditRiskAlarmServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_rejects_untyped_reason_and_bounds_list_page(self):
        store = FakeAlarmStore()
        service = CreditRiskAlarmService(store)
        with self.assertRaises(ValueError):
            await service.report_unknown_spend(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                reason="untrusted-provider-text", actor=SYSTEM_CREDIT_RISK_ACTOR,
            )
        with self.assertRaises(ValueError):
            await service.list_open_alarms(account_id=ACCOUNT_ID, owner_user_id="owner-1", limit=1000)
        self.assertEqual(store.calls, [])


class CreditRiskAlarmApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_operator_can_report_unknown_spend_and_response_is_sanitized(self):
        from tests.test_credit_reservations import make_auth

        verifier, token = make_auth()
        service = CreditRiskAlarmService(FakeAlarmStore())
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(
                token_verifier=verifier,
                database_pool=FakePool(FakeConnection([])),
                credit_risk_alarm_service=service,
            )),
            base_url="http://testserver", headers={"Authorization": f"Bearer {token}"},
        )
        async with client:
            response = await client.post(
                f"/api/v1/flow-accounts/{ACCOUNT_ID}/credit-reservations/{REQUEST_ID}/unknown-spend",
                json={"reason": "ACTUAL_COST_UNKNOWN"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "OPEN")
        self.assertEqual(response.json()["reason_code"], "ACTUAL_COST_UNKNOWN")
        self.assertEqual(service._store.calls[0]["actor"], "user:owner-1")
        self.assertNotIn("owner_user_id", response.json())
        self.assertNotIn("details", response.json())

    async def test_operator_can_list_owner_visible_alarms(self):
        from tests.test_credit_reservations import make_auth

        verifier, token = make_auth()
        service = CreditRiskAlarmService(FakeAlarmStore())
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(
                token_verifier=verifier,
                database_pool=FakePool(FakeConnection([])),
                credit_risk_alarm_service=service,
            )),
            base_url="http://testserver", headers={"Authorization": f"Bearer {token}"},
        )
        async with client:
            response = await client.get(f"/api/v1/flow-accounts/{ACCOUNT_ID}/credit-alarms?limit=50")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["state"], "OPEN")

    async def test_unknown_spend_route_is_unavailable_without_database(self):
        from tests.test_credit_reservations import make_auth

        verifier, token = make_auth()
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=verifier)),
            base_url="http://testserver", headers={"Authorization": f"Bearer {token}"},
        )
        async with client:
            response = await client.post(
                f"/api/v1/flow-accounts/{ACCOUNT_ID}/credit-reservations/{REQUEST_ID}/unknown-spend",
                json={"reason": "ACTUAL_COST_UNKNOWN"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "database_not_configured")


if __name__ == "__main__":
    unittest.main()
