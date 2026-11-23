import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flowx_os.publishing.reconciliation import PublicationPlatform
from flowx_os.publishing.scheduling import (
    PublicationApprovalDecision,
    PublicationApprovalRecord,
    PublicationApprovalRequest,
    PublicationDeliveryState,
    PublicationSchedulePolicy,
    PublicationScheduleRecord,
    PublicationScheduleRequest,
    PublicationSchedulingError,
    PublicationSchedulingService,
    resolve_local_schedule,
)


NOW = datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc)


def approval_request(*, valid_until=None, decision=PublicationApprovalDecision.APPROVE):
    return PublicationApprovalRequest(
        request_id=uuid4(), approval_id=uuid4(), publication_id=uuid4(),
        owner_user_id="owner-1", approver_user_id="owner-1", decision=decision,
        valid_until=valid_until or NOW + timedelta(days=2),
        reason="Reviewed final export and destination",
    )


def schedule_request(approval=None, *, local=None, timezone_name="Asia/Kolkata", fold=None):
    approval = approval or approval_request()
    return PublicationScheduleRequest(
        request_id=uuid4(), schedule_id=uuid4(),
        publication_id=approval.publication_id, approval_id=approval.approval_id,
        owner_user_id=approval.owner_user_id,
        local_scheduled_at=local or datetime(2026, 11, 24, 12, 30),
        timezone_name=timezone_name, fold=fold,
    )


def approval_record(request):
    return PublicationApprovalRecord(
        approval_id=request.approval_id, request_id=request.request_id,
        publication_id=request.publication_id, owner_user_id=request.owner_user_id,
        decision=request.decision, valid_until=request.valid_until,
        reason=request.reason, platform=PublicationPlatform.YOUTUBE,
        content_id=uuid4(), channel_id=uuid4(), asset_id=uuid4(), artifact_version=4,
        publication_state_version=0, destination_fingerprint="a" * 64,
        created_at=NOW,
    )


def schedule_record(request):
    return PublicationScheduleRecord(
        schedule_id=request.schedule_id, request_id=request.request_id,
        publication_id=request.publication_id, approval_id=request.approval_id,
        owner_user_id=request.owner_user_id, platform=PublicationPlatform.YOUTUBE,
        channel_id=uuid4(), content_id=uuid4(), asset_id=uuid4(), artifact_version=4,
        local_scheduled_at=request.local_scheduled_at,
        timezone_name=request.timezone_name, fold=request.fold,
        utc_offset_minutes=request.utc_offset_minutes,
        scheduled_at_utc=request.scheduled_at_utc,
        state=PublicationDeliveryState.SCHEDULED, outbox_job_id=uuid4(), created_at=NOW,
    )


class FakeStore:
    def __init__(self, *, existing_approval=None, existing_schedule=None):
        self.calls = []
        self.existing_approval = existing_approval
        self.existing_schedule = existing_schedule

    async def get_approval(self, request):
        self.calls.append(("get_approval", request))
        return self.existing_approval

    async def record_approval(self, request):
        self.calls.append(("approve", request))
        return approval_record(request)

    async def get_schedule(self, request):
        self.calls.append(("get_schedule", request))
        return self.existing_schedule

    async def schedule(self, request, *, now, policy):
        self.calls.append(("schedule", request, now, policy))
        return schedule_record(request)


class PublicationSchedulingTests(unittest.IsolatedAsyncioTestCase):
    def test_india_local_time_converts_once_to_utc(self):
        request = schedule_request()
        self.assertEqual(request.scheduled_at_utc, datetime(2026, 11, 24, 7, 0, tzinfo=timezone.utc))
        self.assertEqual(request.utc_offset_minutes, 330)
        start, end = request.day_bounds_utc
        self.assertEqual(start, datetime(2026, 11, 23, 18, 30, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 11, 24, 18, 30, tzinfo=timezone.utc))

    def test_utc_brand_timezone_is_supported(self):
        utc_value, offset = resolve_local_schedule(
            datetime(2026, 11, 24, 7, 0), "UTC", None,
        )
        self.assertEqual(utc_value, datetime(2026, 11, 24, 7, 0, tzinfo=timezone.utc))
        self.assertEqual(offset, 0)

    def test_dst_gap_and_implicit_fold_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            resolve_local_schedule(
                datetime(2026, 3, 8, 2, 30), "America/New_York", None,
            )
        with self.assertRaisesRegex(ValueError, "explicit fold"):
            resolve_local_schedule(
                datetime(2026, 11, 1, 1, 30), "America/New_York", None,
            )
        first, first_offset = resolve_local_schedule(
            datetime(2026, 11, 1, 1, 30), "America/New_York", 0,
        )
        second, second_offset = resolve_local_schedule(
            datetime(2026, 11, 1, 1, 30), "America/New_York", 1,
        )
        self.assertNotEqual(first, second)
        self.assertEqual((first_offset, second_offset), (-240, -300))

    def test_local_day_bounds_accept_midnight_dst_gap(self):
        request = schedule_request(
            local=datetime(2026, 4, 24, 12, 0), timezone_name="Africa/Cairo",
        )
        start, end = request.day_bounds_utc
        self.assertEqual(start, datetime(2026, 4, 23, 22, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 4, 24, 21, 0, tzinfo=timezone.utc))

    async def test_approval_is_explicit_owner_action_and_must_be_unexpired(self):
        with self.assertRaises(ValueError):
            PublicationApprovalRequest(
                request_id=uuid4(), approval_id=uuid4(), publication_id=uuid4(),
                owner_user_id="owner-1", approver_user_id="other-user",
                decision=PublicationApprovalDecision.APPROVE,
                valid_until=NOW + timedelta(hours=1), reason="Reviewed",
            )
        service = PublicationSchedulingService(store=FakeStore(), now=lambda: NOW)
        with self.assertRaises(PublicationSchedulingError) as caught:
            await service.approve(approval_request(valid_until=NOW))
        self.assertEqual(caught.exception.code, "APPROVAL_EXPIRED")

    async def test_approval_can_be_recorded_while_auto_schedule_is_disabled(self):
        store = FakeStore()
        request = approval_request()
        result = await PublicationSchedulingService(
            store=store, now=lambda: NOW,
        ).approve(request)
        self.assertEqual(result.approval_id, request.approval_id)
        self.assertEqual([call[0] for call in store.calls], ["get_approval", "approve"])

    async def test_scheduling_is_disabled_by_default(self):
        store = FakeStore()
        with self.assertRaises(PublicationSchedulingError) as caught:
            await PublicationSchedulingService(
                store=store, now=lambda: NOW,
            ).schedule(schedule_request())
        self.assertEqual(caught.exception.code, "SCHEDULING_DISABLED")
        self.assertEqual([call[0] for call in store.calls], ["get_schedule"])

    async def test_schedule_enforces_lead_and_horizon_before_storage(self):
        policy = PublicationSchedulePolicy(enabled=True)
        store = FakeStore()
        service = PublicationSchedulingService(store=store, policy=policy, now=lambda: NOW)
        local_now = datetime(2026, 11, 23, 11, 30)
        for local, code in (
            (local_now + timedelta(seconds=299), "SCHEDULE_TOO_SOON"),
            (datetime(2027, 3, 1, 12, 0), "SCHEDULE_TOO_DISTANT"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(PublicationSchedulingError) as caught:
                    await service.schedule(schedule_request(local=local))
                self.assertEqual(caught.exception.code, code)
        self.assertEqual([call[0] for call in store.calls], ["get_schedule", "get_schedule"])

    async def test_enabled_schedule_passes_utc_and_bounded_policy_to_store(self):
        store = FakeStore()
        request = schedule_request()
        policy = PublicationSchedulePolicy(
            enabled=True, maximum_per_local_day=2, minimum_gap_seconds=7200,
        )
        result = await PublicationSchedulingService(
            store=store, policy=policy, now=lambda: NOW,
        ).schedule(request)
        self.assertEqual(result.scheduled_at_utc, request.scheduled_at_utc)
        self.assertEqual(store.calls[1][0], "schedule")
        self.assertEqual(store.calls[1][2], NOW)
        self.assertIs(store.calls[1][3], policy)

    async def test_exact_replays_survive_expiry_lead_time_and_disablement(self):
        approval = approval_request(valid_until=NOW + timedelta(minutes=1))
        stored_approval = approval_record(approval)
        approval_store = FakeStore(existing_approval=stored_approval)
        replayed_approval = await PublicationSchedulingService(
            store=approval_store, now=lambda: NOW + timedelta(days=2),
        ).approve(approval)
        self.assertIs(replayed_approval, stored_approval)

        request = schedule_request(approval)
        stored_schedule = schedule_record(request)
        schedule_store = FakeStore(existing_schedule=stored_schedule)
        replayed_schedule = await PublicationSchedulingService(
            store=schedule_store, now=lambda: NOW + timedelta(days=30),
        ).schedule(request)
        self.assertIs(replayed_schedule, stored_schedule)
        self.assertEqual([call[0] for call in schedule_store.calls], ["get_schedule"])


if __name__ == "__main__":
    unittest.main()
