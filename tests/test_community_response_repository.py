from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import unittest
from uuid import uuid4

from flowx_os.auth.tokens import Role
from flowx_os.community.comments import CommentState
from flowx_os.community.replies import ReplyDisposition
from flowx_os.community.responses import (
    ApprovalDecision, ApprovableDraft, OfficialResponseClaim,
    OfficialResponseRequest, ReplyAuthorization, ResponseApprovalRecord,
    ResponseApprovalRequest, ResponseState, YOUTUBE_REPLY_SCOPE,
)
from flowx_os.db.community_responses import CommunityResponseRepository
from flowx_os.publishing.reconciliation import PublicationPlatform


NOW = datetime(2026, 11, 23, 18, tzinfo=timezone.utc)


class Cursor:
    def __init__(self, row=None): self.row = row
    async def fetchone(self): return self.row


class Connection:
    def __init__(self, rows=()): self.rows, self.calls = list(rows), []
    @asynccontextmanager
    async def transaction(self): yield self
    async def execute(self, query, params=None):
        self.calls.append((query, params))
        return Cursor(self.rows.pop(0) if self.rows else None)


class Pool:
    def __init__(self, value): self.value = value
    @asynccontextmanager
    async def connection(self): yield self.value


def target():
    return ApprovableDraft(
        uuid4(), "owner-1", uuid4(), uuid4(), "a" * 64, "b" * 64,
        ReplyDisposition.DRAFT_REQUIRES_HUMAN_APPROVAL,
        "Thanks for your comment.", (), False, PublicationPlatform.YOUTUBE,
        "UCchannel", "video123", "comment123", CommentState.ACTIVE,
    )


def target_row(value):
    return (
        value.draft_request_id, value.owner_user_id, value.publication_id,
        value.comment_version_id, value.record_fingerprint,
        value.classification_fingerprint, value.disposition.value,
        value.draft_text, list(value.escalation_reasons),
        value.outbound_action_authorized, value.platform.value,
        value.destination_id, value.remote_object_id, value.remote_comment_id,
        value.comment_state.value,
    )


def approval(value):
    request = ResponseApprovalRequest(
        uuid4(), value.draft_request_id, value.owner_user_id, "reviewer-1",
        Role.REVIEWER, ApprovalDecision.APPROVE, "Approved after review.", NOW,
        NOW + timedelta(hours=1),
    )
    fingerprint = hashlib.sha256("|".join((
        request.fingerprint, value.fingerprint, value.text_fingerprint,
    )).encode()).hexdigest()
    record = ResponseApprovalRecord(
        request, value.fingerprint, value.text_fingerprint, fingerprint,
    )
    return request, record


def approval_row(record):
    request = record.request
    return (
        request.approval_id, request.draft_request_id, request.owner_user_id,
        request.reviewer_user_id, request.reviewer_role.value,
        request.decision.value, request.reason, request.decided_at,
        request.valid_until, request.fingerprint, record.draft_fingerprint,
        record.draft_text_fingerprint, record.record_fingerprint,
    )


def response_claim(value, request, record, state=ResponseState.DRAFT):
    return OfficialResponseClaim(
        request.request_id, request.approval_id, request.owner_user_id,
        request.fingerprint, record.record_fingerprint, value.fingerprint,
        value.draft_text, value.text_fingerprint, value.publication_id,
        value.comment_version_id, value.platform, value.destination_id,
        "secretref://vault/youtube/community", value.remote_object_id,
        value.remote_comment_id, state,
    )


def claim_row(value):
    return (
        value.request_id, value.approval_id, value.owner_user_id,
        value.request_fingerprint, value.approval_fingerprint,
        value.draft_fingerprint, value.draft_text,
        value.draft_text_fingerprint, value.publication_id,
        value.comment_version_id, value.platform.value, value.destination_id,
        value.credentials_ref, value.remote_object_id,
        value.remote_comment_id, value.state.value, value.remote_response_id,
    )


class CommunityResponseRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_approval_target_is_owner_scoped_current_and_locked(self):
        value = target()
        request, _ = approval(value)
        connection = Connection([target_row(value)])
        loaded = await CommunityResponseRepository(Pool(connection)).load_approvable_draft(request)
        self.assertEqual(loaded, value)
        query, params = connection.calls[0]
        self.assertIn("community_comments_current", query)
        self.assertIn("FOR UPDATE OF p", query)
        self.assertEqual(params, (value.draft_request_id, value.owner_user_id, value.owner_user_id))

    async def test_save_approval_rechecks_target_and_inserts_role_evidence(self):
        value = target()
        request, record = approval(value)
        connection = Connection([target_row(value), approval_row(record)])
        stored = await CommunityResponseRepository(Pool(connection)).save_approval(
            request, value, record,
        )
        self.assertEqual(stored, record)
        query, params = connection.calls[1]
        self.assertIn("record_community_response_approval", query)
        self.assertIn(Role.REVIEWER.value, params)

    async def test_claim_inserts_exact_approved_current_destination_snapshot(self):
        value = target()
        _, record = approval(value)
        request = OfficialResponseRequest(uuid4(), record.request.approval_id, value.owner_user_id, NOW)
        claim = response_claim(value, request, record)
        evidence = (
            record.record_fingerprint, value.fingerprint, value.text_fingerprint,
            value.draft_text, value.publication_id, value.comment_version_id,
            value.platform.value, value.destination_id,
            "secretref://vault/youtube/community", value.remote_object_id,
            value.remote_comment_id,
        )
        connection = Connection([
            None, (value.publication_id,), (value.publication_id,),
            evidence, claim_row(claim),
        ])
        stored = await CommunityResponseRepository(Pool(connection)).claim(request)
        self.assertEqual(stored, claim)
        sql = "\n".join(query for query, _ in connection.calls)
        self.assertIn("a.valid_until > clock_timestamp()", sql)
        self.assertIn("WHERE p.id = %s FOR UPDATE", sql)
        self.assertIn("INSERT INTO community_official_responses", sql)

    async def test_mutation_reservation_is_single_winner_with_exact_authorization(self):
        value = target()
        _, record = approval(value)
        request = OfficialResponseRequest(uuid4(), record.request.approval_id, value.owner_user_id, NOW)
        claim = response_claim(value, request, record)
        reserved = response_claim(value, request, record, ResponseState.MUTATION_RESERVED)
        authorization = ReplyAuthorization(
            PublicationPlatform.YOUTUBE, value.destination_id,
            (YOUTUBE_REPLY_SCOPE,), NOW - timedelta(seconds=5),
            NOW + timedelta(minutes=5),
        )
        connection = Connection([claim_row(reserved)])
        stored = await CommunityResponseRepository(Pool(connection)).reserve_mutation(
            claim, authorization,
        )
        self.assertEqual(stored.state, ResponseState.MUTATION_RESERVED)
        query, params = connection.calls[0]
        self.assertIn("state = 'DRAFT'", query)
        self.assertEqual(params[0], authorization.fingerprint)
        self.assertEqual(params[1], [YOUTUBE_REPLY_SCOPE])

    async def test_readiness_locks_publication_before_current_evidence_query(self):
        value = target()
        _, record = approval(value)
        request = OfficialResponseRequest(uuid4(), record.request.approval_id, value.owner_user_id, NOW)
        claim = response_claim(value, request, record)
        connection = Connection([(value.publication_id,), (1,)])
        await CommunityResponseRepository(Pool(connection)).assert_network_ready(claim)
        self.assertIn("WHERE p.id = %s FOR UPDATE", connection.calls[0][0])
        self.assertNotIn("community_comments_current", connection.calls[0][0])
        self.assertIn("community_comments_current", connection.calls[1][0])

    async def test_refresh_binds_second_authorization_to_reserved_claim(self):
        value = target()
        _, record = approval(value)
        request = OfficialResponseRequest(uuid4(), record.request.approval_id, value.owner_user_id, NOW)
        claim = response_claim(value, request, record, ResponseState.MUTATION_RESERVED)
        authorization = ReplyAuthorization(
            PublicationPlatform.YOUTUBE, value.destination_id,
            (YOUTUBE_REPLY_SCOPE,), NOW - timedelta(seconds=2),
            NOW + timedelta(minutes=5),
        )
        connection = Connection([claim_row(claim)])
        stored = await CommunityResponseRepository(Pool(connection)).refresh_mutation_authorization(
            claim, authorization,
        )
        self.assertEqual(stored, claim)
        query, params = connection.calls[0]
        self.assertIn("state = 'MUTATION_RESERVED'", query)
        self.assertIn("receipt_state IS NULL", query)
        self.assertEqual(params[0], authorization.fingerprint)


if __name__ == "__main__": unittest.main()
