import unittest
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from flowx_os.flow_mcp import (
    FlowJobResumeService, FlowJobSubmissionService, FlowOperation,
    JobSubmissionClaim, JobSubmissionRequest, PersistedJobResumeContext, SpendAuthorization,
)
from flowx_os.flow_mcp.capabilities import _issue_flow_account_authorization
from flowx_os.domain.scene_jobs import SceneAttemptLimitExceeded

from flowx_os.flow_mcp import (
    FlowJobState,
    generation_fingerprint,
    observe_in_flight_job,
    observe_resume_result,
)


class FlowJobObservationTests(unittest.TestCase):
    def test_fingerprint_is_stable_and_changes_with_request(self):
        values = dict(account_ref="acct-primary", scene_id="scene-1", attempt_index=1,
                      model="veo", prompt="A scene", settings={"ratio": "9:16", "duration": 8})
        first = generation_fingerprint(**values)
        self.assertEqual(first, generation_fingerprint(**values))
        self.assertEqual(len(first), 64)
        self.assertNotEqual(first, generation_fingerprint(**{**values, "attempt_index": 2}))

    def test_fingerprint_rejects_unstable_settings(self):
        with self.assertRaises(ValueError):
            generation_fingerprint(account_ref="a", scene_id="s", attempt_index=1,
                                   model="m", prompt="p", settings={"invalid": object()})

    def test_in_flight_requires_exactly_one_matching_known_job(self):
        payload = {"jobs_in_flight": [{"job_id": "job-1", "phase": "sent"}]}
        self.assertEqual(observe_in_flight_job(payload, expected_job_id="job-1").state, FlowJobState.RUNNING)
        self.assertEqual(observe_in_flight_job(payload, expected_job_id="job-2").state, FlowJobState.UNKNOWN)
        duplicate = {"jobs_in_flight": payload["jobs_in_flight"] * 2}
        self.assertEqual(observe_in_flight_job(duplicate, expected_job_id="job-1").state, FlowJobState.UNKNOWN)

    def test_absent_or_unrecognized_status_does_not_imply_success(self):
        self.assertEqual(observe_in_flight_job({}, expected_job_id="job-1").state, FlowJobState.UNKNOWN)
        self.assertEqual(observe_resume_result({"job_id": "job-1", "status": "mystery"},
                                               expected_job_id="job-1").state, FlowJobState.UNKNOWN)
        self.assertEqual(observe_resume_result({"job_id": "job-other", "status": "completed",
                                                "output_path": "x"}, expected_job_id="job-1").state,
                         FlowJobState.UNKNOWN)

    def test_terminal_success_requires_matching_job_and_output(self):
        result = observe_resume_result({"job_id": "job-1", "status": "completed", "output_path": "clip.mp4"},
                                       expected_job_id="job-1")
        self.assertEqual(result.state, FlowJobState.SUCCEEDED)
        self.assertEqual(result.output_path, "clip.mp4")
        files_result = observe_resume_result({"job_id": "job-1", "status": "completed",
                                              "files": ["clip.mp4"]}, expected_job_id="job-1")
        self.assertEqual(files_result.state, FlowJobState.SUCCEEDED)
        self.assertEqual(files_result.output_path, "clip.mp4")
        self.assertEqual(observe_resume_result({"job_id": "job-1", "status": "completed"},
                                               expected_job_id="job-1").state, FlowJobState.UNKNOWN)


class FakeAdapter:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def invoke(self, operation, arguments, *, account, spend=None):
        self.calls.append((operation, dict(arguments), account, spend))
        return self.result


class FlowJobResumeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_uses_only_the_existing_job_and_safe_resume_flags(self):
        now = datetime(2026, 11, 19, tzinfo=timezone.utc)
        account = _issue_flow_account_authorization(
            "acct-primary", checked_at=now, valid_until=now + timedelta(minutes=5),
        )
        adapter = FakeAdapter({"job_id": "job-1", "status": "running"})
        local_job_id = uuid4()
        class Store:
            async def get_resume_context(self, *, job_id, account_ref, owner_user_id):
                self.scope = (account_ref, owner_user_id)
                self.requested_job = job_id
                return PersistedJobResumeContext(
                    "job-1", "https://labs.google/fx/tools/flow", "persisted original", "C:/flow-output",
                )
        store = Store()
        result = await FlowJobResumeService(
            adapter, store, account=account, owner_user_id="owner-1",
        ).poll(job_id=local_job_id)
        self.assertEqual(result.state, FlowJobState.RUNNING)
        operation, arguments, called_account, spend = adapter.calls[0]
        self.assertEqual(operation, FlowOperation.JOB_RESUME)
        self.assertEqual(arguments, {
            "job_id": "job-1", "resume": True, "auto_confirm": False,
            "project_url": "https://labs.google/fx/tools/flow", "prompt": "persisted original",
            "output_dir": "C:/flow-output",
        })
        self.assertIs(called_account, account)
        self.assertIsNone(spend)
        self.assertEqual(store.requested_job, local_job_id)
        self.assertEqual(store.scope, ("acct-primary", "owner-1"))

    async def test_missing_persisted_context_does_not_call_flow(self):
        account = _issue_flow_account_authorization(
            "acct-primary", checked_at=datetime(2026, 11, 19, tzinfo=timezone.utc),
            valid_until=datetime(2026, 11, 19, tzinfo=timezone.utc) + timedelta(minutes=5),
        )
        class Store:
            async def get_resume_context(self, *, job_id, account_ref, owner_user_id):
                return None
        adapter = FakeAdapter({})
        result = await FlowJobResumeService(
            adapter, Store(), account=account, owner_user_id="owner-1",
        ).poll(job_id=uuid4())
        self.assertEqual(result.state, FlowJobState.UNKNOWN)
        self.assertEqual(adapter.calls, [])


class FakeSubmissionStore:
    def __init__(self):
        self.claim = JobSubmissionClaim(uuid4(), "RESERVED", None, True)
        self.claims = []
        self.updates = []

    async def claim_or_get(self, **request):
        self.claims.append(request)
        return self.claim

    async def mark_submitted(self, **update):
        self.updates.append(("submitted", update))

    async def mark_remote_submission_unknown(self, **update):
        self.updates.append(("unknown", update))


class FakeSubmitAdapter:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def invoke(self, operation, arguments, *, account, spend=None):
        self.calls.append((operation, arguments, account, spend))
        return self.result


class FlowJobSubmissionServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.account = _issue_flow_account_authorization(
            "acct-primary", checked_at=datetime(2026, 11, 19, tzinfo=timezone.utc),
            valid_until=datetime(2026, 11, 19, tzinfo=timezone.utc) + timedelta(minutes=5),
        )
        self.request = JobSubmissionRequest(
            scene_id=uuid4(), request_id=uuid4(), owner_user_id="owner-1", attempt_index=1,
            model="veo-3.1-lite", prompt="A scene", duration_seconds=8, quoted_credits=2,
            arguments={"auto_confirm": True, "prompt": "A scene", "model": "veo-3.1-lite", "duration": 8,
                       "ratio": "9:16", "project_url": "https://labs.google/fx/tools/flow",
                       "output_dir": "C:/flow-output"},
            settings={"aspect_ratio": "9:16"},
        )
        self.spend = SpendAuthorization(
            "approval-1", "acct-primary", FlowOperation.VIDEO_GENERATE, 2,
        )

    async def test_submission_persists_claim_before_send_and_updates_external_id(self):
        store = FakeSubmissionStore()
        adapter = FakeSubmitAdapter({"job_id": "remote-1"})
        claim = await FlowJobSubmissionService(adapter, store).submit(
            account=self.account, request=self.request, spend=self.spend,
        )
        self.assertEqual(claim.status, "SUBMITTED")
        self.assertEqual(len(store.claims), 1)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(store.updates[0][0], "submitted")
        self.assertEqual(store.updates[0][1]["external_job_id"], "remote-1")

    async def test_duplicate_claim_does_not_resubmit(self):
        store = FakeSubmissionStore()
        store.claim = JobSubmissionClaim(uuid4(), "REMOTE_SUBMISSION_UNKNOWN", None, False)
        adapter = FakeSubmitAdapter({"job_id": "must-not-be-used"})
        claim = await FlowJobSubmissionService(adapter, store).submit(
            account=self.account, request=self.request, spend=self.spend,
        )
        self.assertEqual(claim.status, "REMOTE_SUBMISSION_UNKNOWN")
        self.assertEqual(adapter.calls, [])

    async def test_ambiguous_submit_response_enters_unknown_without_retry(self):
        store = FakeSubmissionStore()
        adapter = FakeSubmitAdapter({"status": "sent"})
        claim = await FlowJobSubmissionService(adapter, store).submit(
            account=self.account, request=self.request, spend=self.spend,
        )
        self.assertEqual(claim.status, "REMOTE_SUBMISSION_UNKNOWN")
        self.assertEqual(store.updates[0][0], "unknown")

    async def test_submission_rejects_approval_below_reserved_quote_before_store_claim(self):
        store = FakeSubmissionStore()
        adapter = FakeSubmitAdapter({"job_id": "unused"})
        low_spend = SpendAuthorization(
            "approval-low", "acct-primary", FlowOperation.VIDEO_GENERATE, 1,
        )
        with self.assertRaises(ValueError):
            await FlowJobSubmissionService(adapter, store).submit(
                account=self.account, request=self.request, spend=low_spend,
            )
        self.assertEqual(store.claims, [])
        self.assertEqual(adapter.calls, [])

    async def test_submission_rejects_attempt_beyond_retry_policy_before_store_or_provider(self):
        store = FakeSubmissionStore()
        adapter = FakeSubmitAdapter({"job_id": "unused"})
        over_limit = replace(self.request, attempt_index=4)
        with self.assertRaises(SceneAttemptLimitExceeded):
            await FlowJobSubmissionService(adapter, store).submit(
                account=self.account, request=over_limit, spend=self.spend,
            )
        self.assertEqual(store.claims, [])
        self.assertEqual(adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
