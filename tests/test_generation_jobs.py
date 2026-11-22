from contextlib import asynccontextmanager
from uuid import uuid4
import unittest
from datetime import datetime, timedelta, timezone

from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.generation_jobs import FlowGenerationJobRepository
from flowx_os.flow_mcp import JobSubmissionRequest
from flowx_os.flow_mcp import PersistedJobResumeContext
from flowx_os.domain.scene_jobs import SceneJobState, SceneRetryPolicy
from flowx_os.qa.retry_gate import RetryGateReason, RetrySpendEvidence


class FakeCursor:
    def __init__(self, row=None, rowcount=1):
        self.row = row
        self.rowcount = rowcount

    async def fetchone(self):
        return self.row

    async def fetchall(self):
        return []


class FakeConnection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, query, params=None):
        self.calls.append((query, params))
        row = self.rows.pop(0) if self.rows else None
        return FakeCursor(row)


class FakePool:
    def __init__(self, connection):
        self._connection = connection

    @asynccontextmanager
    async def connection(self):
        yield self._connection


def request(attempt_index=1):
    return JobSubmissionRequest(
        scene_id=uuid4(), request_id=uuid4(), owner_user_id="owner-1", attempt_index=attempt_index,
        model="veo-3.1-lite", prompt="A scene", duration_seconds=8, quoted_credits=2,
        arguments={"auto_confirm": True, "prompt": "A scene", "model": "veo-3.1-lite", "duration": 8,
                   "ratio": "9:16",
                   "project_url": "https://labs.google/fx/tools/flow", "output_dir": "C:/flow-output"},
        settings={"aspect_ratio": "9:16"},
    )


class FlowGenerationJobRepositoryTests(unittest.IsolatedAsyncioTestCase):
    NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)

    @classmethod
    def eligible_row(cls, reservation_id, account_id, credits=2, **overrides):
        values = {
            "quoted_at": cls.NOW - timedelta(minutes=1),
            "quote_expires_at": cls.NOW + timedelta(minutes=5),
            "health": "HEALTHY", "paused": False, "compliant": True,
            "daily": 20, "monthly": 50,
            "reconciled": cls.NOW - timedelta(minutes=1),
            "daily_reset": cls.NOW + timedelta(hours=8),
            "cycle_start": cls.NOW - timedelta(days=2), "max_inflight": 1,
        }
        values.update(overrides)
        return (reservation_id, account_id, credits, values["quoted_at"], values["quote_expires_at"],
                values["health"], values["paused"], values["compliant"], values["daily"],
                values["monthly"], values["reconciled"], values["daily_reset"],
                values["cycle_start"], values["max_inflight"],
                values.get("scene_state", "PENDING"), values.get("scene_retry_count", 0))

    @classmethod
    def retry_account_row(cls):
        return (
            "HEALTHY", False, True, 20, 50, cls.NOW - timedelta(minutes=1),
            cls.NOW + timedelta(hours=8), cls.NOW - timedelta(days=2), 3,
        )

    @classmethod
    def retry_reservation_row(cls, reservation_id, account_id, request_id, credits=2):
        return (
            reservation_id, account_id, request_id, credits,
            cls.NOW - timedelta(minutes=1), cls.NOW + timedelta(minutes=5), "RESERVED",
        )

    async def test_atomic_claim_checks_owner_reservation_and_inserts_before_send(self):
        reservation_id, account_id, job_id = uuid4(), uuid4(), uuid4()
        connection = FakeConnection([
            self.eligible_row(reservation_id, account_id), (1, 2), None, (job_id, "RESERVED", None),
        ])
        result = await FlowGenerationJobRepository(FakePool(connection), now=lambda: self.NOW).claim_or_get(
            account_ref="flow-account", request=request(), fingerprint="a" * 64,
        )
        self.assertEqual((result.job_id, result.status, result.created), (job_id, "RESERVED", True))
        self.assertIn("owner_user_id", connection.calls[0][0])
        self.assertIn("reservation.state = 'RESERVED'", connection.calls[0][0])
        self.assertIn("ON CONFLICT (idempotency_fingerprint) DO NOTHING", connection.calls[3][0])
        self.assertIn("status)", connection.calls[3][0])

    async def test_retry_reservation_preflight_returns_only_owned_database_snapshot(self):
        reservation_id, account_id, request_id = uuid4(), uuid4(), uuid4()
        connection = FakeConnection([(
            reservation_id, account_id, request_id, "veo-3.1-lite", 8, "quote-1", 2,
            "FLOW_QUOTE", self.NOW - timedelta(minutes=1),
            self.NOW + timedelta(minutes=5), "RESERVED", self.NOW - timedelta(minutes=1),
        )])
        result = await FlowGenerationJobRepository(
            FakePool(connection), now=lambda: self.NOW,
        ).get_owned_retry_reservation(
            reservation_id=reservation_id, account_id=account_id,
            owner_user_id="owner-1",
        )
        self.assertEqual((result.id, result.flow_account_id), (reservation_id, account_id))
        self.assertIn("a.owner_user_id = %s", connection.calls[0][0])

    async def test_failure_preflight_is_owner_scoped_and_replays_existing_gate(self):
        job_id, scene_id, reservation_id = uuid4(), uuid4(), uuid4()
        connection = FakeConnection([(
            "FAILED", 1, scene_id, True, "ALLOW", "ELIGIBLE",
            reservation_id, "a" * 64, 3,
        )])
        result = await FlowGenerationJobRepository(FakePool(connection)).assert_failure_owned(
            job_id=job_id, owner_user_id="owner-1",
        )
        self.assertTrue(result.retry_scheduled)
        self.assertEqual(result.retry_reservation_id, reservation_id)
        self.assertIn("b.owner_user_id = %s", connection.calls[0][0])

    async def test_existing_claim_never_creates_another_generation_row(self):
        reservation_id, account_id, job_id = uuid4(), uuid4(), uuid4()
        task_request = request()
        connection = FakeConnection([
            self.eligible_row(reservation_id, account_id), (1, 2),
            (job_id, account_id, task_request.scene_id, reservation_id, 1, "REMOTE_SUBMISSION_UNKNOWN", None),
        ])
        result = await FlowGenerationJobRepository(FakePool(connection), now=lambda: self.NOW).claim_or_get(
            account_ref="flow-account", request=task_request, fingerprint="b" * 64,
        )
        self.assertFalse(result.created)
        self.assertEqual(result.status, "REMOTE_SUBMISSION_UNKNOWN")
        self.assertEqual(len(connection.calls), 3)

    async def test_missing_reservation_fails_closed_before_insert(self):
        connection = FakeConnection([None])
        with self.assertRaises(RepositoryUnavailable):
            await FlowGenerationJobRepository(FakePool(connection)).claim_or_get(
                account_ref="flow-account", request=request(), fingerprint="c" * 64,
            )
        self.assertEqual(len(connection.calls), 1)

    async def test_status_updates_only_transition_reserved_claims(self):
        first_scene, second_scene = uuid4(), uuid4()
        connection = FakeConnection([
            ("RESERVED", 1, first_scene, "PENDING", 0, False), ("updated",), ("updated",),
            ("RESERVED", 1, second_scene, "PENDING", 0, False), ("updated",), ("updated",),
        ])
        repository = FlowGenerationJobRepository(FakePool(connection))
        job_id = uuid4()
        await repository.mark_submitted(job_id=job_id, external_job_id="remote-1")
        await repository.mark_remote_submission_unknown(job_id=job_id)
        self.assertIn("status = 'SUBMITTED'", connection.calls[1][0])
        self.assertIn("status = 'REMOTE_SUBMISSION_UNKNOWN'", connection.calls[4][0])
        self.assertIn("state = 'BLOCKED'", connection.calls[5][0])

    async def test_resume_context_is_loaded_only_from_persisted_job_request(self):
        job_id = uuid4()
        connection = FakeConnection([("remote-1", "https://labs.google/fx/tools/flow",
                                      "original prompt", "C:/flow-output")])
        result = await FlowGenerationJobRepository(FakePool(connection)).get_resume_context(
            job_id=job_id, account_ref="flow-account", owner_user_id="owner-1",
        )
        self.assertEqual(result, PersistedJobResumeContext(
            "remote-1", "https://labs.google/fx/tools/flow", "original prompt", "C:/flow-output",
        ))
        self.assertIn("request_json->'arguments'->>'prompt'", connection.calls[0][0])
        self.assertIn("'REMOTE_SUBMISSION_UNKNOWN'", connection.calls[0][0])
        self.assertIn("account.alias = %s", connection.calls[0][0])
        self.assertIn("account.owner_user_id = %s", connection.calls[0][0])

    async def test_missing_or_incomplete_resume_context_stays_unavailable(self):
        for row in [None, (None, "https://labs.google/fx/tools/flow", "prompt", "C:/out")]:
            connection = FakeConnection([row])
            result = await FlowGenerationJobRepository(FakePool(connection)).get_resume_context(
                job_id=uuid4(), account_ref="flow-account", owner_user_id="owner-1",
            )
            self.assertIsNone(result)

    async def test_expired_quote_or_paused_account_cannot_claim_before_submit(self):
        for overrides in [
            {"quote_expires_at": self.NOW - timedelta(seconds=1)},
            {"paused": True},
        ]:
            reservation_id, account_id = uuid4(), uuid4()
            connection = FakeConnection([self.eligible_row(reservation_id, account_id, **overrides)])
            with self.subTest(overrides=overrides), self.assertRaises(RepositoryUnavailable):
                await FlowGenerationJobRepository(FakePool(connection), now=lambda: self.NOW).claim_or_get(
                    account_ref="flow-account", request=request(), fingerprint="d" * 64,
                )
            self.assertEqual(len(connection.calls), 1)

    async def test_attempt_index_is_bounded_before_database_access(self):
        task_request = request(attempt_index=4)
        connection = FakeConnection()
        with self.assertRaises(ValueError):
            await FlowGenerationJobRepository(FakePool(connection)).claim_or_get(
                account_ref="flow-account", request=task_request, fingerprint="e" * 64,
            )
        self.assertEqual(connection.calls, [])

    async def test_retry_claim_requires_matching_retry_wait_state_and_retry_counter(self):
        reservation_id, account_id, job_id = uuid4(), uuid4(), uuid4()
        task_request = request(attempt_index=2)
        connection = FakeConnection([
            self.eligible_row(
                reservation_id, account_id, scene_state=SceneJobState.RETRY_WAIT.value,
                scene_retry_count=1,
            ),
            (1, 2), None,
            ("FAILED", True, "ALLOW", reservation_id, 3),
            (job_id, "RESERVED", None),
        ])
        result = await FlowGenerationJobRepository(FakePool(connection), now=lambda: self.NOW).claim_or_get(
            account_ref="flow-account", request=task_request, fingerprint="f" * 64,
        )
        self.assertTrue(result.created)
        self.assertEqual(result.job_id, job_id)

        stale = request(attempt_index=2)
        connection = FakeConnection([
            self.eligible_row(
                reservation_id, account_id, scene_state=SceneJobState.RETRY_WAIT.value,
                scene_retry_count=0,
            ),
            (1, 2), None,
        ])
        with self.assertRaises(RepositoryUnavailable):
            await FlowGenerationJobRepository(FakePool(connection), now=lambda: self.NOW).claim_or_get(
                account_ref="flow-account", request=stale, fingerprint="9" * 64,
            )

    async def test_retry_claim_rejects_reservation_not_bound_by_prior_gate(self):
        reservation_id, account_id = uuid4(), uuid4()
        task_request = request(attempt_index=2)
        connection = FakeConnection([
            self.eligible_row(
                reservation_id, account_id, scene_state=SceneJobState.RETRY_WAIT.value,
                scene_retry_count=1,
            ),
            (1, 2), None,
            ("FAILED", True, "ALLOW", uuid4(), 3),
        ])
        with self.assertRaisesRegex(RepositoryUnavailable, "exact eligible retry-gate"):
            await FlowGenerationJobRepository(
                FakePool(connection), now=lambda: self.NOW,
            ).claim_or_get(
                account_ref="flow-account", request=task_request, fingerprint="8" * 64,
            )
        self.assertFalse(any("INSERT INTO generation_jobs" in call[0] for call in connection.calls))

    async def test_mark_failure_schedules_only_configured_definitive_retries(self):
        for attempt_index, retry_count, expected_state, expected_count, expected_retry in [
            (1, 0, "RETRY_WAIT", 1, True),
            (2, 1, "RETRY_WAIT", 2, True),
            (3, 2, "FAILED", 2, False),
        ]:
            job_id, scene_id, reservation_id, account_id, request_id = (
                uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
            )
            evidence = RetrySpendEvidence(
                reservation_id, account_id, request_id, 2,
                self.NOW + timedelta(minutes=5), "a" * 64, self.NOW,
            )
            rows = [
                self.retry_account_row(),
                self.retry_reservation_row(reservation_id, account_id, request_id),
                ("RUNNING", attempt_index, scene_id, "RUNNING", retry_count, False,
                 None, None, None, None, uuid4(), None),
            ]
            if expected_retry:
                rows.extend([
                    (1, 2), None,
                ])
            rows.extend([("updated",), ("updated",)])
            connection = FakeConnection(rows)
            decision = await FlowGenerationJobRepository(
                FakePool(connection), retry_policy=SceneRetryPolicy(2), now=lambda: self.NOW,
            ).record_failure_retry_gate(
                job_id=job_id, owner_user_id="owner-1", retryable=True,
                failure_code="REMOTE_FAILED", spend_evidence=evidence,
                denial_reason=RetryGateReason.ELIGIBLE,
            )
            self.assertEqual(decision.scene_state.value, expected_state)
            self.assertEqual(decision.retry_count, expected_count)
            self.assertEqual(decision.retry_scheduled, expected_retry)
            self.assertEqual(
                decision.reason,
                RetryGateReason.ELIGIBLE if expected_retry else RetryGateReason.ATTEMPT_LIMIT_EXHAUSTED,
            )
            self.assertIn("FROM flow_accounts", connection.calls[0][0])
            self.assertIn("FROM flow_credit_reservations", connection.calls[1][0])
            self.assertIn("FROM generation_jobs AS j", connection.calls[2][0])
            self.assertIn("retry_gate_decision = %s", connection.calls[-2][0])

    async def test_non_retryable_and_ambiguous_outcomes_never_schedule(self):
        job_id, scene_id = uuid4(), uuid4()
        connection = FakeConnection([
            ("SUBMITTED", 1, scene_id, "SUBMITTED", 0, False,
             None, None, None, None, uuid4(), None), ("updated",), ("updated",),
        ])
        decision = await FlowGenerationJobRepository(FakePool(connection)).record_failure_retry_gate(
            job_id=job_id, owner_user_id="owner-1", retryable=False,
            failure_code="POLICY_BLOCKED", spend_evidence=None,
            denial_reason=RetryGateReason.FAILURE_NOT_RETRYABLE,
        )
        self.assertFalse(decision.retry_scheduled)
        self.assertEqual(decision.reason, RetryGateReason.FAILURE_NOT_RETRYABLE)

        unknown = FakeConnection([(
            "REMOTE_SUBMISSION_UNKNOWN", 1, scene_id, "BLOCKED", 0, False,
            None, None, None, None, uuid4(), None,
        )])
        with self.assertRaises(RepositoryUnavailable):
            await FlowGenerationJobRepository(FakePool(unknown)).record_failure_retry_gate(
                job_id=job_id, owner_user_id="owner-1", retryable=True,
                failure_code="GENERATION_FAILED", spend_evidence=None,
                denial_reason=RetryGateReason.RESERVATION_UNAVAILABLE,
            )

    async def test_stale_approval_evidence_is_persisted_as_no_retry(self):
        job_id, scene_id = uuid4(), uuid4()
        evidence = RetrySpendEvidence(
            uuid4(), uuid4(), uuid4(), 2,
            self.NOW + timedelta(minutes=5), "a" * 64,
            self.NOW - timedelta(minutes=6),
        )
        connection = FakeConnection([
            ("RUNNING", 1, scene_id, "RUNNING", 0, False,
             None, None, None, None, uuid4(), None),
            ("updated",), ("updated",),
        ])
        decision = await FlowGenerationJobRepository(
            FakePool(connection), now=lambda: self.NOW,
        ).record_failure_retry_gate(
            job_id=job_id, owner_user_id="owner-1", retryable=True,
            failure_code="QA_FAILED", spend_evidence=evidence,
            denial_reason=RetryGateReason.ELIGIBLE,
        )
        self.assertFalse(decision.retry_scheduled)
        self.assertEqual(decision.reason, RetryGateReason.SPEND_STATE_INVALID)
        self.assertEqual(len(connection.calls), 3)

    async def test_malformed_active_spend_state_is_durably_denied(self):
        job_id, scene_id = uuid4(), uuid4()
        reservation_id, account_id, request_id = uuid4(), uuid4(), uuid4()
        evidence = RetrySpendEvidence(
            reservation_id, account_id, request_id, 2,
            self.NOW + timedelta(minutes=5), "a" * 64, self.NOW,
        )
        connection = FakeConnection([
            self.retry_account_row(),
            self.retry_reservation_row(reservation_id, account_id, request_id),
            ("RUNNING", 1, scene_id, "RUNNING", 0, False,
             None, None, None, None, uuid4(), None),
            ("malformed",), None, ("updated",), ("updated",),
        ])
        decision = await FlowGenerationJobRepository(
            FakePool(connection), now=lambda: self.NOW,
        ).record_failure_retry_gate(
            job_id=job_id, owner_user_id="owner-1", retryable=True,
            failure_code="QA_FAILED", spend_evidence=evidence,
            denial_reason=RetryGateReason.ELIGIBLE,
        )
        self.assertFalse(decision.retry_scheduled)
        self.assertEqual(decision.reason, RetryGateReason.SPEND_STATE_INVALID)
        self.assertIn("retry_gate_decision = %s", connection.calls[-2][0])

    async def test_retry_decision_is_idempotent_after_job_failure(self):
        job_id, scene_id = uuid4(), uuid4()
        reservation_id, account_id, request_id = uuid4(), uuid4(), uuid4()
        evidence = RetrySpendEvidence(
            reservation_id, account_id, request_id, 2,
            self.NOW + timedelta(minutes=5), "a" * 64, self.NOW,
        )
        connection = FakeConnection([
            self.retry_account_row(),
            self.retry_reservation_row(reservation_id, account_id, request_id),
            # Scene has since advanced and exhausted attempt 3; replaying the
            # attempt-1 failure must return its original scheduled decision.
            ("FAILED", 1, scene_id, "FAILED", 2, True,
             "ALLOW", "ELIGIBLE", reservation_id, "a" * 64, uuid4(), 3),
        ])
        decision = await FlowGenerationJobRepository(
            FakePool(connection), now=lambda: self.NOW,
        ).record_failure_retry_gate(
            job_id=job_id, owner_user_id="owner-1", retryable=True,
            failure_code="GENERATION_FAILED", spend_evidence=evidence,
            denial_reason=RetryGateReason.ELIGIBLE,
        )
        self.assertTrue(decision.retry_scheduled)
        self.assertEqual(decision.retry_count, 1)
        self.assertEqual(decision.reason, RetryGateReason.ELIGIBLE)
        self.assertEqual(len(connection.calls), 3)


if __name__ == "__main__":
    unittest.main()
