from datetime import datetime, timedelta, timezone
import unittest
from uuid import uuid4

from flowx_os.credits.reservations import (
    CreditQuoteSource,
    CreditReservationRecord,
    CreditReservationState,
)
from flowx_os.domain.scene_jobs import SceneJobState
from flowx_os.qa.retry_gate import (
    RetryGateReason,
    SceneRetryGateDecision,
    SceneRetrySpendGateService,
)


NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def reservation(*, state=CreditReservationState.RESERVED):
    return CreditReservationRecord(
        uuid4(), uuid4(), uuid4(), "veo-3.1-lite", 8, "quote-1", 3,
        CreditQuoteSource.FLOW_QUOTE, NOW - timedelta(minutes=1),
        NOW + timedelta(minutes=4), state, NOW - timedelta(minutes=1),
    )


class Store:
    def __init__(self, existing=None):
        self.events = []
        self.record = None
        self.existing = existing

    async def assert_failure_owned(self, *, job_id, owner_user_id):
        self.events.append(("preflight", job_id, owner_user_id))
        return self.existing

    async def record_failure_retry_gate(self, **kwargs):
        self.events.append(("record", kwargs["job_id"], kwargs["owner_user_id"]))
        self.record = kwargs
        evidence = kwargs["spend_evidence"]
        return SceneRetryGateDecision(
            uuid4(), kwargs["job_id"], 1, 1 if evidence else 0,
            SceneJobState.RETRY_WAIT if evidence else SceneJobState.FAILED,
            evidence is not None, kwargs["denial_reason"],
            evidence.reservation_id if evidence else None,
            evidence.approval_fingerprint if evidence else None,
        )


class Authorizer:
    def __init__(self, result=True, error=None, events=None):
        self.result = result
        self.error = error
        self.calls = []
        self.events = events

    async def is_authorized(self, **kwargs):
        if self.events is not None:
            self.events.append(("authorize", kwargs["account_ref"]))
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class RetrySpendGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_reserved_approval_creates_hashed_spend_evidence(self):
        store = Store()
        auth = Authorizer(events=store.events)
        value = reservation()
        result = await SceneRetrySpendGateService(
            store, auth, now=lambda: NOW,
        ).record_failure(
            job_id=uuid4(), owner_user_id="owner-1", retryable=True,
            failure_code="QA_FAILED", reservation=value,
            approval_ref="approval:retry-1",
        )
        self.assertTrue(result.retry_scheduled)
        self.assertEqual(result.reason, RetryGateReason.ELIGIBLE)
        self.assertEqual([event[0] for event in store.events], ["preflight", "authorize", "record"])
        self.assertEqual(auth.calls[0]["account_ref"], str(value.flow_account_id))
        self.assertEqual(auth.calls[0]["max_allowed_credits"], value.quoted_credits)
        self.assertEqual(store.record["spend_evidence"].approval_fingerprint.__len__(), 64)
        self.assertNotIn("approval:retry-1", repr(store.record["spend_evidence"]))

    async def test_missing_or_reconciling_reservation_denies_without_provider(self):
        for value, reason in [
            (None, RetryGateReason.RESERVATION_UNAVAILABLE),
            (reservation(state=CreditReservationState.RECONCILE_PENDING),
             RetryGateReason.SPEND_STATE_INVALID),
        ]:
            store, auth = Store(), Authorizer()
            result = await SceneRetrySpendGateService(store, auth, now=lambda: NOW).record_failure(
                job_id=uuid4(), owner_user_id="owner-1", retryable=True,
                failure_code="QA_FAILED", reservation=value,
                approval_ref="approval:retry-1",
            )
            self.assertFalse(result.retry_scheduled)
            self.assertEqual(result.reason, reason)
            self.assertEqual(auth.calls, [])

    async def test_missing_rejected_or_unavailable_approval_is_durable_denial(self):
        cases = [
            (None, None, RetryGateReason.APPROVAL_REQUIRED),
            (Authorizer(False), "approval:retry-1", RetryGateReason.APPROVAL_REJECTED),
            (Authorizer(error=RuntimeError("private provider detail")),
             "approval:retry-1", RetryGateReason.APPROVAL_UNAVAILABLE),
        ]
        for auth, approval_ref, reason in cases:
            store = Store()
            result = await SceneRetrySpendGateService(store, auth, now=lambda: NOW).record_failure(
                job_id=uuid4(), owner_user_id="owner-1", retryable=True,
                failure_code="QA_FAILED", reservation=reservation(),
                approval_ref=approval_ref,
            )
            self.assertEqual(result.reason, reason)
            self.assertIsNone(store.record["spend_evidence"])

    async def test_nonretryable_failure_skips_spend_provider(self):
        store, auth = Store(), Authorizer()
        result = await SceneRetrySpendGateService(store, auth, now=lambda: NOW).record_failure(
            job_id=uuid4(), owner_user_id="owner-1", retryable=False,
            failure_code="POLICY_BLOCKED", reservation=reservation(),
            approval_ref="approval:retry-1",
        )
        self.assertEqual(result.reason, RetryGateReason.FAILURE_NOT_RETRYABLE)
        self.assertEqual(auth.calls, [])

    async def test_existing_decision_replays_without_approval_provider(self):
        job_id = uuid4()
        existing = SceneRetryGateDecision(
            uuid4(), job_id, 1, 1, SceneJobState.RETRY_WAIT, True,
            RetryGateReason.ELIGIBLE, uuid4(), "a" * 64,
        )
        store, auth = Store(existing), Authorizer(error=RuntimeError("must not run"))
        result = await SceneRetrySpendGateService(store, auth, now=lambda: NOW).record_failure(
            job_id=job_id, owner_user_id="owner-1", retryable=True,
            failure_code="QA_FAILED", reservation=reservation(),
            approval_ref="approval:retry-1",
        )
        self.assertEqual(result, existing)
        self.assertEqual(auth.calls, [])
        self.assertIsNone(store.record)

    async def test_invalid_identity_fails_before_preflight(self):
        store = Store()
        with self.assertRaises(ValueError):
            await SceneRetrySpendGateService(store, Authorizer()).record_failure(
                job_id=uuid4(), owner_user_id="owner\nspoof", retryable=True,
                failure_code="QA_FAILED",
            )
        self.assertEqual(store.events, [])

    async def test_owner_preflight_failure_prevents_approval_provider_call(self):
        class RejectingStore(Store):
            async def assert_failure_owned(self, *, job_id, owner_user_id):
                raise RuntimeError("owner-scoped job is unavailable")

        auth = Authorizer()
        with self.assertRaises(RuntimeError):
            await SceneRetrySpendGateService(
                RejectingStore(), auth, now=lambda: NOW,
            ).record_failure(
                job_id=uuid4(), owner_user_id="owner-1", retryable=True,
                failure_code="QA_FAILED", reservation=reservation(),
                approval_ref="approval:retry-1",
            )
        self.assertEqual(auth.calls, [])


if __name__ == "__main__":
    unittest.main()
