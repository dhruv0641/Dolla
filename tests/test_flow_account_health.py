from datetime import datetime, timedelta, timezone
import unittest

from flowx_os.flow_mcp import (
    AccountHealthState,
    AdapterErrorCode,
    FlowAccountHealthSnapshot,
    FlowAccountHealthService,
    FlowAdapterError,
    inspect_flow_account_health,
)


NOW = datetime(2026, 11, 18, 17, 15, tzinfo=timezone.utc)


class FlowAccountHealthTests(unittest.IsolatedAsyncioTestCase):
    def snapshot(self, **overrides):
        values = {
            "connected": True,
            "logged_in": True,
            "identity_verified": True,
            "account_ref": "acct-primary",
            "checked_at": NOW,
        }
        values.update(overrides)
        return FlowAccountHealthSnapshot(**values)

    def inspect(self, snapshot):
        return inspect_flow_account_health(
            snapshot,
            expected_account_ref="acct-primary",
            now=NOW,
            max_age=timedelta(minutes=5),
        )

    async def test_ready_requires_fresh_connected_logged_in_and_verified_matching_identity(self):
        result = self.inspect(self.snapshot())
        self.assertEqual(result.state, AccountHealthState.READY)
        service = FlowAccountHealthService(
            FakeHealthProvider(self.snapshot()), expected_account_ref="acct-primary", now=lambda: NOW
        )
        authorization = await service.authorize()
        self.assertTrue(authorization.verified)
        self.assertEqual(authorization.account_ref, "acct-primary")
        self.assertEqual(authorization.valid_until, NOW + timedelta(minutes=5))
        self.assertEqual(set(result.to_payload()), {"status", "checked_at", "account_ref"})

    async def test_login_does_not_imply_identity_verification(self):
        result = self.inspect(self.snapshot(identity_verified=False, account_ref=None))
        self.assertEqual(result.state, AccountHealthState.IDENTITY_UNVERIFIED)
        service = FlowAccountHealthService(
            FakeHealthProvider(self.snapshot(identity_verified=False, account_ref=None)),
            expected_account_ref="acct-primary", now=lambda: NOW,
        )
        with self.assertRaises(FlowAdapterError) as caught:
            await service.authorize()
        self.assertEqual(caught.exception.code, AdapterErrorCode.ACCOUNT_UNVERIFIED)

    async def test_disconnected_logged_out_stale_and_wrong_account_all_deny(self):
        cases = [
            (self.snapshot(connected=False), AccountHealthState.DISCONNECTED, AdapterErrorCode.ACCOUNT_DISCONNECTED),
            (self.snapshot(logged_in=False), AccountHealthState.LOGGED_OUT, AdapterErrorCode.ACCOUNT_NOT_LOGGED_IN),
            (self.snapshot(checked_at=NOW - timedelta(minutes=6)), AccountHealthState.STALE, AdapterErrorCode.ACCOUNT_HEALTH_STALE),
            (self.snapshot(account_ref="acct-secondary"), AccountHealthState.ACCOUNT_MISMATCH, AdapterErrorCode.ACCOUNT_MISMATCH),
        ]
        for snapshot, state, code in cases:
            with self.subTest(state=state):
                result = self.inspect(snapshot)
                self.assertEqual(result.state, state)
                service = FlowAccountHealthService(
                    FakeHealthProvider(snapshot), expected_account_ref="acct-primary", now=lambda: NOW
                )
                with self.assertRaises(FlowAdapterError) as caught:
                    await service.authorize()
                self.assertEqual(caught.exception.code, code)

    def test_future_evidence_and_email_based_account_references_are_rejected(self):
        result = self.inspect(self.snapshot(checked_at=NOW + timedelta(seconds=1)))
        self.assertEqual(result.state, AccountHealthState.STALE)
        with self.assertRaises(ValueError):
            self.snapshot(account_ref="user@example.com")

    def test_health_payload_contains_no_provider_error_or_account_email(self):
        result = self.inspect(self.snapshot())
        payload = result.to_payload()
        self.assertNotIn("email", str(payload).lower())
        self.assertNotIn("cookie", str(payload).lower())


class FakeHealthProvider:
    def __init__(self, snapshot=None, error=None):
        self.snapshot = snapshot
        self.error = error

    async def get_snapshot(self):
        if self.error:
            raise self.error
        return self.snapshot


class FlowAccountHealthServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_exception_and_missing_evidence_are_unavailable(self):
        for provider in (FakeHealthProvider(), FakeHealthProvider(error=RuntimeError("private"))):
            service = FlowAccountHealthService(provider, expected_account_ref="acct-primary", now=lambda: NOW)
            result = await service.inspect()
            self.assertEqual(result.state, AccountHealthState.UNAVAILABLE)
            with self.assertRaises(FlowAdapterError) as caught:
                await service.authorize()
            self.assertEqual(caught.exception.code, AdapterErrorCode.ACCOUNT_HEALTH_UNAVAILABLE)

    async def test_provider_evidence_is_revalidated_before_authorization(self):
        service = FlowAccountHealthService(
            FakeHealthProvider(FlowAccountHealthSnapshot(True, True, True, "acct-secondary", NOW)),
            expected_account_ref="acct-primary",
            now=lambda: NOW,
        )
        with self.assertRaises(FlowAdapterError) as caught:
            await service.authorize()
        self.assertEqual(caught.exception.code, AdapterErrorCode.ACCOUNT_MISMATCH)

    async def test_malformed_provider_result_is_unavailable(self):
        service = FlowAccountHealthService(
            FakeHealthProvider({"connected": True}), expected_account_ref="acct-primary", now=lambda: NOW
        )
        self.assertEqual((await service.inspect()).state, AccountHealthState.UNAVAILABLE)
        with self.assertRaises(FlowAdapterError) as caught:
            await service.authorize()
        self.assertEqual(caught.exception.code, AdapterErrorCode.ACCOUNT_HEALTH_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
