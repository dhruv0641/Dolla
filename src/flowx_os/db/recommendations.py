"""Owner-scoped immutable persistence for recommendations and experiments."""

from __future__ import annotations

import json

from flowx_os.analytics.recommendations import (
    EvidenceBackedRecommendation,
    ExperimentProposal,
    ExperimentProposalRequest,
    RecommendationRequest,
)
from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work


class RecommendationNotFound(RuntimeError):
    """Required owned cohort or recommendation evidence was not found."""


class RecommendationConflict(RuntimeError):
    """An immutable request identity is already bound to different evidence."""


class RecommendationRepository:
    """Persist review-only hypotheses and inert experiment proposals."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def create_recommendation(
        self, *, request: RecommendationRequest,
        recommendation: EvidenceBackedRecommendation,
    ) -> EvidenceBackedRecommendation:
        if (
            not isinstance(request, RecommendationRequest)
            or not isinstance(recommendation, EvidenceBackedRecommendation)
            or recommendation.recommendation_id != request.recommendation_id
            or recommendation.owner_user_id != request.owner_user_id
            or recommendation.request_fingerprint != request.fingerprint
            or recommendation.report_request_id != request.report_request_id
            or recommendation.report_fingerprint != request.report_fingerprint
        ):
            raise ValueError("recommendation evidence is invalid")
        data = _bounded_json(recommendation.canonical(), 1_048_576, "recommendation")
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find_recommendation(
                    connection, request.recommendation_id, request.owner_user_id,
                )
                if existing is not None:
                    return self._require_recommendation_replay(
                        existing, request, recommendation,
                    )
                cursor = await connection.execute(
                    """INSERT INTO analytics_recommendations
                         (recommendation_id, owner_user_id, request_fingerprint,
                          report_request_id, report_fingerprint, definition_version,
                          factor, platform, metric_id, window_name,
                          registry_version, registry_fingerprint, minimum_group_size,
                          control_label, treatment_label, recommendation_data,
                          recommendation_fingerprint, storage_fingerprint, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s::jsonb, %s, repeat('0', 64), %s)
                       ON CONFLICT DO NOTHING
                       RETURNING request_fingerprint, recommendation_fingerprint""",
                    (
                        recommendation.recommendation_id,
                        recommendation.owner_user_id,
                        recommendation.request_fingerprint,
                        recommendation.report_request_id,
                        recommendation.report_fingerprint,
                        recommendation.definition_version,
                        recommendation.factor.value,
                        recommendation.platform.value,
                        recommendation.metric_id,
                        recommendation.window.value,
                        recommendation.registry_version,
                        recommendation.registry_fingerprint,
                        recommendation.minimum_group_size,
                        recommendation.control.label,
                        recommendation.treatment.label,
                        data, recommendation.fingerprint,
                        recommendation.created_at,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    existing = await self._find_recommendation(
                        connection, request.recommendation_id,
                        request.owner_user_id,
                    )
                    if existing is None:
                        raise RecommendationConflict(
                            "recommendation identity is already in use"
                        )
                    return self._require_recommendation_replay(
                        existing, request, recommendation,
                    )
                return self._require_recommendation_replay(
                    row, request, recommendation,
                )
        except (RecommendationConflict, RecommendationNotFound, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("recommendation storage is unavailable") from exc

    async def create_experiment_proposal(
        self, *, request: ExperimentProposalRequest,
        proposal: ExperimentProposal,
    ) -> ExperimentProposal:
        if (
            not isinstance(request, ExperimentProposalRequest)
            or not isinstance(proposal, ExperimentProposal)
            or proposal.proposal_id != request.proposal_id
            or proposal.owner_user_id != request.owner_user_id
            or proposal.request_fingerprint != request.fingerprint
            or proposal.recommendation_id != request.recommendation_id
            or proposal.recommendation_fingerprint
               != request.recommendation_fingerprint
        ):
            raise ValueError("experiment proposal evidence is invalid")
        data = _bounded_json(proposal.canonical(), 65_536, "experiment proposal")
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find_proposal(
                    connection, request.proposal_id, request.owner_user_id,
                )
                if existing is not None:
                    return self._require_proposal_replay(existing, request, proposal)
                cursor = await connection.execute(
                    """INSERT INTO analytics_experiment_proposals
                         (proposal_id, owner_user_id, request_fingerprint,
                          recommendation_id, recommendation_fingerprint,
                          definition_version, single_variable, platform, metric_id,
                          window_name, registry_version, registry_fingerprint,
                          control_label, treatment_label, minimum_sample_per_arm,
                          control_target_size, treatment_target_size, proposal_data,
                          proposal_fingerprint, storage_fingerprint, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s::jsonb, %s,
                               repeat('0', 64), %s)
                       ON CONFLICT DO NOTHING
                       RETURNING request_fingerprint, proposal_fingerprint""",
                    (
                        proposal.proposal_id, proposal.owner_user_id,
                        proposal.request_fingerprint, proposal.recommendation_id,
                        proposal.recommendation_fingerprint,
                        proposal.definition_version, proposal.factor.value,
                        proposal.platform.value, proposal.metric_id,
                        proposal.window.value, proposal.registry_version,
                        proposal.registry_fingerprint, proposal.control_label,
                        proposal.treatment_label, proposal.minimum_sample_per_arm,
                        proposal.control_target_size,
                        proposal.treatment_target_size, data,
                        proposal.fingerprint, proposal.created_at,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    existing = await self._find_proposal(
                        connection, request.proposal_id,
                        request.owner_user_id,
                    )
                    if existing is None:
                        raise RecommendationConflict(
                            "experiment proposal identity is already in use"
                        )
                    return self._require_proposal_replay(existing, request, proposal)
                return self._require_proposal_replay(row, request, proposal)
        except (RecommendationConflict, RecommendationNotFound, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("experiment proposal storage is unavailable") from exc

    @staticmethod
    async def _find_recommendation(connection, recommendation_id, owner_user_id):
        cursor = await connection.execute(
            """SELECT request_fingerprint, recommendation_fingerprint
               FROM analytics_recommendations
               WHERE recommendation_id = %s AND owner_user_id = %s""",
            (recommendation_id, owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    async def _find_proposal(connection, proposal_id, owner_user_id):
        cursor = await connection.execute(
            """SELECT request_fingerprint, proposal_fingerprint
               FROM analytics_experiment_proposals
               WHERE proposal_id = %s AND owner_user_id = %s""",
            (proposal_id, owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    def _require_recommendation_replay(row, request, recommendation):
        if tuple(row) != (request.fingerprint, recommendation.fingerprint):
            raise RecommendationConflict(
                "recommendation request identifies different immutable evidence"
            )
        return recommendation

    @staticmethod
    def _require_proposal_replay(row, request, proposal):
        if tuple(row) != (request.fingerprint, proposal.fingerprint):
            raise RecommendationConflict(
                "experiment request identifies different immutable evidence"
            )
        return proposal


def _bounded_json(value: dict[str, object], limit: int, label: str) -> str:
    serialized = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    if len(serialized.encode("utf-8")) > limit:
        raise ValueError(f"{label} exceeds its byte limit")
    return serialized
