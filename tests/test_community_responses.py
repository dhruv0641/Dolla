from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import unittest

from flowx_os.auth.tokens import Principal, Role
from flowx_os.community.comments import CommentState
from flowx_os.community.replies import ReplyDisposition
from flowx_os.community.responses import (
    ApprovalDecision,
    ApprovableDraft,
    CommunityResponseError,
    CommunityResponsePolicy,
    CommunityResponseService,
    OfficialResponseClaim,
    OfficialResponseRequest,
    ProviderMutationState,
    ProviderResponseReceipt,
    RemoteResponseProof,
    ReplyAuthorization,
    ResponseApprovalRequest,
    ResponseState,
    YOUTUBE_REPLY_SCOPE,
)
from flowx_os.publishing.reconciliation import PublicationPlatform


NOW = datetime(2026, 11, 23, 18, tzinfo=timezone.utc)
OWNER = "owner@example.test"
REVIEWER = "reviewer@example.test"


def draft(**changes) -> ApprovableDraft:
    value = ApprovableDraft(
        draft_request_id=uuid4(), owner_user_id=OWNER, publication_id=uuid4(),
        comment_version_id=uuid4(), record_fingerprint="a" * 64,
        classification_fingerprint="b" * 64,
        disposition=ReplyDisposition.DRAFT_REQUIRES_HUMAN_APPROVAL,
        draft_text="Thanks for your comment.", escalation_reasons=(),
        outbound_action_authorized=False, platform=PublicationPlatform.YOUTUBE,
        destination_id="UCchannel", remote_object_id="video123",
        remote_comment_id="comment123", comment_state=CommentState.ACTIVE,
    )
    return replace(value, **changes)


def approval_request(value: ApprovableDraft, **changes) -> ResponseApprovalRequest:
    request = ResponseApprovalRequest(
        approval_id=uuid4(), draft_request_id=value.draft_request_id,
        owner_user_id=OWNER, reviewer_user_id=REVIEWER,
        reviewer_role=Role.REVIEWER,
        decision=ApprovalDecision.APPROVE, reason="Reviewed and approved.",
        decided_at=NOW, valid_until=NOW + timedelta(hours=1),
    )
    return replace(request, **changes)


def response_request(approval_id: UUID) -> OfficialResponseRequest:
    return OfficialResponseRequest(uuid4(), approval_id, OWNER, NOW)


class Store:
    def __init__(self, target: ApprovableDraft) -> None:
        self.target = target
        self.saved = None
        self.claim_value = None
        self.reserve_calls = 0
        self.ready_calls = 0
        self.failure = None
        self.receipt = None
        self.proof = None
        self.corrupt_reservation = False
        self.corrupt_verification = False

    async def load_approvable_draft(self, request):
        return self.target

    async def save_approval(self, request, target, record):
        self.saved = record
        return record

    async def claim(self, request):
        return self.claim_value

    async def assert_network_ready(self, claim):
        self.ready_calls += 1

    async def reserve_mutation(self, claim, authorization):
        self.reserve_calls += 1
        self.claim_value = replace(claim, state=ResponseState.MUTATION_RESERVED)
        if self.corrupt_reservation:
            self.claim_value = replace(self.claim_value, destination_id="other")
        return self.claim_value

    async def refresh_mutation_authorization(self, claim, authorization):
        return claim

    async def record_receipt(self, claim, receipt):
        self.receipt = receipt
        self.claim_value = replace(
            claim, state=ResponseState.VERIFY_PENDING,
            remote_response_id=receipt.remote_response_id,
        )
        return self.claim_value

    async def record_transport_failure(self, claim, error):
        self.failure = error

    async def record_verification(self, claim, proof):
        self.proof = proof
        self.claim_value = replace(claim, state=ResponseState.RESPONDED)
        from flowx_os.community.responses import OfficialResponseResult
        return OfficialResponseResult(
            uuid4() if self.corrupt_verification else claim.request_id,
            ResponseState.RESPONDED, claim.remote_response_id,
        )

    async def recover_response_identity(self, request, remote_response_id, recovery_evidence_id):
        self.claim_value = replace(
            self.claim_value, state=ResponseState.VERIFY_PENDING,
            remote_response_id=remote_response_id,
        )
        return self.claim_value


class Transport:
    def __init__(self) -> None:
        self.create_calls = 0
        self.get_calls = 0
        self.authorization_calls = 0
        self.raise_create = False
        self.authorization = ReplyAuthorization(
            PublicationPlatform.YOUTUBE, "UCchannel", (YOUTUBE_REPLY_SCOPE,),
            NOW - timedelta(seconds=10), NOW + timedelta(minutes=10),
        )
        self.authorization_sequence = []
        self.receipt = ProviderResponseReceipt(
            ProviderMutationState.ACCEPTED, PublicationPlatform.YOUTUBE,
            "UCchannel", "video123", "comment123",
            "0" * 64, "1" * 64, "reply123",
        )
        self.proof = RemoteResponseProof(
            PublicationPlatform.YOUTUBE, "UCchannel", "video123", "reply123",
            "comment123", "0" * 64, True, NOW, "evidence-123",
        )

    async def check_authorization(self, **kwargs):
        self.authorization_calls += 1
        if self.authorization_sequence:
            return self.authorization_sequence.pop(0)
        return self.authorization

    async def create_response(self, **kwargs):
        self.create_calls += 1
        if self.raise_create:
            raise TimeoutError("unknown")
        return self.receipt

    async def get_response(self, **kwargs):
        self.get_calls += 1
        return self.proof


def service(target=None, *, enabled=True):
    value = target or draft()
    store = Store(value)
    transport = Transport()
    instance = CommunityResponseService(
        store=store, transport=transport,
        policy=CommunityResponsePolicy(enabled=enabled),
    )
    return value, store, transport, instance


def install_claim(value, store, transport, request, approval):
    store.claim_value = OfficialResponseClaim(
        request_id=request.request_id, approval_id=request.approval_id,
        owner_user_id=OWNER, request_fingerprint=request.fingerprint,
        approval_fingerprint=approval.fingerprint,
        draft_fingerprint=value.fingerprint, draft_text=value.draft_text,
        draft_text_fingerprint=value.text_fingerprint,
        publication_id=value.publication_id,
        comment_version_id=value.comment_version_id,
        platform=value.platform, destination_id=value.destination_id,
        credentials_ref="secretref://vault/youtube/community",
        remote_object_id=value.remote_object_id,
        remote_comment_id=value.remote_comment_id, state=ResponseState.DRAFT,
    )
    transport.receipt = replace(
        transport.receipt, text_fingerprint=value.text_fingerprint,
        authorization_fingerprint=transport.authorization.fingerprint,
    )
    transport.proof = replace(transport.proof, text_fingerprint=value.text_fingerprint)


class CommunityResponseServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_reviewer_approves_exact_clean_draft(self):
        value, store, _, instance = service()
        request = approval_request(value)
        record = await instance.decide(
            request, Principal(REVIEWER, frozenset({Role.REVIEWER})), now=NOW,
        )
        assert record.request == request
        assert record.draft_fingerprint == value.fingerprint
        assert store.saved == record


    async def test_admin_can_reject_an_escalated_record_but_cannot_approve_it(self):
        value = draft(
            disposition=ReplyDisposition.ESCALATED_NO_DRAFT, draft_text=None,
            escalation_reasons=("safety-harassment",),
        )
        _, _, _, instance = service(value)
        rejected = approval_request(
            value, decision=ApprovalDecision.REJECT, reviewer_role=Role.ADMIN,
        )
        assert (await instance.decide(
            rejected, Principal(REVIEWER, frozenset({Role.ADMIN})), now=NOW,
        )).request.decision is ApprovalDecision.REJECT
        approved = approval_request(value, reviewer_role=Role.ADMIN)
        with self.assertRaisesRegex(CommunityResponseError, "cannot be approved"):
            await instance.decide(
                approved, Principal(REVIEWER, frozenset({Role.ADMIN})), now=NOW,
            )


    async def test_operator_or_different_subject_cannot_decide(self):
        value, _, _, instance = service()
        request = approval_request(value)
        for principal in (
            Principal(REVIEWER, frozenset({Role.OPERATOR})),
            Principal("other", frozenset({Role.REVIEWER})),
        ):
            with self.assertRaises(CommunityResponseError) as caught:
                await instance.decide(request, principal, now=NOW)
            assert caught.exception.code == "REVIEWER_NOT_AUTHORIZED"


    async def test_official_response_is_disabled_by_default(self):
        value, _, _, instance = service(enabled=False)
        request = response_request(uuid4())
        with self.assertRaises(CommunityResponseError) as caught:
            await instance.respond(request, now=NOW)
        assert caught.exception.code == "RESPONSES_DISABLED"


    async def test_success_requires_reservation_and_independent_remote_proof(self):
        value, store, transport, instance = service()
        approval = approval_request(value)
        request = response_request(approval.approval_id)
        install_claim(value, store, transport, request, approval)
        result = await instance.respond(request, now=NOW)
        assert result.state is ResponseState.RESPONDED
        assert result.remote_response_id == "reply123"
        assert store.reserve_calls == 1
        assert transport.create_calls == 1
        assert transport.authorization_calls == 2
        assert transport.get_calls == 1
        assert store.ready_calls == 3


    async def test_insufficient_or_stale_authorization_fails_before_mutation(self):
        value, store, transport, instance = service()
        approval = approval_request(value)
        request = response_request(approval.approval_id)
        install_claim(value, store, transport, request, approval)
        transport.authorization = replace(transport.authorization, granted_scopes=("youtube.readonly",))
        with self.assertRaises(CommunityResponseError) as caught:
            await instance.respond(request, now=NOW)
        assert caught.exception.code == "AUTHORIZATION_INVALID"
        assert transport.create_calls == 0
        transport.authorization = ReplyAuthorization(
            PublicationPlatform.YOUTUBE, "UCchannel", (YOUTUBE_REPLY_SCOPE,),
            NOW - timedelta(minutes=6), NOW + timedelta(minutes=1),
        )
        with self.assertRaises(CommunityResponseError) as caught:
            await instance.respond(request, now=NOW)
        assert caught.exception.code == "AUTHORIZATION_INVALID"


    async def test_authorization_is_rechecked_after_reservation_before_mutation(self):
        value, store, transport, instance = service()
        approval = approval_request(value)
        request = response_request(approval.approval_id)
        install_claim(value, store, transport, request, approval)
        revoked = replace(transport.authorization, granted_scopes=("youtube.readonly",))
        transport.authorization_sequence = [transport.authorization, revoked]
        with self.assertRaises(CommunityResponseError) as caught:
            await instance.respond(request, now=NOW)
        assert caught.exception.code == "AUTHORIZATION_INVALID"
        assert store.reserve_calls == 1
        assert transport.authorization_calls == 2
        assert transport.create_calls == 0
        assert store.failure is caught.exception
        assert not store.failure.ambiguous


    async def test_transport_exception_is_ambiguous_and_never_auto_retried(self):
        value, store, transport, instance = service()
        approval = approval_request(value)
        request = response_request(approval.approval_id)
        install_claim(value, store, transport, request, approval)
        transport.raise_create = True
        with self.assertRaises(CommunityResponseError) as caught:
            await instance.respond(request, now=NOW)
        assert caught.exception.code == "TRANSPORT_OUTCOME_UNKNOWN"
        assert caught.exception.ambiguous
        assert store.failure is caught.exception
        store.claim_value = replace(store.claim_value, state=ResponseState.VERIFY_PENDING)
        with self.assertRaises(CommunityResponseError) as caught:
            await instance.respond(request, now=NOW)
        assert caught.exception.code == "RESPONSE_OUTCOME_UNKNOWN"
        assert transport.create_calls == 1


    async def test_mismatched_receipt_is_ambiguous_and_not_verified(self):
        value, store, transport, instance = service()
        approval = approval_request(value)
        request = response_request(approval.approval_id)
        install_claim(value, store, transport, request, approval)
        transport.receipt = replace(transport.receipt, parent_remote_comment_id="other")
        with self.assertRaises(CommunityResponseError) as caught:
            await instance.respond(request, now=NOW)
        assert caught.exception.code == "REMOTE_RESPONSE_INVALID"
        assert caught.exception.ambiguous
        assert transport.get_calls == 0


    async def test_unknown_receipt_requires_identity_recovery_then_read_only_verification(self):
        value, store, transport, instance = service()
        approval = approval_request(value)
        request = response_request(approval.approval_id)
        install_claim(value, store, transport, request, approval)
        transport.receipt = replace(
            transport.receipt, state=ProviderMutationState.UNKNOWN,
            remote_response_id=None,
        )
        result = await instance.respond(request, now=NOW)
        assert result.state is ResponseState.VERIFY_PENDING
        await instance.recover_identity(request, "reply123", "operator-read-123")
        result = await instance.reconcile(request, now=NOW)
        assert result.state is ResponseState.RESPONDED
        assert transport.create_calls == 1


    async def test_remote_proof_must_match_exact_parent_and_text(self):
        value, store, transport, instance = service()
        approval = approval_request(value)
        request = response_request(approval.approval_id)
        install_claim(value, store, transport, request, approval)
        store.claim_value = replace(
            store.claim_value, state=ResponseState.VERIFY_PENDING,
            remote_response_id="reply123",
        )
        transport.proof = replace(transport.proof, parent_remote_comment_id="other")
        with self.assertRaises(CommunityResponseError) as caught:
            await instance.respond(request, now=NOW)
        assert caught.exception.code == "REMOTE_PROOF_INVALID"
        assert transport.create_calls == 0


    async def test_future_remote_proof_is_rejected(self):
        value, store, transport, instance = service()
        approval = approval_request(value)
        request = response_request(approval.approval_id)
        install_claim(value, store, transport, request, approval)
        store.claim_value = replace(
            store.claim_value, state=ResponseState.VERIFY_PENDING,
            remote_response_id="reply123",
        )
        transport.proof = replace(transport.proof, observed_at=NOW + timedelta(seconds=1))
        with self.assertRaises(CommunityResponseError) as caught:
            await instance.respond(request, now=NOW)
        assert caught.exception.code == "REMOTE_PROOF_INVALID"


    async def test_injected_store_cannot_change_claim_identity_or_final_result(self):
        value, store, transport, instance = service()
        approval = approval_request(value)
        request = response_request(approval.approval_id)
        install_claim(value, store, transport, request, approval)
        store.corrupt_reservation = True
        with self.assertRaises(CommunityResponseError) as caught:
            await instance.respond(request, now=NOW)
        assert caught.exception.code == "STORED_CLAIM_INVALID"
        assert transport.create_calls == 0

        install_claim(value, store, transport, request, approval)
        store.claim_value = replace(
            store.claim_value, state=ResponseState.VERIFY_PENDING,
            remote_response_id="reply123",
        )
        store.corrupt_reservation = False
        store.corrupt_verification = True
        with self.assertRaises(CommunityResponseError) as caught:
            await instance.respond(request, now=NOW)
        assert caught.exception.code == "VERIFICATION_RESULT_INVALID"


    async def test_terminal_response_replays_without_network(self):
        value, store, transport, instance = service()
        approval = approval_request(value)
        request = response_request(approval.approval_id)
        install_claim(value, store, transport, request, approval)
        store.claim_value = replace(
            store.claim_value, state=ResponseState.RESPONDED,
            remote_response_id="reply123",
        )
        result = await instance.respond(request, now=NOW)
        assert result.state is ResponseState.RESPONDED
        assert store.ready_calls == transport.create_calls == transport.get_calls == 0


    def test_approval_expiry_and_unsafe_reason_are_rejected(self):
        value = draft()
        with self.assertRaises(ValueError):
            approval_request(value, valid_until=NOW + timedelta(days=2))
        with self.assertRaises(ValueError):
            approval_request(value, reason="token=super-secret")


    async def test_expired_or_future_approval_is_rejected_before_store_access(self):
        value, store, _, instance = service()
        expired = approval_request(
            value, decided_at=NOW - timedelta(hours=2),
            valid_until=NOW - timedelta(hours=1),
        )
        with self.assertRaises(CommunityResponseError) as caught:
            await instance.decide(
                expired, Principal(REVIEWER, frozenset({Role.REVIEWER})), now=NOW,
            )
        assert caught.exception.code == "APPROVAL_TIME_INVALID"
        assert store.saved is None


if __name__ == '__main__':
    unittest.main()
