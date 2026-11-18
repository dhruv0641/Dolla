import base64
import hashlib
import hmac
import json
import time
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID

import httpx

from flowx_os.api.main import create_app
from flowx_os.auth.tokens import TokenVerifier
from flowx_os.db.flow_accounts import (
    FlowAccountAliasConflict,
    FlowAccountRepository,
    OwnedFlowAccountNotFound,
)


ACCOUNT_ID = UUID("cc90bf84-9d8a-4a0b-91cb-0ee53c8d649d")
CREATED_AT = datetime(2026, 11, 19, tzinfo=timezone.utc)
SECRET_REF = "secretref://local/flow/primary"


def account_row(owner: str = "operator-1"):
    return (
        ACCOUNT_ID, "Primary", owner, "google_flow_via_user_authorized_mcp", None,
        None, None, None, None, None, None, None, "UNVERIFIED", True, False, 1, CREATED_AT,
    )


class FakeCursor:
    def __init__(self, one=None, many=None):
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


def make_token(*, roles=("operator",), subject="operator-1"):
    key = b"test-key-that-is-long-enough-for-hmac"
    verifier = TokenVerifier(key, issuer="flowx-test", audience="flowx-api", clock_skew_seconds=0)
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({
        "iss": "flowx-test", "aud": "flowx-api", "sub": subject,
        "roles": list(roles), "iat": now - 1, "nbf": now - 1, "exp": now + 60,
    }).encode())
    signing_input = f"{header}.{claims}"
    signature = _b64(hmac.new(key, signing_input.encode("ascii"), hashlib.sha256).digest())
    return verifier, f"{signing_input}.{signature}"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


class FlowAccountRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_persists_unverified_paused_account_and_omits_secret_in_record(self):
        connection = FakeConnection([FakeCursor(one=account_row())])
        result = await FlowAccountRepository(FakePool(connection)).register(
            owner_user_id="operator-1", alias="Primary", credentials_ref=SECRET_REF,
            mcp_adapter="google_flow_via_user_authorized_mcp",
        )

        query, params = connection.queries[0]
        self.assertIn("'UNVERIFIED', TRUE, FALSE", query)
        self.assertIn("ON CONFLICT (owner_user_id, alias) DO NOTHING", query)
        self.assertNotIn("credentials_ref", query.split("RETURNING", 1)[1])
        self.assertEqual(params, ("Primary", "operator-1", SECRET_REF, "google_flow_via_user_authorized_mcp"))
        self.assertTrue(result.paused)
        self.assertFalse(result.compliance_approved)
        self.assertEqual(result.session_health, "UNVERIFIED")
        self.assertFalse(hasattr(result, "credentials_ref"))

    async def test_duplicate_alias_is_reported_without_database_error_detail(self):
        connection = FakeConnection([FakeCursor(one=None)])
        with self.assertRaises(FlowAccountAliasConflict):
            await FlowAccountRepository(FakePool(connection)).register(
                owner_user_id="operator-1", alias="Primary", credentials_ref=SECRET_REF,
                mcp_adapter="google_flow_via_user_authorized_mcp",
            )

    async def test_list_is_owner_scoped_and_does_not_select_secret_reference(self):
        connection = FakeConnection([FakeCursor(many=[account_row()])])
        records = await FlowAccountRepository(FakePool(connection)).list_for_owner(owner_user_id="operator-1")
        query, params = connection.queries[0]
        self.assertIn("WHERE owner_user_id = %s", query)
        self.assertNotIn("credentials_ref", query)
        self.assertEqual(params, ("operator-1",))
        self.assertEqual(records[0].owner_user_id, "operator-1")

    async def test_pause_is_owner_scoped_and_only_moves_toward_safer_state(self):
        connection = FakeConnection([FakeCursor(one=account_row())])
        result = await FlowAccountRepository(FakePool(connection)).pause(
            account_id=ACCOUNT_ID, owner_user_id="operator-1"
        )
        query, params = connection.queries[0]
        self.assertIn("SET paused = TRUE", query)
        self.assertIn("id = %s AND owner_user_id = %s", query)
        self.assertEqual(params, (ACCOUNT_ID, "operator-1"))
        self.assertTrue(result.paused)

    async def test_pause_hides_absent_and_foreign_accounts_as_not_found(self):
        connection = FakeConnection([FakeCursor(one=None)])
        with self.assertRaises(OwnedFlowAccountNotFound):
            await FlowAccountRepository(FakePool(connection)).pause(
                account_id=ACCOUNT_ID, owner_user_id="other-owner"
            )


class FlowAccountApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.verifier, self.token = make_token()

    async def client_for(self, pool):
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=self.verifier, database_pool=pool)),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.addAsyncCleanup(client.aclose)
        return client

    async def test_create_returns_paused_unverified_state_without_secret_reference(self):
        connection = FakeConnection([FakeCursor(one=account_row())])
        client = await self.client_for(FakePool(connection))
        response = await client.post("/api/v1/flow-accounts", json={"alias": "Primary", "credentials_ref": SECRET_REF})

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["session_health"], "UNVERIFIED")
        self.assertTrue(payload["paused"])
        self.assertFalse(payload["compliance_approved"])
        self.assertNotIn("credentials_ref", payload)

    async def test_raw_credentials_are_rejected_without_echo(self):
        client = await self.client_for(FakePool(FakeConnection([])))
        response = await client.post(
            "/api/v1/flow-accounts", json={"alias": "Primary", "credentials_ref": "token-secret-123"}
        )

        self.assertEqual(response.status_code, 422)
        self.assertNotIn("token-secret-123", response.text)

    async def test_duplicate_alias_returns_conflict(self):
        connection = FakeConnection([FakeCursor(one=None)])
        client = await self.client_for(FakePool(connection))
        response = await client.post("/api/v1/flow-accounts", json={"alias": "Primary", "credentials_ref": SECRET_REF})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "flow_account_alias_unavailable")

    async def test_account_listing_scopes_records_to_principal(self):
        connection = FakeConnection([FakeCursor(many=[account_row()])])
        client = await self.client_for(FakePool(connection))
        response = await client.get("/api/v1/flow-accounts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(connection.queries[0][1], ("operator-1",))

    async def test_pause_route_only_applies_owner_scoped_pause(self):
        connection = FakeConnection([FakeCursor(one=account_row())])
        client = await self.client_for(FakePool(connection))
        response = await client.post(f"/api/v1/flow-accounts/{ACCOUNT_ID}/pause")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["paused"])
        self.assertEqual(connection.queries[0][1], (ACCOUNT_ID, "operator-1"))

    async def test_reviewer_role_cannot_manage_flow_accounts(self):
        verifier, token = make_token(roles=("reviewer",))
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(token_verifier=verifier, database_pool=FakePool(FakeConnection([])))),
            base_url="http://testserver", headers={"Authorization": f"Bearer {token}"},
        )
        async with client:
            response = await client.get("/api/v1/flow-accounts")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
