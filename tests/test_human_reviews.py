from contextlib import asynccontextmanager
from datetime import datetime, timezone
import unittest
from uuid import uuid4

from flowx_os.db.content import OwnedContentNotFound
from flowx_os.db.human_reviews import (
    HumanReviewNotAllowed,
    HumanReviewRepository,
)
from flowx_os.domain.content_state import ContentStatus
from flowx_os.qa.human_review import (
    HumanReviewDecision,
    HumanReviewRequest,
    HumanReviewRevisionTarget,
)


NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, row=None):
        self.row = row
        self.rowcount = 1

    async def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, query, params=None):
        self.calls.append((query, params))
        return FakeCursor(self.rows.pop(0) if self.rows else None)


class FakePool:
    def __init__(self, connection):
        self.connection_value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.connection_value


def review_request(*, decision=HumanReviewDecision.APPROVE, revision_target=None):
    return HumanReviewRequest(
        request_id=uuid4(), content_id=uuid4(), asset_id=uuid4(),
        qa_report_id=uuid4(), reviewer_user_id="owner-1", decision=decision,
        reason="Reviewed the final media and supporting evidence.",
        revision_target=revision_target,
    )


def stored_row(decision_id, request):
    return (
        decision_id, request.request_id, request.fingerprint, request.content_id,
        request.asset_id, request.qa_report_id, request.reviewer_user_id,
        request.decision.value, request.reason,
        request.revision_target.value if request.revision_target else None, NOW,
    )


class HumanReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_approve_binds_exact_unblocked_signal_evidence(self):
        request = review_request()
        decision_id = request.request_id
        connection = FakeConnection([
            ("NEEDS_REVIEW",), None,
            ("FINAL_VIDEO", "ACTIVE", "signals-v1", "NEEDS_HUMAN", "AUTO", [], {
                "human_approval_required": True, "content_approved": False,
            }),
            None, stored_row(decision_id, request),
        ])
        record = await HumanReviewRepository(FakePool(connection)).create_or_get(
            decision_id=decision_id, brand_id=uuid4(),
            owner_user_id="owner-1", request=request,
        )
        self.assertEqual(record.next_status, ContentStatus.READY)
        self.assertIn("FOR UPDATE OF c", connection.calls[0][0])
        self.assertIn("FOR KEY SHARE OF a, q", connection.calls[2][0])
        self.assertIn("INSERT INTO review_decisions", connection.calls[4][0])

    async def test_changes_required_has_explicit_revision_target(self):
        with self.assertRaises(ValueError):
            review_request(decision=HumanReviewDecision.CHANGES_REQUIRED)
        request = review_request(
            decision=HumanReviewDecision.CHANGES_REQUIRED,
            revision_target=HumanReviewRevisionTarget.STORYBOARD_READY,
        )
        self.assertEqual(request.next_status, ContentStatus.STORYBOARD_READY)
        rejected = review_request(decision=HumanReviewDecision.REJECT)
        self.assertEqual(rejected.next_status, ContentStatus.ARCHIVED)
        with self.assertRaises(ValueError):
            review_request(
                decision=HumanReviewDecision.APPROVE,
                revision_target=HumanReviewRevisionTarget.SCRIPT_READY,
            )

    async def test_blocked_or_failed_automated_qa_cannot_be_approved(self):
        for qa_decision, blockers in [("FAIL", []), ("NEEDS_HUMAN", ["POLICY_CRITICAL"])]:
            request = review_request()
            connection = FakeConnection([
                ("NEEDS_REVIEW",), None,
                ("EXPORT_VARIANT", "ACTIVE", "signals-v1", qa_decision, "AUTO", blockers, {
                    "human_approval_required": True, "content_approved": False,
                }),
            ])
            with self.subTest(qa_decision=qa_decision, blockers=blockers), self.assertRaises(
                HumanReviewNotAllowed
            ):
                await HumanReviewRepository(FakePool(connection)).create_or_get(
                    decision_id=request.request_id, brand_id=uuid4(),
                    owner_user_id="owner-1", request=request,
                )
            self.assertFalse(any("INSERT INTO review_decisions" in query for query, _ in connection.calls))

    async def test_exact_replay_returns_before_current_state_check(self):
        request = review_request()
        row = stored_row(request.request_id, request)
        connection = FakeConnection([("READY",), row])
        record = await HumanReviewRepository(FakePool(connection)).create_or_get(
            decision_id=request.request_id, brand_id=uuid4(),
            owner_user_id="owner-1", request=request,
        )
        self.assertEqual(record.request, request)
        self.assertEqual(len(connection.calls), 2)

    async def test_foreign_content_is_concealed_before_evidence_lookup(self):
        request = review_request()
        connection = FakeConnection([None])
        with self.assertRaises(OwnedContentNotFound):
            await HumanReviewRepository(FakePool(connection)).create_or_get(
                decision_id=request.request_id, brand_id=uuid4(),
                owner_user_id="owner-1", request=request,
            )
        self.assertEqual(len(connection.calls), 1)

    async def test_reason_rejects_credentials_and_control_characters(self):
        for reason in ["token=private-value", "unsafe\nreason"]:
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                HumanReviewRequest(
                    request_id=uuid4(), content_id=uuid4(), asset_id=uuid4(),
                    qa_report_id=uuid4(), reviewer_user_id="owner-1",
                    decision=HumanReviewDecision.REJECT, reason=reason,
                )

    async def test_fingerprint_binds_reason_and_decision_identity(self):
        request = review_request()
        changed_reason = HumanReviewRequest(
            request_id=request.request_id, content_id=request.content_id,
            asset_id=request.asset_id, qa_report_id=request.qa_report_id,
            reviewer_user_id=request.reviewer_user_id, decision=request.decision,
            reason="A different reviewed rationale.",
        )
        self.assertNotEqual(request.fingerprint, changed_reason.fingerprint)

if __name__ == "__main__":
    unittest.main()
