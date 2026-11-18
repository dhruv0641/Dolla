import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx

from flowx_os.api.main import create_app
from flowx_os.credits.ledger import (
    CreditBalanceObservation,
    CreditObservationUnavailable,
    CreditReconciliationConflict,
    CreditReconciliationService,
    InvalidCreditObservation,
)
from flowx_os.db.credit_ledger import FlowCreditLedgerRepository
from flowx_os.db.flow_accounts import OwnedFlowAccountNotFound


NOW = datetime(2026, 11, 19, 2, 0, tzinfo=timezone.utc)
ACCOUNT_ID = UUID("1090bf84-9d8a-4a0b-91cb-0ee53c8d649d")
REQUEST_ID = UUID("2190bf84-9d8a-4a0b-91cb-0ee53c8d649d")
ENTRY_ID_DAILY = UUID("3290bf84-9d8a-4a0b-91cb-0ee53c8d649d")
ENTRY_ID_MONTHLY = UUID("4290bf84-9d8a-4a0b-91cb-0ee53c8d649d")


class FakeCursor:
    def __init__(self, *, one=None, many=None):
        self.one = one
        self.many = many or []

    async def fetchone(self):
        return self.one

    async def fetchall(self):
        return self.many


class FakeConnection:
    def __init__(self, responses, *, on_execute=None):
        self.responses = list(responses)
        self.queries = []
        self.on_execute = on_execute

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query, params=None):
        self.queries.append((query, params))
        if self.on_execute is not None:
            self.on_execute(query)
        return self.responses.pop(0)


class FakePool:
    def __init__(self, connection):
        self.connection_value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.connection_value


class FakeStore:
    def __init__(self, *, owned_error=None):
        self.owned_error = owned_error
        self.owned_calls = []
        self.reconcile_calls = []
        self.entries = []

    async def assert_account_owned(self, *, account_id, owner_user_id):
        self.owned_calls.append((account_id, owner_user_id))
        if self.owned_error:
            raise self.owned_error

    async def reconcile(self, **kwargs):
        self.reconcile_calls.append(kwargs)
        return ()

    async def list_entries(self, **kwargs):
        return self.entries


class FakeProvider:
    def __init__(self, evidence):
        self.evidence = evidence
        self.calls = []

    async def observe(self, *, account_ref, request_id):
        self.calls.append((account_ref, request_id))
        return self.evidence


def observation(**changes):
    values = {
        "account_ref": str(ACCOUNT_ID),
        "request_id": REQUEST_ID,
        "daily_available": 18,
        "monthly_available": 420,
        "observed_at": NOW - timedelta(seconds=30),
        "next_daily_reset_at": NOW + timedelta(hours=4),
        "monthly_cycle_starts_at": NOW - timedelta(days=8),
    }
    values.update(changes)
    return CreditBalanceObservation(**values)


def entry_row(entry_id, wallet, delta, key, *, before, after):
    details = {
        "available_after": after,
        "available_before": before,
        "observation_fingerprint": "fingerprint",
    }
    return (
        entry_id, ACCOUNT_ID, None, wallet, "RECONCILE", delta, "FLOW_OBSERVED",
        None, key, details, NOW,
    )


class CreditReconciliationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_is_checked_before_provider_receives_account_reference(self):
        store = FakeStore(owned_error=OwnedFlowAccountNotFound("not found"))
        provider = FakeProvider(observation())
        service = CreditReconciliationService(store, provider, now=lambda: NOW)
        with self.assertRaises(OwnedFlowAccountNotFound):
            await service.reconcile(account_id=ACCOUNT_ID, owner_user_id="other", request_id=REQUEST_ID)
        self.assertEqual(provider.calls, [])

    async def test_missing_provider_fails_closed_after_owner_check(self):
        store = FakeStore()
        service = CreditReconciliationService(store, None, now=lambda: NOW)
        with self.assertRaises(CreditObservationUnavailable):
            await service.reconcile(account_id=ACCOUNT_ID, owner_user_id="owner", request_id=REQUEST_ID)
        self.assertEqual(store.owned_calls, [(ACCOUNT_ID, "owner")])

    async def test_rejects_wrong_account_and_stale_or_invalid_balances(self):
        cases = [
            observation(account_ref="foreign-account"),
            observation(observed_at=NOW + timedelta(seconds=1)),
            observation(observed_at=NOW - timedelta(minutes=11)),
            observation(daily_available=-1),
            observation(monthly_available=True),
            observation(next_daily_reset_at=NOW - timedelta(minutes=1)),
            observation(monthly_cycle_starts_at=NOW + timedelta(seconds=1)),
        ]
        for evidence in cases:
            store = FakeStore()
            service = CreditReconciliationService(
                store, FakeProvider(evidence), now=lambda: NOW
            )
            with self.subTest(evidence=evidence), self.assertRaises(InvalidCreditObservation):
                await service.reconcile(
                    account_id=ACCOUNT_ID, owner_user_id="owner", request_id=REQUEST_ID
                )
            self.assertEqual(store.reconcile_calls, [])

    async def test_valid_provider_evidence_is_passed_to_atomic_store(self):
        store = FakeStore()
        provider = FakeProvider(observation())
        service = CreditReconciliationService(store, provider, now=lambda: NOW)
        await service.reconcile(account_id=ACCOUNT_ID, owner_user_id="owner", request_id=REQUEST_ID)
        self.assertEqual(provider.calls, [(str(ACCOUNT_ID), REQUEST_ID)])
        self.assertEqual(len(store.reconcile_calls), 1)
        self.assertEqual(store.reconcile_calls[0]["observation"], observation())


class CreditLedgerRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconciliation_locks_account_and_writes_both_wallets_and_snapshot(self):
        fingerprint = FlowCreditLedgerRepository._fingerprint(observation())
        daily, monthly = entry_row(
            ENTRY_ID_DAILY, "DAILY", 14, f"reconcile:{REQUEST_ID}:DAILY", before=4, after=18
        ), entry_row(
            ENTRY_ID_MONTHLY, "MONTHLY", 70, f"reconcile:{REQUEST_ID}:MONTHLY", before=350, after=420
        )
        daily = (*daily[:9], {**daily[9], "observation_fingerprint": fingerprint}, daily[10])
        monthly = (*monthly[:9], {**monthly[9], "observation_fingerprint": fingerprint}, monthly[10])
        connection = FakeConnection([
            FakeCursor(one=(4, 350, NOW - timedelta(days=1), NOW + timedelta(hours=1), NOW - timedelta(days=8))),
            FakeCursor(many=[]),
            FakeCursor(one=daily),
            FakeCursor(one=monthly),
            FakeCursor(one=None),
        ])
        repository = FlowCreditLedgerRepository(FakePool(connection), now=lambda: NOW)
        result = await repository.reconcile(
            account_id=ACCOUNT_ID, owner_user_id="owner", request_id=REQUEST_ID,
            observation=observation(), max_observation_age=timedelta(minutes=10),
        )
        self.assertEqual([record.wallet_type for record in result], ["DAILY", "MONTHLY"])
        self.assertIn("FOR UPDATE", connection.queries[0][0])
        self.assertEqual(connection.queries[2][1][1:4], ("DAILY", 14, f"reconcile:{REQUEST_ID}:DAILY"))
        self.assertEqual(connection.queries[3][1][1:4], ("MONTHLY", 70, f"reconcile:{REQUEST_ID}:MONTHLY"))
        self.assertIn("UPDATE flow_accounts", connection.queries[-1][0])
        self.assertEqual(connection.queries[-1][1][:2], (18, 420))

    async def test_unverified_legacy_scalar_values_are_recorded_as_a_zero_delta_baseline(self):
        fingerprint = FlowCreditLedgerRepository._fingerprint(observation())
        rows = []
        for entry_id, wallet, amount, key in (
            (ENTRY_ID_DAILY, "DAILY", 18, f"reconcile:{REQUEST_ID}:DAILY"),
            (ENTRY_ID_MONTHLY, "MONTHLY", 420, f"reconcile:{REQUEST_ID}:MONTHLY"),
        ):
            row = entry_row(entry_id, wallet, 0, key, before=None, after=amount)
            rows.append((*row[:9], {**row[9], "observation_fingerprint": fingerprint}, row[10]))
        connection = FakeConnection([
            FakeCursor(one=(3, 300, None, None, None)),
            FakeCursor(many=[]),
            FakeCursor(one=rows[0]),
            FakeCursor(one=rows[1]),
            FakeCursor(one=None),
        ])
        repository = FlowCreditLedgerRepository(FakePool(connection), now=lambda: NOW)
        await repository.reconcile(
            account_id=ACCOUNT_ID, owner_user_id="owner", request_id=REQUEST_ID,
            observation=observation(), max_observation_age=timedelta(minutes=10),
        )
        self.assertEqual(connection.queries[2][1][1:3], ("DAILY", 0))
        self.assertEqual(connection.queries[3][1][1:3], ("MONTHLY", 0))

    async def test_repeat_request_returns_existing_pair_without_mutating_snapshot(self):
        evidence = observation()
        fingerprint = FlowCreditLedgerRepository._fingerprint(evidence)
        rows = []
        for item in (
            entry_row(ENTRY_ID_DAILY, "DAILY", 0, f"reconcile:{REQUEST_ID}:DAILY", before=None, after=18),
            entry_row(ENTRY_ID_MONTHLY, "MONTHLY", 0, f"reconcile:{REQUEST_ID}:MONTHLY", before=None, after=420),
        ):
            rows.append((*item[:9], {**item[9], "observation_fingerprint": fingerprint}, item[10]))
        connection = FakeConnection([
            FakeCursor(one=(18, 420, NOW - timedelta(seconds=1))),
            FakeCursor(many=rows),
        ])
        repository = FlowCreditLedgerRepository(FakePool(connection))
        result = await repository.reconcile(
            account_id=ACCOUNT_ID, owner_user_id="owner", request_id=REQUEST_ID,
            observation=evidence, max_observation_age=timedelta(minutes=10),
        )
        self.assertEqual([record.wallet_type for record in result], ["DAILY", "MONTHLY"])
        self.assertEqual(len(connection.queries), 2)

    async def test_observation_freshness_is_rechecked_after_lock_wait(self):
        current = [NOW]

        def simulate_wait(query):
            if "FOR UPDATE" in query:
                current[0] = NOW + timedelta(minutes=11)

        connection = FakeConnection([
            FakeCursor(one=(None, None, None, None, None)),
            FakeCursor(many=[]),
        ], on_execute=simulate_wait)
        repository = FlowCreditLedgerRepository(FakePool(connection), now=lambda: current[0])
        with self.assertRaises(CreditReconciliationConflict):
            await repository.reconcile(
                account_id=ACCOUNT_ID, owner_user_id="owner", request_id=REQUEST_ID,
                observation=observation(), max_observation_age=timedelta(minutes=10),
            )
        self.assertEqual(len(connection.queries), 2)
        self.assertFalse(any("INSERT INTO flow_credit_entries" in query for query, _ in connection.queries))


class CreditLedgerApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconciliation_endpoint_fails_closed_without_provider(self):
        from tests.test_credit_reservations import make_auth

        verifier, token = make_auth()
        pool = FakePool(FakeConnection([FakeCursor(one=(1,))]))
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=verifier, database_pool=pool)),
            base_url="http://testserver", headers={"Authorization": f"Bearer {token}"},
        )
        async with client:
            response = await client.post(
                f"/api/v1/flow-accounts/{ACCOUNT_ID}/credit-reconciliations",
                json={"request_id": str(REQUEST_ID)},
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "credit_observation_unavailable")
        self.assertEqual(pool.connection_value.queries[0][1], (ACCOUNT_ID, "owner-1"))

    async def test_api_ledger_projection_drops_unrecognized_details_and_receipt(self):
        from flowx_os.api.main import _credit_ledger_entry_response
        from flowx_os.credits.ledger import CreditLedgerEntry

        record = CreditLedgerEntry(
            ENTRY_ID_DAILY, ACCOUNT_ID, None, "DAILY", "RECONCILE", 0,
            "FLOW_OBSERVED", "credential=never-return", "opaque-secret-key",
            {"available_after": 18, "raw_provider_payload": "token=secret", "nested": {"key": "secret"}},
            NOW,
        )
        payload = _credit_ledger_entry_response(record).model_dump(mode="json")
        self.assertEqual(payload["details"], {"available_after": 18})
        self.assertNotIn("external_receipt", payload)
        self.assertNotIn("idempotency_key", payload)
        self.assertNotIn("raw_provider_payload", payload["details"])


if __name__ == "__main__":
    unittest.main()
