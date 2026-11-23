from contextlib import asynccontextmanager
from datetime import timedelta
import unittest
from uuid import uuid4

from flowx_os.analytics.feedback import (
    FeedbackGateService,
    FeedbackOutcomeRecorder,
    FeedbackOutcomeRequest,
)
from flowx_os.db.feedback import FeedbackConflict, FeedbackRepository
from tests.test_feedback_loop import (
    NOW, REGISTRY, Store, Verifier, gate_request, proposal_evidence, reservation,
)
from tests.test_recommendations import descriptive_analysis


class Cursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class Connection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, query, params=None):
        self.calls.append((query, params))
        return Cursor(self.rows.pop(0) if self.rows else None)


class Pool:
    def __init__(self, connection):
        self.connection_value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.connection_value


async def gate_evidence():
    proposal = proposal_evidence()
    value = reservation()
    request = gate_request(proposal, value)
    store = Store(value)
    decision = await FeedbackGateService(
        store, Verifier(), Verifier(),
        now=lambda: NOW + timedelta(minutes=4),
    ).approve(request=request, proposal=proposal)
    recorded = store.calls[-1][1]
    return (
        proposal, value, request, decision,
        recorded["human_attestation"], recorded["spend_attestation"],
    )


async def outcome_evidence():
    proposal, value, gate_request_value, gate, _, _ = await gate_evidence()
    analysis_request, report = descriptive_analysis()
    request = FeedbackOutcomeRequest(
        outcome_id=uuid4(), owner_user_id="owner-1",
        gate_id=gate.gate_id, gate_fingerprint=gate.fingerprint,
        report_request_id=analysis_request.request_id,
        report_fingerprint=report.fingerprint,
        definition_version="feedback-outcome-v1",
        recorded_at=NOW + timedelta(minutes=5),
    )
    outcome = await FeedbackOutcomeRecorder(Store(value)).record(
        request=request, gate=gate, proposal=proposal,
        analysis_request=analysis_request, report=report, registry=REGISTRY,
    )
    return gate_request_value, gate, request, outcome


class FeedbackRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_owned_preflights_do_not_leak_cross_tenant_records(self):
        proposal, value, _, _, _, _ = await gate_evidence()
        connection = Connection([(1,), (
            value.id, value.flow_account_id, value.request_id, value.model_name,
            value.duration_seconds, value.quote_ref, value.quoted_credits,
            value.quote_source.value, value.quoted_at, value.quote_expires_at,
            value.state.value, value.created_at,
        )])
        repository = FeedbackRepository(Pool(connection))
        await repository.assert_proposal_owned(
            proposal_id=proposal.proposal_id,
            proposal_fingerprint=proposal.fingerprint,
            owner_user_id="owner-1",
        )
        stored = await repository.get_owned_reservation(
            reservation_id=value.id, account_id=value.flow_account_id,
            owner_user_id="owner-1",
        )
        self.assertEqual(stored, value)
        self.assertIn("owner_user_id = %s", connection.calls[0][0])
        self.assertIn("a.owner_user_id = %s", connection.calls[1][0])

    async def test_gate_insert_is_exact_idempotent_and_reference_only(self):
        _, _, request, decision, human, spend = await gate_evidence()
        connection = Connection([
            None, (request.fingerprint, decision.fingerprint),
        ])
        result = await FeedbackRepository(Pool(connection)).record_gate(
            request=request, decision=decision,
            human_attestation=human, spend_attestation=spend,
        )
        self.assertEqual(result, decision)
        self.assertEqual(connection.calls[0][1], (decision.gate_id, "owner-1"))
        query, params = connection.calls[1]
        self.assertIn("ON CONFLICT DO NOTHING", query)
        self.assertIn(request.human_approval_ref, params)
        self.assertNotIn("credentials_ref", repr(params))
        self.assertIn('"automatic_execution":false', next(
            item for item in params if isinstance(item, str) and item.startswith("{")
        ))
        self.assertNotIn("INSERT INTO analytics_feedback_approval_attestations", " ".join(
            query for query, _ in connection.calls
        ))

    async def test_gate_replay_conflict_fails_closed(self):
        _, _, request, decision, human, spend = await gate_evidence()
        connection = Connection([(request.fingerprint, "f" * 64)])
        with self.assertRaises(FeedbackConflict):
            await FeedbackRepository(Pool(connection)).record_gate(
                request=request, decision=decision,
                human_attestation=human, spend_attestation=spend,
            )

    async def test_outcome_insert_and_replay_are_immutable(self):
        _, _, request, outcome = await outcome_evidence()
        connection = Connection([None, (request.fingerprint, outcome.fingerprint)])
        result = await FeedbackRepository(Pool(connection)).record_outcome(
            request=request, outcome=outcome,
        )
        self.assertEqual(result, outcome)
        query, params = connection.calls[1]
        self.assertIn("analytics_feedback_outcomes", query)
        self.assertIn("ON CONFLICT DO NOTHING", query)
        self.assertIn(outcome.report_fingerprint, params)


if __name__ == "__main__":
    unittest.main()
