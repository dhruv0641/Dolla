from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from uuid import uuid4

from flowx_os.analytics.cohorts import CohortAnalysisRequest
from flowx_os.analytics.collection import CollectionWindow
from flowx_os.analytics.feedback import (
    FeedbackApprovalAttestation,
    FeedbackApprovalKind,
    FeedbackGateCode,
    FeedbackGateError,
    FeedbackGateRequest,
    FeedbackGateService,
    FeedbackOutcomeRecorder,
    FeedbackOutcomeRequest,
)
from flowx_os.analytics.metrics import load_metric_registry
from flowx_os.analytics.recommendations import (
    ExperimentPlanner,
    ExperimentProposalRequest,
)
from flowx_os.credits.reservations import (
    CreditQuoteSource,
    CreditReservationRecord,
    CreditReservationState,
)
from tests.test_recommendations import NOW, descriptive_analysis, recommendation_evidence


REGISTRY = load_metric_registry(
    Path(__file__).resolve().parents[1] / "config" / "platform_metrics.v1.json"
)


def proposal_evidence():
    _, _, _, recommendation = recommendation_evidence()
    request = ExperimentProposalRequest(
        proposal_id=uuid4(), owner_user_id="owner-1",
        recommendation_id=recommendation.recommendation_id,
        recommendation_fingerprint=recommendation.fingerprint,
        definition_version="experiment-v1", minimum_sample_per_arm=3,
        target_sample_per_arm=3, created_at=NOW + timedelta(minutes=1),
    )
    return ExperimentPlanner().propose(request=request, recommendation=recommendation)


def reservation(*, state=CreditReservationState.RESERVED, credits=25):
    created = NOW + timedelta(minutes=2)
    return CreditReservationRecord(
        id=uuid4(), flow_account_id=uuid4(), request_id=uuid4(),
        model_name="veo-model", duration_seconds=32, quote_ref="quote:feedback:1",
        quoted_credits=credits, quote_source=CreditQuoteSource.FLOW_QUOTE,
        quoted_at=created, quote_expires_at=created + timedelta(minutes=10),
        state=state, created_at=created,
    )


def gate_request(proposal, value, **changes):
    fields = dict(
        gate_id=uuid4(), owner_user_id="owner-1",
        proposal_id=proposal.proposal_id,
        proposal_fingerprint=proposal.fingerprint,
        account_id=value.flow_account_id, reservation_id=value.id,
        reservation_request_id=value.request_id, maximum_credits=50,
        human_approval_ref="approval:experiment:1",
        spend_approval_ref="approval:spend:1",
        definition_version="feedback-gate-v1",
        requested_at=NOW + timedelta(minutes=3),
    )
    fields.update(changes)
    return FeedbackGateRequest(**fields)


class Verifier:
    def __init__(self, approved=True, raises=False):
        self.approved = approved
        self.raises = raises
        self.calls = []

    async def verify(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError("unavailable")
        if not self.approved:
            return None
        spend = "account_id" in kwargs
        return FeedbackApprovalAttestation(
            attestation_id=uuid4(),
            kind=(FeedbackApprovalKind.SPEND if spend else FeedbackApprovalKind.HUMAN_EXPERIMENT),
            approval_ref=kwargs["approval_ref"],
            owner_user_id=kwargs["owner_user_id"],
            proposal_id=kwargs["proposal_id"],
            proposal_fingerprint=kwargs["proposal_fingerprint"],
            account_id=kwargs.get("account_id"),
            maximum_credits=kwargs.get("maximum_credits"),
            operation=(kwargs.get("operation") if spend else None),
            verifier_ref=("approval-store:spend" if spend else "approval-store:experiment"),
            verifier_version="approval-v1", evidence_fingerprint="a" * 64,
            verified_at=NOW + timedelta(minutes=3),
            expires_at=NOW + timedelta(minutes=9),
        )


class Store:
    def __init__(self, value):
        self.value = value
        self.calls = []

    async def assert_proposal_owned(self, **kwargs):
        self.calls.append(("proposal", kwargs))

    async def get_owned_reservation(self, **kwargs):
        self.calls.append(("reservation", kwargs))
        return self.value

    async def record_gate(self, **kwargs):
        self.calls.append(("gate", kwargs))
        return kwargs["decision"]

    async def record_outcome(self, **kwargs):
        self.calls.append(("outcome", kwargs))
        return kwargs["outcome"]


class FeedbackLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_approvals_and_spend_create_inert_gate(self):
        proposal = proposal_evidence()
        value = reservation()
        request = gate_request(proposal, value)
        store = Store(value)
        human = Verifier()
        spend = Verifier()

        decision = await FeedbackGateService(
            store, human, spend,
            now=lambda: NOW + timedelta(minutes=4),
        ).approve(request=request, proposal=proposal)

        self.assertEqual(decision.proposal_fingerprint, proposal.fingerprint)
        self.assertEqual(decision.reservation_id, value.id)
        self.assertEqual(decision.quoted_credits, 25)
        self.assertNotEqual(decision.human_approval_fingerprint, request.human_approval_ref)
        self.assertNotEqual(decision.spend_approval_fingerprint, request.spend_approval_ref)
        data = decision.canonical()
        self.assertTrue(data["separate_executor_must_revalidate_exact_reservation"])
        for key in (
            "execution_authorized", "automatic_execution", "account_connection_authorized",
            "scheduling_authorized", "upload_authorized", "publishing_authorized",
        ):
            self.assertFalse(data[key])
        self.assertEqual(store.calls[0][0], "proposal")
        self.assertEqual(store.calls[-1][0], "gate")

    async def test_mixed_owner_or_proposal_fails_before_external_verifier(self):
        proposal = proposal_evidence()
        value = reservation()
        request = gate_request(proposal, value, owner_user_id="owner-2")
        human = Verifier()
        spend = Verifier()
        with self.assertRaisesRegex(FeedbackGateError, "proposal") as raised:
            await FeedbackGateService(Store(value), human, spend).approve(
                request=request, proposal=proposal,
            )
        self.assertEqual(raised.exception.code, FeedbackGateCode.PROPOSAL_MISMATCH)
        self.assertEqual(human.calls, [])
        self.assertEqual(spend.calls, [])

    async def test_stale_mismatched_or_excess_reservation_fails_closed(self):
        proposal = proposal_evidence()
        for value, changes, code in (
            (reservation(state=CreditReservationState.RECONCILE_PENDING), {}, FeedbackGateCode.SPEND_STATE_INVALID),
            (reservation(credits=51), {}, FeedbackGateCode.SPEND_STATE_INVALID),
            (reservation(), {"reservation_request_id": uuid4()}, FeedbackGateCode.RESERVATION_MISMATCH),
        ):
            with self.subTest(code=code):
                request = gate_request(proposal, value, **changes)
                with self.assertRaises(FeedbackGateError) as raised:
                    await FeedbackGateService(
                        Store(value), Verifier(), Verifier(),
                        now=lambda: NOW + timedelta(minutes=4),
                    ).approve(request=request, proposal=proposal)
                self.assertEqual(raised.exception.code, code)

    async def test_both_human_and_spend_approval_are_mandatory(self):
        proposal = proposal_evidence()
        value = reservation()
        request = gate_request(proposal, value)
        cases = (
            (None, Verifier(), FeedbackGateCode.HUMAN_APPROVAL_UNAVAILABLE),
            (Verifier(False), Verifier(), FeedbackGateCode.HUMAN_APPROVAL_REQUIRED),
            (Verifier(), None, FeedbackGateCode.SPEND_APPROVAL_UNAVAILABLE),
            (Verifier(), Verifier(False), FeedbackGateCode.SPEND_APPROVAL_REQUIRED),
        )
        for human, spend, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(FeedbackGateError) as raised:
                    await FeedbackGateService(
                        Store(value), human, spend,
                        now=lambda: NOW + timedelta(minutes=4),
                    ).approve(request=request, proposal=proposal)
                self.assertEqual(raised.exception.code, code)

    async def test_post_gate_outcome_is_exact_descriptive_evidence(self):
        proposal = proposal_evidence()
        value = reservation()
        gate = await FeedbackGateService(
            Store(value), Verifier(), Verifier(),
            now=lambda: NOW + timedelta(minutes=4),
        ).approve(request=gate_request(proposal, value), proposal=proposal)
        analysis_request, report = descriptive_analysis()
        outcome_request = FeedbackOutcomeRequest(
            outcome_id=uuid4(), owner_user_id="owner-1",
            gate_id=gate.gate_id, gate_fingerprint=gate.fingerprint,
            report_request_id=analysis_request.request_id,
            report_fingerprint=report.fingerprint,
            definition_version="feedback-outcome-v1",
            recorded_at=NOW + timedelta(minutes=5),
        )
        store = Store(value)
        outcome = await FeedbackOutcomeRecorder(store).record(
            request=outcome_request, gate=gate, proposal=proposal,
            analysis_request=analysis_request, report=report, registry=REGISTRY,
        )
        self.assertEqual(outcome.report_fingerprint, report.fingerprint)
        self.assertEqual(outcome.source_count, 6)
        self.assertFalse(outcome.canonical()["causal_claim_authorized"])
        self.assertTrue(outcome.canonical()["new_recommendation_requires_separate_human_review"])

    async def test_outcome_rejects_mixed_report_or_underfilled_arm(self):
        proposal = proposal_evidence()
        value = reservation()
        gate = await FeedbackGateService(
            Store(value), Verifier(), Verifier(),
            now=lambda: NOW + timedelta(minutes=4),
        ).approve(request=gate_request(proposal, value), proposal=proposal)
        analysis_request, report = descriptive_analysis()
        request = FeedbackOutcomeRequest(
            outcome_id=uuid4(), owner_user_id="owner-1", gate_id=gate.gate_id,
            gate_fingerprint=gate.fingerprint,
            report_request_id=analysis_request.request_id,
            report_fingerprint="f" * 64, definition_version="feedback-outcome-v1",
            recorded_at=NOW + timedelta(minutes=5),
        )
        with self.assertRaises(FeedbackGateError) as raised:
            await FeedbackOutcomeRecorder(Store(value)).record(
                request=request, gate=gate, proposal=proposal,
                analysis_request=analysis_request, report=report, registry=REGISTRY,
            )
        self.assertEqual(raised.exception.code, FeedbackGateCode.OUTCOME_MISMATCH)


if __name__ == "__main__":
    unittest.main()
