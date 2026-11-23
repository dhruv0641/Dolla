"""Transactional persistence for approved spend gates and feedback outcomes."""

from __future__ import annotations

import json

from flowx_os.analytics.feedback import (
    FeedbackApprovalAttestation,
    FeedbackGateDecision,
    FeedbackGateRequest,
    FeedbackOutcome,
    FeedbackOutcomeRequest,
)
from flowx_os.credits.reservations import (
    CreditQuoteSource,
    CreditReservationRecord,
    CreditReservationState,
)
from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work


class FeedbackNotFound(RuntimeError):
    pass


class FeedbackConflict(RuntimeError):
    pass


_RESERVATION_COLUMNS = """r.id, r.flow_account_id, r.request_id, r.model_name,
    r.duration_seconds, r.quote_ref, r.quoted_credits, r.quote_source,
    r.quoted_at, r.quote_expires_at, r.state, r.created_at"""


class FeedbackRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def assert_proposal_owned(
        self, *, proposal_id, proposal_fingerprint, owner_user_id,
    ) -> None:
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT 1 FROM analytics_experiment_proposals
                       WHERE proposal_id = %s AND proposal_fingerprint = %s
                         AND owner_user_id = %s""",
                    (proposal_id, proposal_fingerprint, owner_user_id),
                )
                if await cursor.fetchone() is None:
                    raise FeedbackNotFound("owned experiment proposal not found")
        except FeedbackNotFound:
            raise
        except Exception as exc:
            raise RepositoryUnavailable("feedback proposal lookup is unavailable") from exc

    async def get_owned_reservation(
        self, *, reservation_id, account_id, owner_user_id,
    ) -> CreditReservationRecord:
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""SELECT {_RESERVATION_COLUMNS}
                        FROM flow_credit_reservations AS r
                        JOIN flow_accounts AS a ON a.id = r.flow_account_id
                        WHERE r.id = %s AND r.flow_account_id = %s
                          AND a.owner_user_id = %s""",
                    (reservation_id, account_id, owner_user_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise FeedbackNotFound("owned credit reservation not found")
                return _reservation(row)
        except FeedbackNotFound:
            raise
        except Exception as exc:
            raise RepositoryUnavailable("feedback reservation lookup is unavailable") from exc

    async def record_gate(
        self, *, request: FeedbackGateRequest,
        decision: FeedbackGateDecision,
        human_attestation: FeedbackApprovalAttestation,
        spend_attestation: FeedbackApprovalAttestation,
    ) -> FeedbackGateDecision:
        if (
            not isinstance(request, FeedbackGateRequest)
            or not isinstance(decision, FeedbackGateDecision)
            or decision.gate_id != request.gate_id
            or decision.owner_user_id != request.owner_user_id
            or decision.request_fingerprint != request.fingerprint
            or decision.proposal_id != request.proposal_id
            or decision.proposal_fingerprint != request.proposal_fingerprint
            or not isinstance(human_attestation, FeedbackApprovalAttestation)
            or not isinstance(spend_attestation, FeedbackApprovalAttestation)
            or human_attestation.attestation_id != decision.human_attestation_id
            or human_attestation.fingerprint != decision.human_approval_fingerprint
            or spend_attestation.attestation_id != decision.spend_attestation_id
            or spend_attestation.fingerprint != decision.spend_approval_fingerprint
        ):
            raise ValueError("feedback gate evidence is invalid")
        data = _json(decision.canonical(), 65_536, "feedback gate")
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find_gate(connection, request.gate_id, request.owner_user_id)
                if existing is not None:
                    return _gate_replay(existing, request, decision)
                cursor = await connection.execute(
                    """INSERT INTO analytics_feedback_gates
                         (gate_id, owner_user_id, request_fingerprint,
                          proposal_id, proposal_fingerprint, account_id,
                          reservation_id, reservation_request_id, maximum_credits,
                          quoted_credits, quote_expires_at, human_approval_ref,
                          spend_approval_ref, human_attestation_id,
                          human_approval_fingerprint, spend_attestation_id,
                          spend_approval_fingerprint, definition_version,
                          gate_data, gate_fingerprint, storage_fingerprint,
                          approved_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s,
                               repeat('0', 64), %s)
                       ON CONFLICT DO NOTHING
                       RETURNING request_fingerprint, gate_fingerprint""",
                    (
                        decision.gate_id, decision.owner_user_id,
                        decision.request_fingerprint, decision.proposal_id,
                        decision.proposal_fingerprint, decision.account_id,
                        decision.reservation_id, decision.reservation_request_id,
                        decision.maximum_credits, decision.quoted_credits,
                        decision.quote_expires_at, request.human_approval_ref,
                        request.spend_approval_ref,
                        decision.human_attestation_id,
                        decision.human_approval_fingerprint,
                        decision.spend_attestation_id,
                        decision.spend_approval_fingerprint,
                        decision.definition_version, data, decision.fingerprint,
                        decision.approved_at,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    existing = await self._find_gate(
                        connection, request.gate_id, request.owner_user_id,
                    )
                    if existing is None:
                        raise FeedbackConflict("feedback gate identity is already in use")
                    return _gate_replay(existing, request, decision)
                return _gate_replay(row, request, decision)
        except (FeedbackConflict, FeedbackNotFound, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("feedback gate storage is unavailable") from exc

    async def record_outcome(
        self, *, request: FeedbackOutcomeRequest,
        outcome: FeedbackOutcome,
    ) -> FeedbackOutcome:
        if (
            not isinstance(request, FeedbackOutcomeRequest)
            or not isinstance(outcome, FeedbackOutcome)
            or outcome.outcome_id != request.outcome_id
            or outcome.owner_user_id != request.owner_user_id
            or outcome.request_fingerprint != request.fingerprint
            or outcome.gate_id != request.gate_id
            or outcome.gate_fingerprint != request.gate_fingerprint
            or outcome.report_request_id != request.report_request_id
            or outcome.report_fingerprint != request.report_fingerprint
        ):
            raise ValueError("feedback outcome evidence is invalid")
        data = _json(outcome.canonical(), 65_536, "feedback outcome")
        try:
            async with unit_of_work(self._pool) as connection:
                existing = await self._find_outcome(
                    connection, request.outcome_id, request.owner_user_id,
                )
                if existing is not None:
                    return _outcome_replay(existing, request, outcome)
                cursor = await connection.execute(
                    """INSERT INTO analytics_feedback_outcomes
                         (outcome_id, owner_user_id, request_fingerprint,
                          gate_id, gate_fingerprint, proposal_id,
                          proposal_fingerprint, report_request_id,
                          report_request_fingerprint, report_fingerprint,
                          definition_version, source_count, outcome_data,
                          outcome_fingerprint, storage_fingerprint, recorded_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s::jsonb, %s, repeat('0', 64), %s)
                       ON CONFLICT DO NOTHING
                       RETURNING request_fingerprint, outcome_fingerprint""",
                    (
                        outcome.outcome_id, outcome.owner_user_id,
                        outcome.request_fingerprint, outcome.gate_id,
                        outcome.gate_fingerprint, outcome.proposal_id,
                        outcome.proposal_fingerprint,
                        outcome.report_request_id,
                        outcome.report_request_fingerprint,
                        outcome.report_fingerprint,
                        outcome.definition_version, outcome.source_count,
                        data, outcome.fingerprint, outcome.recorded_at,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    existing = await self._find_outcome(
                        connection, request.outcome_id, request.owner_user_id,
                    )
                    if existing is None:
                        raise FeedbackConflict("feedback outcome identity is already in use")
                    return _outcome_replay(existing, request, outcome)
                return _outcome_replay(row, request, outcome)
        except (FeedbackConflict, FeedbackNotFound, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("feedback outcome storage is unavailable") from exc

    @staticmethod
    async def _find_gate(connection, gate_id, owner_user_id):
        cursor = await connection.execute(
            """SELECT request_fingerprint, gate_fingerprint
               FROM analytics_feedback_gates
               WHERE gate_id = %s AND owner_user_id = %s""",
            (gate_id, owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    async def _find_outcome(connection, outcome_id, owner_user_id):
        cursor = await connection.execute(
            """SELECT request_fingerprint, outcome_fingerprint
               FROM analytics_feedback_outcomes
               WHERE outcome_id = %s AND owner_user_id = %s""",
            (outcome_id, owner_user_id),
        )
        return await cursor.fetchone()


def _reservation(row) -> CreditReservationRecord:
    try:
        return CreditReservationRecord(
            id=row[0], flow_account_id=row[1], request_id=row[2],
            model_name=row[3], duration_seconds=row[4], quote_ref=row[5],
            quoted_credits=row[6], quote_source=CreditQuoteSource(row[7]),
            quoted_at=row[8], quote_expires_at=row[9],
            state=CreditReservationState(row[10]), created_at=row[11],
        )
    except (IndexError, TypeError, ValueError) as exc:
        raise RepositoryUnavailable("feedback reservation record is invalid") from exc


def _gate_replay(row, request, decision):
    if tuple(row) != (request.fingerprint, decision.fingerprint):
        raise FeedbackConflict("feedback gate request identifies different evidence")
    return decision


def _outcome_replay(row, request, outcome):
    if tuple(row) != (request.fingerprint, outcome.fingerprint):
        raise FeedbackConflict("feedback outcome request identifies different evidence")
    return outcome


def _json(value, limit, label):
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(serialized.encode("utf-8")) > limit:
        raise ValueError(f"{label} exceeds its byte limit")
    return serialized
