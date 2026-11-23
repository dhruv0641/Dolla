"""Owner-scoped persistence for exact community approvals and responses."""

from __future__ import annotations

import hashlib

from flowx_os.auth.tokens import Role
from flowx_os.community.comments import CommentState
from flowx_os.community.replies import ReplyDisposition
from flowx_os.community.responses import (
    ApprovalDecision,
    ApprovableDraft,
    CommunityResponseError,
    OfficialResponseClaim,
    OfficialResponseRequest,
    OfficialResponseResult,
    ProviderResponseReceipt,
    RemoteResponseProof,
    ReplyAuthorization,
    ResponseApprovalRecord,
    ResponseApprovalRequest,
    ResponseState,
)
from flowx_os.db.content import RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.publishing.reconciliation import PublicationPlatform


_CLAIM_COLUMNS = """request_id, approval_id, owner_user_id, request_fingerprint,
  approval_fingerprint, draft_fingerprint, draft_text, draft_text_fingerprint,
  publication_id, comment_version_id, platform, destination_id, credentials_ref,
  remote_object_id, remote_comment_id, state, remote_response_id"""


class CommunityResponseConflict(RuntimeError):
    """The idempotency key or exact evidence identifies different work."""


class CommunityResponseNotFound(RuntimeError):
    """Owned current response evidence is unavailable."""


def _receipt_fingerprint(receipt: ProviderResponseReceipt) -> str:
    values = (
        receipt.state.value, receipt.platform.value, receipt.destination_id,
        receipt.remote_object_id, receipt.parent_remote_comment_id,
        receipt.text_fingerprint, receipt.authorization_fingerprint,
        receipt.remote_response_id or "",
    )
    return hashlib.sha256("|".join(values).encode()).hexdigest()


class CommunityResponseRepository:
    def __init__(
        self, pool: ConnectionPool, *, approval_pool: ConnectionPool,
    ) -> None:
        self._pool = pool
        self._approval_pool = approval_pool

    async def load_approvable_draft(
        self, request: ResponseApprovalRequest,
    ) -> ApprovableDraft:
        if not isinstance(request, ResponseApprovalRequest):
            raise ValueError("response approval request is required")
        try:
            async with unit_of_work(self._approval_pool) as connection:
                row = await self._draft_row(connection, request, lock=True)
                if row is None:
                    raise CommunityResponseNotFound("owned current reply draft not found")
                return self._draft(row)
        except (CommunityResponseNotFound, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community response approval storage is unavailable") from exc

    async def save_approval(
        self, request: ResponseApprovalRequest, draft: ApprovableDraft,
        record: ResponseApprovalRecord,
    ) -> ResponseApprovalRecord:
        if (
            not isinstance(request, ResponseApprovalRequest)
            or not isinstance(draft, ApprovableDraft)
            or not isinstance(record, ResponseApprovalRecord)
            or record.request != request
            or record.draft_fingerprint != draft.fingerprint
            or record.draft_text_fingerprint != draft.text_fingerprint
        ):
            raise ValueError("response approval persistence identity is invalid")
        try:
            async with unit_of_work(self._approval_pool) as connection:
                current = await self._draft_row(connection, request, lock=True)
                if current is None or self._draft(current) != draft:
                    raise CommunityResponseConflict("reply draft changed before approval")
                cursor = await connection.execute(
                    """SELECT * FROM record_community_response_approval(
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )""",
                    (
                        request.approval_id, request.draft_request_id,
                        request.owner_user_id, request.reviewer_user_id,
                        request.reviewer_role.value, request.decision.value,
                        request.reason, request.decided_at, request.valid_until,
                        request.fingerprint, record.draft_fingerprint,
                        record.draft_text_fingerprint, record.record_fingerprint,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    cursor = await connection.execute(
                        """SELECT approval_id, draft_request_id, owner_user_id,
                             reviewer_user_id, reviewer_role, decision, reason,
                             decided_at, valid_until, request_fingerprint,
                             draft_fingerprint, draft_text_fingerprint,
                             record_fingerprint
                           FROM community_response_approvals
                           WHERE approval_id = %s AND owner_user_id = %s""",
                        (request.approval_id, request.owner_user_id),
                    )
                    row = await cursor.fetchone()
                if row is None:
                    raise CommunityResponseConflict("approval identity is unavailable")
                stored = self._approval(row)
                if stored != record:
                    raise CommunityResponseConflict("stored approval differs from exact replay")
                return stored
        except (CommunityResponseConflict, CommunityResponseNotFound, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community response approval storage is unavailable") from exc

    async def claim(self, request: OfficialResponseRequest) -> OfficialResponseClaim:
        if not isinstance(request, OfficialResponseRequest):
            raise ValueError("official response request is required")
        try:
            async with unit_of_work(self._pool) as connection:
                row = await self._claim_row(connection, request)
                if row is not None:
                    claim = self._claim(row)
                    if claim.request_fingerprint != request.fingerprint:
                        raise CommunityResponseConflict("official response request conflicts")
                    return claim
                cursor = await connection.execute(
                    """SELECT d.publication_id
                       FROM community_response_approvals AS a
                       JOIN community_reply_draft_records AS d
                         ON d.request_id = a.draft_request_id
                       WHERE a.approval_id = %s AND a.owner_user_id = %s
                         AND a.decision = 'APPROVE'
                         AND a.valid_until > clock_timestamp()""",
                    (request.approval_id, request.owner_user_id),
                )
                publication = await cursor.fetchone()
                if publication is None:
                    raise CommunityResponseNotFound("approved response evidence not found")
                cursor = await connection.execute(
                    """SELECT p.id FROM publication_jobs AS p
                       WHERE p.id = %s FOR UPDATE""",
                    (publication[0],),
                )
                if await cursor.fetchone() is None:
                    raise CommunityResponseNotFound("approved publication not found")
                cursor = await connection.execute(
                    """SELECT a.record_fingerprint, a.draft_fingerprint,
                              a.draft_text_fingerprint, d.draft_text,
                              d.publication_id, d.comment_version_id,
                              c.platform, c.destination_id, ch.credentials_ref,
                              c.remote_object_id, c.remote_comment_id
                       FROM community_response_approvals AS a
                       JOIN community_reply_draft_records AS d
                         ON d.request_id = a.draft_request_id
                       JOIN community_comments_current AS c
                         ON c.id = d.comment_version_id
                       JOIN publication_jobs AS p ON p.id = d.publication_id
                       JOIN social_channels AS ch ON ch.id = p.channel_id
                       JOIN brands AS b ON b.id = ch.brand_id
                       WHERE a.approval_id = %s AND a.owner_user_id = %s
                         AND a.decision = 'APPROVE' AND a.valid_until > clock_timestamp()
                         AND b.owner_user_id = %s AND p.status = 'PUBLISHED'
                         AND ch.enabled AND ch.permissions_status = 'VALID'""",
                    (request.approval_id, request.owner_user_id, request.owner_user_id),
                )
                evidence = await cursor.fetchone()
                if evidence is None:
                    raise CommunityResponseNotFound("approved current response evidence not found")
                cursor = await connection.execute(
                    f"""INSERT INTO community_official_responses
                      (request_id, approval_id, owner_user_id, request_fingerprint,
                       approval_fingerprint, draft_fingerprint, draft_text,
                       draft_text_fingerprint, publication_id, comment_version_id,
                       platform, destination_id, credentials_ref, remote_object_id,
                       remote_comment_id, state, requested_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, 'DRAFT', %s)
                    ON CONFLICT DO NOTHING RETURNING {_CLAIM_COLUMNS}""",
                    (
                        request.request_id, request.approval_id,
                        request.owner_user_id, request.fingerprint,
                        evidence[0], evidence[1], evidence[3], evidence[2],
                        evidence[4], evidence[5], evidence[6], evidence[7],
                        evidence[8], evidence[9], evidence[10], request.requested_at,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    row = await self._claim_row(connection, request)
                if row is None:
                    raise CommunityResponseConflict("response approval already identifies another request")
                claim = self._claim(row)
                if claim.request_fingerprint != request.fingerprint:
                    raise CommunityResponseConflict("official response request conflicts")
                return claim
        except (CommunityResponseConflict, CommunityResponseNotFound, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community response storage is unavailable") from exc

    async def assert_network_ready(self, claim: OfficialResponseClaim) -> None:
        if not isinstance(claim, OfficialResponseClaim):
            raise ValueError("official response claim is required")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT p.id FROM publication_jobs AS p
                       WHERE p.id = %s FOR UPDATE""",
                    (claim.publication_id,),
                )
                if await cursor.fetchone() is None:
                    raise CommunityResponseConflict("official response publication is unavailable")
                cursor = await connection.execute(
                    """SELECT 1
                       FROM community_official_responses AS r
                       JOIN community_response_approvals AS a ON a.approval_id = r.approval_id
                       JOIN community_reply_draft_records AS d ON d.request_id = a.draft_request_id
                       JOIN community_comments_current AS c ON c.id = r.comment_version_id
                       JOIN publication_jobs AS p ON p.id = r.publication_id
                       JOIN social_channels AS ch ON ch.id = p.channel_id
                       JOIN brands AS b ON b.id = ch.brand_id
                       WHERE r.request_id = %s AND r.owner_user_id = %s
                         AND r.request_fingerprint = %s AND r.state = %s
                         AND a.decision = 'APPROVE'
                         AND a.record_fingerprint = r.approval_fingerprint
                         AND d.record_fingerprint = r.draft_fingerprint
                         AND d.draft_text = r.draft_text
                         AND c.id = d.comment_version_id
                         AND c.platform = r.platform AND c.destination_id = r.destination_id
                         AND c.remote_object_id = r.remote_object_id
                         AND c.remote_comment_id = r.remote_comment_id
                         AND b.owner_user_id = r.owner_user_id
                         AND p.status = 'PUBLISHED' AND ch.enabled
                         AND ch.permissions_status = 'VALID'
                         AND ch.external_channel_id = r.destination_id
                         AND ch.credentials_ref = r.credentials_ref
                         AND (
                           r.state = 'VERIFY_PENDING' OR (
                             a.valid_until > clock_timestamp()
                             AND c.state <> 'DELETED'
                             AND NOT EXISTS (
                               SELECT 1 FROM community_analysis_reports AS newer
                               WHERE newer.publication_id = d.publication_id
                                 AND (newer.created_at, newer.request_id::text) >
                                     ((SELECT created_at FROM community_analysis_reports
                                       WHERE request_id = d.analysis_request_id),
                                      d.analysis_request_id::text)
                             )
                           )
                         )
                         AND (
                           r.state <> 'MUTATION_RESERVED' OR (
                             r.authorization_checked_at >= clock_timestamp() - interval '300 seconds'
                             AND r.authorization_valid_until >= clock_timestamp() + interval '30 seconds'
                           )
                         )""",
                    (claim.request_id, claim.owner_user_id, claim.request_fingerprint, claim.state.value),
                )
                if await cursor.fetchone() is None:
                    raise CommunityResponseConflict("official response is no longer network-ready")
        except (CommunityResponseConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community response readiness is unavailable") from exc

    async def reserve_mutation(
        self, claim: OfficialResponseClaim, authorization: ReplyAuthorization,
    ) -> OfficialResponseClaim:
        if not isinstance(claim, OfficialResponseClaim) or not isinstance(authorization, ReplyAuthorization):
            raise ValueError("official response reservation is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""UPDATE community_official_responses
                        SET state = 'MUTATION_RESERVED',
                            authorization_fingerprint = %s,
                            authorization_scopes = %s,
                            authorization_checked_at = %s,
                            authorization_valid_until = %s,
                            mutation_reserved_at = clock_timestamp()
                        WHERE request_id = %s AND owner_user_id = %s
                          AND request_fingerprint = %s AND state = 'DRAFT'
                        RETURNING {_CLAIM_COLUMNS}""",
                    (
                        authorization.fingerprint, list(authorization.granted_scopes),
                        authorization.checked_at, authorization.valid_until,
                        claim.request_id, claim.owner_user_id, claim.request_fingerprint,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise CommunityResponseConflict("official response mutation is already reserved")
                return self._claim(row)
        except (CommunityResponseConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community response reservation is unavailable") from exc

    async def refresh_mutation_authorization(
        self, claim: OfficialResponseClaim, authorization: ReplyAuthorization,
    ) -> OfficialResponseClaim:
        if not isinstance(claim, OfficialResponseClaim) or not isinstance(authorization, ReplyAuthorization):
            raise ValueError("official response authorization refresh is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""UPDATE community_official_responses
                        SET authorization_fingerprint = %s,
                            authorization_scopes = %s,
                            authorization_checked_at = %s,
                            authorization_valid_until = %s
                        WHERE request_id = %s AND owner_user_id = %s
                          AND request_fingerprint = %s
                          AND state = 'MUTATION_RESERVED'
                          AND remote_response_id IS NULL
                          AND receipt_state IS NULL
                        RETURNING {_CLAIM_COLUMNS}""",
                    (
                        authorization.fingerprint, list(authorization.granted_scopes),
                        authorization.checked_at, authorization.valid_until,
                        claim.request_id, claim.owner_user_id, claim.request_fingerprint,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise CommunityResponseConflict("official response authorization refresh conflicts")
                return self._claim(row)
        except (CommunityResponseConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community response authorization refresh is unavailable") from exc

    async def record_receipt(
        self, claim: OfficialResponseClaim, receipt: ProviderResponseReceipt,
    ) -> OfficialResponseClaim:
        if not isinstance(claim, OfficialResponseClaim) or not isinstance(receipt, ProviderResponseReceipt):
            raise ValueError("official response receipt is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""UPDATE community_official_responses
                        SET state = 'VERIFY_PENDING', receipt_state = %s,
                            receipt_fingerprint = %s, remote_response_id = %s,
                            error_code = NULL
                        WHERE request_id = %s AND owner_user_id = %s
                          AND request_fingerprint = %s AND state = 'MUTATION_RESERVED'
                        RETURNING {_CLAIM_COLUMNS}""",
                    (
                        receipt.state.value, _receipt_fingerprint(receipt),
                        receipt.remote_response_id, claim.request_id,
                        claim.owner_user_id, claim.request_fingerprint,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise CommunityResponseConflict("official response receipt conflicts")
                return self._claim(row)
        except (CommunityResponseConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community response receipt storage is unavailable") from exc

    async def record_transport_failure(
        self, claim: OfficialResponseClaim, error: CommunityResponseError,
    ) -> None:
        if not isinstance(claim, OfficialResponseClaim) or not isinstance(error, CommunityResponseError):
            raise ValueError("official response failure is invalid")
        target = "VERIFY_PENDING" if error.ambiguous else "FAILED"
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """UPDATE community_official_responses
                       SET state = %s, error_code = %s
                       WHERE request_id = %s AND owner_user_id = %s
                         AND request_fingerprint = %s AND state = 'MUTATION_RESERVED'
                       RETURNING request_id""",
                    (target, error.code, claim.request_id, claim.owner_user_id, claim.request_fingerprint),
                )
                if await cursor.fetchone() is None:
                    raise CommunityResponseConflict("official response failure conflicts")
        except (CommunityResponseConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community response failure storage is unavailable") from exc

    async def record_verification(
        self, claim: OfficialResponseClaim, proof: RemoteResponseProof,
    ) -> OfficialResponseResult:
        if not isinstance(claim, OfficialResponseClaim) or not isinstance(proof, RemoteResponseProof):
            raise ValueError("official response proof is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """UPDATE community_official_responses
                       SET state = 'RESPONDED', verification_evidence_id = %s,
                           verification_observed_at = %s,
                           verification_fingerprint = %s,
                           verification_platform = %s,
                           verification_destination_id = %s,
                           verification_remote_object_id = %s,
                           verification_parent_comment_id = %s,
                           verification_text_fingerprint = %s,
                           verification_visible = %s, error_code = NULL
                       WHERE request_id = %s AND owner_user_id = %s
                         AND request_fingerprint = %s AND state = 'VERIFY_PENDING'
                         AND remote_response_id = %s
                       RETURNING request_id, state, remote_response_id""",
                    (
                        proof.evidence_id, proof.observed_at, proof.fingerprint,
                        proof.platform.value, proof.destination_id,
                        proof.remote_object_id, proof.parent_remote_comment_id,
                        proof.text_fingerprint, proof.visible, claim.request_id,
                        claim.owner_user_id, claim.request_fingerprint,
                        proof.remote_response_id,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise CommunityResponseConflict("official response proof conflicts")
                return OfficialResponseResult(row[0], ResponseState(row[1]), row[2])
        except (CommunityResponseConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community response verification storage is unavailable") from exc

    async def recover_response_identity(
        self, request: OfficialResponseRequest, remote_response_id: str,
        recovery_evidence_id: str,
    ) -> OfficialResponseClaim:
        if (
            not isinstance(request, OfficialResponseRequest)
            or not isinstance(remote_response_id, str)
            or not isinstance(recovery_evidence_id, str)
        ):
            raise ValueError("official response recovery is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""UPDATE community_official_responses
                        SET remote_response_id = %s, recovery_evidence_id = %s,
                            identity_recovered_at = clock_timestamp()
                        WHERE request_id = %s AND approval_id = %s
                          AND owner_user_id = %s AND request_fingerprint = %s
                          AND state = 'VERIFY_PENDING' AND remote_response_id IS NULL
                        RETURNING {_CLAIM_COLUMNS}""",
                    (
                        remote_response_id, recovery_evidence_id,
                        request.request_id, request.approval_id,
                        request.owner_user_id, request.fingerprint,
                    ),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise CommunityResponseConflict("response identity recovery conflicts")
                return self._claim(row)
        except (CommunityResponseConflict, ValueError):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("community response recovery is unavailable") from exc

    @staticmethod
    async def _draft_row(connection, request, *, lock):
        cursor = await connection.execute(
            """SELECT d.request_id, d.owner_user_id, d.publication_id,
                      d.comment_version_id, d.record_fingerprint,
                      d.classification_fingerprint, d.disposition, d.draft_text,
                      d.escalation_reasons, d.outbound_action_authorized,
                      c.platform, c.destination_id, c.remote_object_id,
                      c.remote_comment_id, c.state
               FROM community_reply_draft_records AS d
               JOIN community_comments_current AS c ON c.id = d.comment_version_id
               JOIN publication_jobs AS p ON p.id = d.publication_id
               JOIN social_channels AS ch ON ch.id = p.channel_id
               JOIN brands AS b ON b.id = ch.brand_id
               WHERE d.request_id = %s AND d.owner_user_id = %s
                 AND b.owner_user_id = %s""" + (" FOR UPDATE OF p" if lock else ""),
            (request.draft_request_id, request.owner_user_id, request.owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    def _draft(row) -> ApprovableDraft:
        return ApprovableDraft(
            draft_request_id=row[0], owner_user_id=row[1], publication_id=row[2],
            comment_version_id=row[3], record_fingerprint=row[4],
            classification_fingerprint=row[5], disposition=ReplyDisposition(row[6]),
            draft_text=row[7], escalation_reasons=tuple(row[8]),
            outbound_action_authorized=row[9], platform=PublicationPlatform(row[10]),
            destination_id=row[11], remote_object_id=row[12],
            remote_comment_id=row[13], comment_state=CommentState(row[14]),
        )

    @staticmethod
    def _approval(row) -> ResponseApprovalRecord:
        request = ResponseApprovalRequest(
            approval_id=row[0], draft_request_id=row[1], owner_user_id=row[2],
            reviewer_user_id=row[3], reviewer_role=Role(row[4]),
            decision=ApprovalDecision(row[5]), reason=row[6],
            decided_at=row[7], valid_until=row[8],
        )
        if request.fingerprint != row[9]:
            raise RepositoryUnavailable("stored response approval is invalid")
        return ResponseApprovalRecord(request, row[10], row[11], row[12])

    @staticmethod
    async def _claim_row(connection, request):
        cursor = await connection.execute(
            f"""SELECT {_CLAIM_COLUMNS} FROM community_official_responses
                WHERE request_id = %s AND owner_user_id = %s""",
            (request.request_id, request.owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    def _claim(row) -> OfficialResponseClaim:
        try:
            return OfficialResponseClaim(
                request_id=row[0], approval_id=row[1], owner_user_id=row[2],
                request_fingerprint=row[3], approval_fingerprint=row[4],
                draft_fingerprint=row[5], draft_text=row[6],
                draft_text_fingerprint=row[7], publication_id=row[8],
                comment_version_id=row[9], platform=PublicationPlatform(row[10]),
                destination_id=row[11], credentials_ref=row[12],
                remote_object_id=row[13], remote_comment_id=row[14],
                state=ResponseState(row[15]), remote_response_id=row[16],
            )
        except Exception as exc:
            raise RepositoryUnavailable("stored community response is invalid") from exc
