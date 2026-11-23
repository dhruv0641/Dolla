from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
import unittest
from uuid import uuid4

from flowx_os.analytics.recommendations import (
    ExperimentPlanner,
    ExperimentProposalRequest,
)
from flowx_os.db.recommendations import (
    RecommendationConflict,
    RecommendationRepository,
)
from tests.test_recommendations import NOW, recommendation_evidence


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


def proposal_evidence():
    _, _, recommendation_request, recommendation = recommendation_evidence()
    proposal_request = ExperimentProposalRequest(
        proposal_id=uuid4(), owner_user_id="owner-1",
        recommendation_id=recommendation.recommendation_id,
        recommendation_fingerprint=recommendation.fingerprint,
        definition_version="experiment-v1", minimum_sample_per_arm=5,
        target_sample_per_arm=10, created_at=NOW + timedelta(minutes=1),
    )
    proposal = ExperimentPlanner().propose(
        request=proposal_request, recommendation=recommendation,
    )
    return recommendation_request, recommendation, proposal_request, proposal


class RecommendationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recommendation_is_owner_scoped_insert_or_read(self):
        request, recommendation, _, _ = proposal_evidence()
        connection = Connection([
            None, (request.fingerprint, recommendation.fingerprint),
        ])
        result = await RecommendationRepository(Pool(connection)).create_recommendation(
            request=request, recommendation=recommendation,
        )
        self.assertEqual(result, recommendation)
        self.assertEqual(
            connection.calls[0][1], (recommendation.recommendation_id, "owner-1"),
        )
        query, params = connection.calls[1]
        self.assertIn("ON CONFLICT DO NOTHING", query)
        self.assertIn("analytics_recommendations", query)
        self.assertIn(recommendation.report_fingerprint, params)
        self.assertNotIn("secretref://", repr(params))

    async def test_recommendation_replay_rejects_changed_evidence(self):
        request, recommendation, _, _ = proposal_evidence()
        connection = Connection([(request.fingerprint, "f" * 64)])
        with self.assertRaises(RecommendationConflict):
            await RecommendationRepository(Pool(connection)).create_recommendation(
                request=request, recommendation=recommendation,
            )
        self.assertEqual(len(connection.calls), 1)

    async def test_proposal_is_owner_scoped_inert_insert_or_read(self):
        _, _, request, proposal = proposal_evidence()
        connection = Connection([
            None, (request.fingerprint, proposal.fingerprint),
        ])
        result = await RecommendationRepository(Pool(connection)).create_experiment_proposal(
            request=request, proposal=proposal,
        )
        self.assertEqual(result, proposal)
        self.assertEqual(connection.calls[0][1], (proposal.proposal_id, "owner-1"))
        query, params = connection.calls[1]
        self.assertIn("ON CONFLICT DO NOTHING", query)
        self.assertIn("analytics_experiment_proposals", query)
        serialized = next(value for value in params if isinstance(value, str) and value.startswith("{"))
        self.assertIn('"execution_authorized":false', serialized)
        self.assertIn('"human_approval_required":true', serialized)

    async def test_proposal_replay_and_request_mismatch_fail_closed(self):
        _, _, request, proposal = proposal_evidence()
        connection = Connection([(request.fingerprint, "f" * 64)])
        with self.assertRaises(RecommendationConflict):
            await RecommendationRepository(Pool(connection)).create_experiment_proposal(
                request=request, proposal=proposal,
            )
        with self.assertRaisesRegex(ValueError, "invalid"):
            await RecommendationRepository(Pool(Connection())).create_experiment_proposal(
                request=replace(request, recommendation_fingerprint="e" * 64),
                proposal=proposal,
            )


if __name__ == "__main__":
    unittest.main()
