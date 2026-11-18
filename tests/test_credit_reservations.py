import base64
import hashlib
import hmac
import json
import time
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx

from flowx_os.api.main import create_app
from flowx_os.auth.tokens import TokenVerifier
from flowx_os.credits.reservations import (
    CreditApprovalRequired,
    CreditApprovalUnavailable,
    CreditQuoteEvidence,
    CreditQuoteRequest,
    CreditQuoteSource,
    CreditQuoteUnavailable,
    CreditReservationRecord,
    CreditReservationService,
    CreditReservationState,
    InvalidCreditQuote,
)
from flowx_os.db.credit_reservations import (
    CreditAccountIneligible,
    CreditBalanceUnknown,
    CreditLimitExceeded,
    CreditReservationConflict,
    FlowCreditReservationRepository,
)


NOW = datetime(2026, 11, 19, 0, 35, tzinfo=timezone.utc)
ACCOUNT_ID = UUID("1090bf84-9d8a-4a0b-91cb-0ee53c8d649d")
REQUEST_ID = UUID("2190bf84-9d8a-4a0b-91cb-0ee53c8d649d")
RESERVATION_ID = UUID("3290bf84-9d8a-4a0b-91cb-0ee53c8d649d")
QUOTE = CreditQuoteEvidence(
    quote_ref="quote-1", account_ref=str(ACCOUNT_ID), request_id=REQUEST_ID,
    model_name="veo-model", duration_seconds=8, quoted_credits=7,
    source=CreditQuoteSource.FLOW_QUOTE, quoted_at=NOW - timedelta(seconds=15),
    expires_at=NOW + timedelta(minutes=2),
)
RESERVATION_ROW = (
    RESERVATION_ID, ACCOUNT_ID, REQUEST_ID, "veo-model", 8, "quote-1", 7,
    "FLOW_QUOTE", NOW - timedelta(seconds=15), NOW + timedelta(minutes=2),
    "RESERVED", NOW,
)


class FakeCursor:
    def __init__(self, one=None):
        self.one = one

    async def fetchone(self):
        return self.one


class FakeConnection:
    def __init__(self, responses, on_execute=None):
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
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakePool:
    def __init__(self, connection):
        self.value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.value


class FakeQuoteProvider:
    def __init__(self, quote=QUOTE, error=None):
        self.quote = quote
        self.error = error
        self.requests = []

    async def get_quote(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.quote


class FakeApprover:
    def __init__(self, allowed=True, error=None):
        self.allowed = allowed
        self.error = error
        self.calls = []

    async def is_authorized(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.allowed


class FakeStore:
    def __init__(self, result=None, owned_error=None):
        self.result = result or record()
        self.owned_error = owned_error
        self.ownership_calls = []
        self.calls = []

    async def assert_account_owned(self, **kwargs):
        self.ownership_calls.append(kwargs)
        if self.owned_error:
            raise self.owned_error

    async def reserve(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeReservationService:
    async def reserve(self, **kwargs):
        return record()


def account_row(
    *, health="HEALTHY", paused=False, compliance=True, daily=50, monthly=200,
    reconciled=NOW - timedelta(minutes=1), daily_reset=NOW + timedelta(hours=5),
    cycle_start=NOW - timedelta(days=5), max_inflight=2,
):
    return (health, paused, compliance, daily, monthly, reconciled, daily_reset, cycle_start, max_inflight)


def record():
    return CreditReservationRecord(
        RESERVATION_ID, ACCOUNT_ID, REQUEST_ID, "veo-model", 8, "quote-1", 7,
        CreditQuoteSource.FLOW_QUOTE, NOW - timedelta(seconds=15),
        NOW + timedelta(minutes=2), CreditReservationState.RESERVED, NOW,
    )


def make_service(provider=None, approver=None, store=None, **kwargs):
    return CreditReservationService(
        store or FakeStore(), provider, approver,
        max_credits_per_request=20, now=lambda: NOW, **kwargs,
    )


class CreditReservationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_reservation_requires_quote_approval_and_policy_ceiling(self):
        provider, approver, store = FakeQuoteProvider(), FakeApprover(), FakeStore()
        result = await make_service(provider, approver, store).reserve(
            account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
            model_name="veo-model", duration_seconds=8, approval_ref="approval-1",
        )
        self.assertEqual(result, record())
        self.assertEqual(provider.requests[0].account_ref, str(ACCOUNT_ID))
        self.assertEqual(approver.calls[0]["max_allowed_credits"], 7)
        self.assertEqual(store.ownership_calls[0], {"account_id": ACCOUNT_ID, "owner_user_id": "owner-1"})
        self.assertEqual(store.calls[0]["quote"], QUOTE)

    async def test_foreign_account_is_rejected_before_quote_or_approval_provider(self):
        from flowx_os.db.flow_accounts import OwnedFlowAccountNotFound

        provider, approver, store = FakeQuoteProvider(), FakeApprover(), FakeStore(
            owned_error=OwnedFlowAccountNotFound("Flow account not found")
        )
        with self.assertRaises(OwnedFlowAccountNotFound):
            await make_service(provider, approver, store).reserve(
                account_id=ACCOUNT_ID, owner_user_id="owner-2", request_id=REQUEST_ID,
                model_name="veo-model", duration_seconds=8, approval_ref="approval-1",
            )
        self.assertEqual(provider.requests, [])
        self.assertEqual(approver.calls, [])
        self.assertEqual(store.calls, [])

    async def test_missing_quote_provider_fails_closed_without_store_call(self):
        store = FakeStore()
        with self.assertRaises(CreditQuoteUnavailable):
            await make_service(None, FakeApprover(), store).reserve(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                model_name="veo-model", duration_seconds=8, approval_ref="approval-1",
            )
        self.assertEqual(store.calls, [])

    async def test_provider_exception_is_sanitized(self):
        with self.assertRaises(CreditQuoteUnavailable) as raised:
            await make_service(FakeQuoteProvider(error=RuntimeError("private provider response")), FakeApprover()).reserve(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                model_name="veo-model", duration_seconds=8, approval_ref="approval-1",
            )
        self.assertNotIn("private provider response", str(raised.exception))

    async def test_quote_must_match_exact_request_and_stay_within_ceiling(self):
        wrong_request = CreditQuoteEvidence(
            quote_ref=QUOTE.quote_ref,
            account_ref=QUOTE.account_ref,
            request_id=UUID("4390bf84-9d8a-4a0b-91cb-0ee53c8d649d"),
            model_name=QUOTE.model_name,
            duration_seconds=QUOTE.duration_seconds,
            quoted_credits=QUOTE.quoted_credits,
            source=QUOTE.source,
            quoted_at=QUOTE.quoted_at,
            expires_at=QUOTE.expires_at,
        )
        store = FakeStore()
        with self.assertRaises(InvalidCreditQuote):
            await make_service(FakeQuoteProvider(wrong_request), FakeApprover(), store).reserve(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                model_name="veo-model", duration_seconds=8, approval_ref="approval-1",
            )
        self.assertEqual(store.calls, [])

    async def test_expired_and_over_ceiling_quotes_fail_before_approval(self):
        expired = CreditQuoteEvidence(
            "q", str(ACCOUNT_ID), REQUEST_ID, "veo-model", 8, 7,
            CreditQuoteSource.FLOW_QUOTE, NOW - timedelta(minutes=10), NOW - timedelta(seconds=1),
        )
        approver = FakeApprover()
        with self.assertRaises(InvalidCreditQuote):
            await make_service(FakeQuoteProvider(expired), approver).reserve(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                model_name="veo-model", duration_seconds=8, approval_ref="approval-1",
            )
        too_expensive = CreditQuoteEvidence(
            "q", str(ACCOUNT_ID), REQUEST_ID, "veo-model", 8, 21,
            CreditQuoteSource.FLOW_QUOTE, NOW - timedelta(seconds=10), NOW + timedelta(minutes=1),
        )
        with self.assertRaises(InvalidCreditQuote):
            await make_service(FakeQuoteProvider(too_expensive), approver).reserve(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                model_name="veo-model", duration_seconds=8, approval_ref="approval-1",
            )
        self.assertEqual(approver.calls, [])

    async def test_approval_is_required_and_approval_backend_errors_fail_closed(self):
        for approver, expected in (
            (FakeApprover(allowed=False), CreditApprovalRequired),
            (FakeApprover(error=RuntimeError("private approval backend")), CreditApprovalUnavailable),
        ):
            store = FakeStore()
            with self.subTest(expected=expected.__name__), self.assertRaises(expected):
                await make_service(FakeQuoteProvider(), approver, store).reserve(
                    account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                    model_name="veo-model", duration_seconds=8, approval_ref="approval-1",
                )
            self.assertEqual(store.calls, [])


class CreditReservationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def repository(self, responses, *, now=None, on_execute=None):
        connection = FakeConnection(responses, on_execute=on_execute)
        return FlowCreditReservationRepository(FakePool(connection), now=now or (lambda: NOW)), connection

    async def test_owner_preflight_scopes_account_before_external_quote(self):
        repository, connection = self.repository([FakeCursor(one=(1,))])
        await repository.assert_account_owned(account_id=ACCOUNT_ID, owner_user_id="owner-1")
        self.assertEqual(connection.queries[0][1], (ACCOUNT_ID, "owner-1"))
        self.assertIn("owner_user_id = %s", connection.queries[0][0])

    async def test_owner_preflight_hides_foreign_account(self):
        from flowx_os.db.flow_accounts import OwnedFlowAccountNotFound

        repository, _ = self.repository([FakeCursor(one=None)])
        with self.assertRaises(OwnedFlowAccountNotFound):
            await repository.assert_account_owned(account_id=ACCOUNT_ID, owner_user_id="owner-2")

    async def test_reserve_locks_account_and_checks_limits_before_insert(self):
        repository, connection = self.repository([
            FakeCursor(one=account_row()),
            FakeCursor(one=None),
            FakeCursor(one=(0, 0)),
            FakeCursor(one=RESERVATION_ROW),
        ])
        result = await repository.reserve(
            account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
            quote=QUOTE, now=NOW, max_quote_age=timedelta(minutes=5), max_balance_age=timedelta(minutes=15),
        )
        self.assertEqual(result, record())
        self.assertIn("FOR UPDATE", connection.queries[0][0])
        self.assertEqual(connection.queries[0][1], (ACCOUNT_ID, "owner-1"))
        self.assertIn("state IN ('RESERVED', 'RECONCILE_PENDING')", connection.queries[2][0])
        self.assertIn("ON CONFLICT (flow_account_id, request_id) DO NOTHING", connection.queries[3][0])

    async def test_unverified_or_paused_account_cannot_reserve(self):
        for row in (account_row(health="UNVERIFIED"), account_row(paused=True), account_row(compliance=False)):
            repository, connection = self.repository([FakeCursor(one=row), FakeCursor(one=None)])
            with self.assertRaises(CreditAccountIneligible):
                await repository.reserve(
                    account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                    quote=QUOTE, now=NOW, max_quote_age=timedelta(minutes=5), max_balance_age=timedelta(minutes=15),
                )
            self.assertEqual(len(connection.queries), 2)

    async def test_missing_or_stale_balance_fails_closed(self):
        for row in (
            account_row(daily=None),
            account_row(reconciled=NOW - timedelta(hours=1)),
            account_row(daily_reset=NOW - timedelta(seconds=1)),
            account_row(reconciled=NOW - timedelta(days=6), cycle_start=NOW - timedelta(days=5)),
        ):
            repository, _ = self.repository([FakeCursor(one=row), FakeCursor(one=None)])
            with self.assertRaises(CreditBalanceUnknown):
                await repository.reserve(
                    account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                    quote=QUOTE, now=NOW, max_quote_age=timedelta(minutes=5), max_balance_age=timedelta(minutes=15),
                )

    async def test_active_reservations_reduce_both_wallet_limits_and_inflight_slots(self):
        repository, connection = self.repository([
            FakeCursor(one=account_row(daily=10, monthly=10, max_inflight=2)),
            FakeCursor(one=None),
            FakeCursor(one=(1, 5)),
        ])
        with self.assertRaises(CreditLimitExceeded):
            await repository.reserve(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                quote=QUOTE, now=NOW, max_quote_age=timedelta(minutes=5), max_balance_age=timedelta(minutes=15),
            )
        self.assertEqual(len(connection.queries), 3)

    async def test_active_reservation_count_enforces_account_concurrency(self):
        repository, _ = self.repository([
            FakeCursor(one=account_row(max_inflight=1)),
            FakeCursor(one=None),
            FakeCursor(one=(1, 2)),
        ])
        with self.assertRaises(CreditLimitExceeded):
            await repository.reserve(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                quote=QUOTE, now=NOW, max_quote_age=timedelta(minutes=5), max_balance_age=timedelta(minutes=15),
            )

    async def test_quote_expiry_is_rechecked_after_database_wait(self):
        current = [NOW]

        def advance_after_active_count(query):
            if "SELECT COUNT(*)" in query:
                current[0] = NOW + timedelta(minutes=3)

        repository, connection = self.repository([
            FakeCursor(one=account_row()), FakeCursor(one=None), FakeCursor(one=(0, 0)),
        ], now=lambda: current[0], on_execute=advance_after_active_count)
        with self.assertRaises(CreditBalanceUnknown):
            await repository.reserve(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                quote=QUOTE, now=NOW, max_quote_age=timedelta(minutes=5), max_balance_age=timedelta(minutes=15),
            )
        self.assertEqual(len(connection.queries), 3)

    async def test_quote_maximum_age_is_rechecked_after_database_wait(self):
        current = [NOW]

        def advance_after_active_count(query):
            if "SELECT COUNT(*)" in query:
                current[0] = NOW + timedelta(minutes=2)

        quote = CreditQuoteEvidence(
            "long-lived", str(ACCOUNT_ID), REQUEST_ID, "veo-model", 8, 7,
            CreditQuoteSource.FLOW_QUOTE, NOW - timedelta(minutes=4), NOW + timedelta(hours=1),
        )
        repository, connection = self.repository([
            FakeCursor(one=account_row()), FakeCursor(one=None), FakeCursor(one=(0, 0)),
        ], now=lambda: current[0], on_execute=advance_after_active_count)
        with self.assertRaises(CreditBalanceUnknown):
            await repository.reserve(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                quote=quote, now=NOW, max_quote_age=timedelta(minutes=5),
                max_balance_age=timedelta(minutes=15),
            )
        self.assertEqual(len(connection.queries), 3)

    async def test_balance_freshness_is_rechecked_after_database_wait(self):
        current = [NOW]

        def advance_after_active_count(query):
            if "SELECT COUNT(*)" in query:
                current[0] = NOW + timedelta(minutes=20)

        quote = CreditQuoteEvidence(
            "long-lived", str(ACCOUNT_ID), REQUEST_ID, "veo-model", 8, 7,
            CreditQuoteSource.FLOW_QUOTE, NOW - timedelta(seconds=10), NOW + timedelta(hours=1),
        )
        repository, connection = self.repository([
            FakeCursor(one=account_row()), FakeCursor(one=None), FakeCursor(one=(0, 0)),
        ], now=lambda: current[0], on_execute=advance_after_active_count)
        with self.assertRaises(CreditBalanceUnknown):
            await repository.reserve(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                quote=quote, now=NOW, max_quote_age=timedelta(minutes=5), max_balance_age=timedelta(minutes=15),
            )
        self.assertEqual(len(connection.queries), 3)

    async def test_idempotent_request_returns_existing_reservation_without_inserting(self):
        repository, connection = self.repository([
            FakeCursor(one=account_row(health="UNVERIFIED", paused=True)),
            FakeCursor(one=RESERVATION_ROW),
        ])
        result = await repository.reserve(
            account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
            quote=QUOTE, now=NOW, max_quote_age=timedelta(minutes=5), max_balance_age=timedelta(minutes=15),
        )
        self.assertEqual(result, record())
        self.assertEqual(len(connection.queries), 2)

    async def test_reused_request_id_with_changed_quote_is_rejected(self):
        changed = CreditQuoteEvidence(
            "quote-other", str(ACCOUNT_ID), REQUEST_ID, "veo-model", 8, 8,
            CreditQuoteSource.FLOW_QUOTE, NOW - timedelta(seconds=10), NOW + timedelta(minutes=1),
        )
        repository, _ = self.repository([FakeCursor(one=account_row()), FakeCursor(one=RESERVATION_ROW)])
        with self.assertRaises(CreditReservationConflict):
            await repository.reserve(
                account_id=ACCOUNT_ID, owner_user_id="owner-1", request_id=REQUEST_ID,
                quote=changed, now=NOW, max_quote_age=timedelta(minutes=5), max_balance_age=timedelta(minutes=15),
            )


class CreditReservationApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_reservation_route_is_unavailable_without_quote_service(self):
        verifier, token = make_auth()
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(
                token_verifier=verifier,
                database_pool=FakePool(FakeConnection([])),
            )),
            base_url="http://testserver", headers={"Authorization": f"Bearer {token}"},
        )
        async with client:
            response = await client.post(
                f"/api/v1/flow-accounts/{ACCOUNT_ID}/credit-reservations",
                json={"request_id": str(REQUEST_ID), "model_name": "veo-model", "duration_seconds": 8, "approval_ref": "approval-1"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "credit_quote_unavailable")

    async def test_response_model_omits_owner_and_credential_references(self):
        verifier, token = make_auth()
        service = FakeReservationService()
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(
                token_verifier=verifier,
                database_pool=FakePool(FakeConnection([])),
                credit_reservation_service=service,
            )),
            base_url="http://testserver", headers={"Authorization": f"Bearer {token}"},
        )
        async with client:
            response = await client.post(
                f"/api/v1/flow-accounts/{ACCOUNT_ID}/credit-reservations",
                json={"request_id": str(REQUEST_ID), "model_name": "veo-model", "duration_seconds": 8, "approval_ref": "approval-1"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "RESERVED")
        self.assertNotIn("owner_user_id", response.json())
        self.assertNotIn("credentials_ref", response.json())


def make_auth():
    key = b"test-key-that-is-long-enough-for-hmac"
    verifier = TokenVerifier(key, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({
        "iss": "flowx-test", "aud": "flowx-api", "sub": "owner-1",
        "roles": ["operator"], "iat": now - 1, "nbf": now - 1, "exp": now + 60,
    }).encode())
    signing_input = f"{header}.{claims}"
    signature = _b64(hmac.new(key, signing_input.encode("ascii"), hashlib.sha256).digest())
    return verifier, f"{signing_input}.{signature}"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


if __name__ == "__main__":
    unittest.main()
