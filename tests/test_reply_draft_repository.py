from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import unittest
from uuid import uuid4

from flowx_os.community.analysis import CommunityTheme, SafetyCategory, SafetySeverity
from flowx_os.community.comments import CommentState
from flowx_os.community.replies import ReplyDraftRequest, ReplyDraftService
from flowx_os.db.community_replies import ReplyDraftRepository


NOW = datetime(2026, 11, 23, 17, 30, tzinfo=timezone.utc)


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


def request(*, risky=False):
    version = uuid4()
    category = "PROMPT_INJECTION" if risky else "NO_DETECTED_SIGNAL"
    severity = "MEDIUM" if risky else "NONE"
    rules = "safety.prompt_injection" if risky else ""
    review = "true" if risky else "false"
    classification = hashlib.sha256("|".join((
        str(version), "b" * 64, "QUESTION", "theme.question",
        category, severity, rules, review,
    )).encode()).hexdigest()
    return ReplyDraftRequest(
        uuid4(), "owner-1", uuid4(), uuid4(), version, classification, NOW,
    )


def target_row(value, *, risky=False):
    return (
        value.owner_user_id, value.publication_id, value.analysis_request_id,
        "a" * 64, value.comment_version_id, "comment_1", "b" * 64, "ACTIVE",
        "QUESTION", "theme.question",
        "PROMPT_INJECTION" if risky else "NO_DETECTED_SIGNAL",
        "MEDIUM" if risky else "NONE",
        ["safety.prompt_injection"] if risky else [], risky,
        value.classification_fingerprint,
    )


def record_row(record):
    return (
        record.request_id, record.owner_user_id, record.publication_id,
        record.analysis_request_id, record.comment_version_id,
        record.request_fingerprint, record.target_fingerprint,
        record.analysis_report_fingerprint, record.classification_fingerprint,
        record.policy_version, record.disposition.value,
        record.escalation_priority.value, list(record.escalation_reasons),
        record.draft_text, record.human_approval_required,
        record.outbound_action_authorized, record.created_at,
        record.record_fingerprint,
    )


class ReplyDraftRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_target_is_owner_exact_classification_and_latest_report_scoped(self):
        value = request()
        connection = Connection([target_row(value)])
        target = await ReplyDraftRepository(Pool(connection)).load_target(value)
        self.assertEqual(target.comment_version_id, value.comment_version_id)
        query, params = connection.calls[0]
        self.assertIn("community_comments_current", query)
        self.assertIn("NOT EXISTS", query)
        self.assertEqual(params, (
            value.analysis_request_id, value.publication_id,
            value.comment_version_id, value.owner_user_id,
            value.classification_fingerprint,
        ))

    async def test_persist_locks_publication_rechecks_target_and_inserts(self):
        value = request()
        row = target_row(value)
        target = ReplyDraftRepository._target(row)
        record = ReplyDraftService._build(request=value, target=target)
        connection = Connection([None, (value.publication_id,), row, record_row(record)])
        stored = await ReplyDraftRepository(Pool(connection)).persist(value, target, record)
        self.assertEqual(stored, record)
        sql = "\n".join(query for query, _ in connection.calls)
        self.assertIn("FOR UPDATE OF p", sql)
        self.assertIn("FOR SHARE OF r, c, v", sql)
        self.assertIn("INSERT INTO community_reply_draft_records", sql)

    async def test_get_existing_is_owner_scoped_and_hydrates_escalation(self):
        value = request(risky=True)
        target = ReplyDraftRepository._target(target_row(value, risky=True))
        record = ReplyDraftService._build(request=value, target=target)
        connection = Connection([record_row(record)])
        stored = await ReplyDraftRepository(Pool(connection)).get_existing(value)
        self.assertEqual(stored, record)
        self.assertEqual(connection.calls[0][1], (value.request_id, value.owner_user_id))


if __name__ == "__main__": unittest.main()
