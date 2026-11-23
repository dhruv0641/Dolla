from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import unittest
from uuid import uuid4

from flowx_os.community.analysis import CommunityTheme, SafetyCategory, SafetySeverity
from flowx_os.community.comments import CommentState
from flowx_os.community.replies import (
    EscalationPriority,
    ReplyDisposition,
    ReplyDraftError,
    ReplyDraftPolicy,
    ReplyDraftRequest,
    ReplyDraftService,
    ReplyDraftTarget,
)


NOW = datetime(2026, 11, 23, 17, 0, tzinfo=timezone.utc)


def request(
    *, theme=CommunityTheme.QUESTION, theme_rule="theme.question",
    category=SafetyCategory.NO_DETECTED_SIGNAL, severity=SafetySeverity.NONE,
    rules=(), review=False,
):
    comment_version_id = uuid4()
    classification = hashlib.sha256("|".join((
        str(comment_version_id), "b" * 64, theme.value, theme_rule,
        category.value, severity.value, ",".join(rules), str(review).lower(),
    )).encode()).hexdigest()
    return ReplyDraftRequest(
        uuid4(), "owner-1", uuid4(), uuid4(), comment_version_id,
        classification, NOW,
    )


def target(value, **changes):
    values = dict(
        owner_user_id=value.owner_user_id, publication_id=value.publication_id,
        analysis_request_id=value.analysis_request_id,
        analysis_report_fingerprint="a" * 64,
        comment_version_id=value.comment_version_id,
        remote_comment_id="comment_1", comment_fingerprint="b" * 64,
        comment_state=CommentState.ACTIVE, theme=CommunityTheme.QUESTION,
        theme_rule_id="theme.question",
        safety_category=SafetyCategory.NO_DETECTED_SIGNAL,
        safety_severity=SafetySeverity.NONE, safety_rule_ids=(),
        requires_human_review=False,
        classification_fingerprint=value.classification_fingerprint,
    )
    values.update(changes)
    return ReplyDraftTarget(**values)


class FakeStore:
    def __init__(self, value, existing=None, persisted=None):
        self.value = value
        self.existing = existing
        self.persisted = persisted
        self.loads = 0

    async def get_existing(self, request):
        return self.existing

    async def load_target(self, request):
        self.loads += 1
        return self.value

    async def persist(self, request, target, record):
        return record if self.persisted is None else self.persisted


class ReplyDraftTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_policy_fails_before_evidence_access(self):
        value = request()
        store = FakeStore(target(value))
        with self.assertRaises(ReplyDraftError) as raised:
            await ReplyDraftService(store).draft(value, now=NOW)
        self.assertEqual(raised.exception.code, "DRAFTING_DISABLED")
        self.assertEqual(store.loads, 0)

    async def test_clean_comment_gets_inert_source_bound_human_review_draft(self):
        value = request()
        result = await ReplyDraftService(
            FakeStore(target(value)), ReplyDraftPolicy(enabled=True),
        ).draft(value, now=NOW)
        self.assertEqual(result.disposition, ReplyDisposition.DRAFT_REQUIRES_HUMAN_APPROVAL)
        self.assertEqual(result.escalation_priority, EscalationPriority.NONE)
        self.assertIn("team member", result.draft_text.lower())
        self.assertTrue(result.human_approval_required)
        self.assertFalse(result.outbound_action_authorized)
        self.assertEqual(result.created_at, value.requested_at)

    async def test_any_safety_signal_blocks_draft_and_escalates(self):
        value = request(
            category=SafetyCategory.PROMPT_INJECTION,
            severity=SafetySeverity.MEDIUM,
            rules=("safety.prompt_injection",), review=True,
        )
        risky = target(
            value, safety_category=SafetyCategory.PROMPT_INJECTION,
            safety_severity=SafetySeverity.MEDIUM,
            safety_rule_ids=("safety.prompt_injection",), requires_human_review=True,
        )
        result = await ReplyDraftService(
            FakeStore(risky), ReplyDraftPolicy(enabled=True),
        ).draft(value, now=NOW)
        self.assertEqual(result.disposition, ReplyDisposition.ESCALATED_NO_DRAFT)
        self.assertEqual(result.escalation_priority, EscalationPriority.HUMAN_REVIEW)
        self.assertIsNone(result.draft_text)
        self.assertIn("safety.prompt_injection", result.escalation_reasons)

    async def test_critical_signal_is_urgent_and_never_drafted(self):
        value = request(
            category=SafetyCategory.SELF_HARM,
            severity=SafetySeverity.CRITICAL,
            rules=("safety.self_harm",), review=True,
        )
        risky = target(
            value, safety_category=SafetyCategory.SELF_HARM,
            safety_severity=SafetySeverity.CRITICAL,
            safety_rule_ids=("safety.self_harm",), requires_human_review=True,
        )
        result = await ReplyDraftService(
            FakeStore(risky), ReplyDraftPolicy(enabled=True),
        ).draft(value, now=NOW)
        self.assertEqual(result.escalation_priority, EscalationPriority.URGENT)
        self.assertIsNone(result.draft_text)

    async def test_deleted_comment_has_no_draft(self):
        value = request(
            theme=CommunityTheme.CONTENT_UNAVAILABLE,
            theme_rule="theme.content_unavailable",
            category=SafetyCategory.CONTENT_UNAVAILABLE,
        )
        deleted = target(
            value, comment_state=CommentState.DELETED,
            theme=CommunityTheme.CONTENT_UNAVAILABLE,
            theme_rule_id="theme.content_unavailable",
            safety_category=SafetyCategory.CONTENT_UNAVAILABLE,
        )
        result = await ReplyDraftService(
            FakeStore(deleted), ReplyDraftPolicy(enabled=True),
        ).draft(value, now=NOW)
        self.assertEqual(result.disposition, ReplyDisposition.CONTENT_UNAVAILABLE_NO_DRAFT)
        self.assertIsNone(result.draft_text)

    async def test_identity_policy_time_and_store_results_fail_closed(self):
        value = request()
        wrong = target(value, owner_user_id="owner-2")
        with self.assertRaises(ReplyDraftError) as mismatch:
            await ReplyDraftService(
                FakeStore(wrong), ReplyDraftPolicy(enabled=True),
            ).draft(value, now=NOW)
        self.assertEqual(mismatch.exception.code, "EVIDENCE_IDENTITY_MISMATCH")

        with self.assertRaises(ReplyDraftError) as future:
            await ReplyDraftService(
                FakeStore(target(value)), ReplyDraftPolicy(enabled=True),
            ).draft(value, now=NOW - timedelta(seconds=1))
        self.assertEqual(future.exception.code, "REQUEST_FROM_FUTURE")

        unavailable = replace(value, policy_version="community-reply-v2")
        with self.assertRaises(ReplyDraftError) as version:
            await ReplyDraftService(
                FakeStore(target(unavailable)), ReplyDraftPolicy(enabled=True),
            ).draft(unavailable, now=NOW)
        self.assertEqual(version.exception.code, "POLICY_VERSION_UNAVAILABLE")

        with self.assertRaises(ReplyDraftError) as persisted:
            await ReplyDraftService(
                FakeStore(target(value), persisted=object()),
                ReplyDraftPolicy(enabled=True),
            ).draft(value, now=NOW)
        self.assertEqual(persisted.exception.code, "STORED_RECORD_IDENTITY_MISMATCH")

    async def test_exact_existing_record_revalidates_current_target(self):
        value = request()
        store = FakeStore(target(value))
        existing = await ReplyDraftService(
            store, ReplyDraftPolicy(enabled=True),
        ).draft(value, now=NOW)
        replay = FakeStore(target(value), existing=existing)
        result = await ReplyDraftService(
            replay, ReplyDraftPolicy(enabled=True),
        ).draft(value, now=NOW + timedelta(minutes=1))
        self.assertEqual(result, existing)
        self.assertEqual(replay.loads, 1)


if __name__ == "__main__":
    unittest.main()
