import hashlib
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flowx_os.publishing.reconciliation import (
    PlatformPublicationObservation,
    PlatformPublicationReconciler,
    PlatformReconciliationError,
    PlatformReconciliationPolicy,
    PlatformReconciliationRequest,
    PublicationPlatform,
    PublicationReconciliationRecord,
    PublicationReconciliationTarget,
    ReconciliationVerdict,
    RemotePublicationState,
)


def make_request():
    return PlatformReconciliationRequest(uuid4(), uuid4(), "owner-1")


def make_target(request, *, status="PUBLISHED", remote_id="video_1"):
    credentials = "secretref://os/youtube-owner-1"
    destination = "channel_1"
    return PublicationReconciliationTarget(
        publication_id=request.publication_id,
        owner_user_id=request.owner_user_id,
        platform=PublicationPlatform.YOUTUBE,
        local_status=status,
        publication_state_version=7,
        request_fingerprint="a" * 64,
        channel_id=uuid4(),
        destination_id=destination,
        credentials_ref=credentials,
        destination_fingerprint=hashlib.sha256(
            f"{destination}|{credentials}".encode()
        ).hexdigest(),
        remote_object_id=remote_id,
        remote_url=None if remote_id is None else f"https://www.youtube.com/watch?v={remote_id}",
    )


def make_observation(request, target, *, state=RemotePublicationState.PUBLISHED,
                     observed_at=None, remote_id=None, destination=None, platform=None,
                     publication_id=None, request_id=None, remote_url="default"):
    object_id = remote_id or target.remote_object_id or "video_1"
    if remote_url == "default":
        remote_url = (
            f"https://www.youtube.com/watch?v={object_id}"
            if state is RemotePublicationState.PUBLISHED else None
        )
    return PlatformPublicationObservation(
        request_id=request_id or request.request_id,
        publication_id=publication_id or request.publication_id,
        platform=platform or target.platform,
        destination_id=destination or target.destination_id,
        remote_object_id=object_id,
        state=state,
        observed_at=observed_at or datetime.now(timezone.utc),
        evidence_id="youtube:etag:abc123",
        remote_url=remote_url,
    )


def make_record(request, target, observation, verdict):
    return PublicationReconciliationRecord(
        request_id=request.request_id,
        publication_id=request.publication_id,
        platform=target.platform,
        local_status=target.local_status,
        remote_state=observation.state,
        verdict=verdict,
        requires_human_review=verdict is not ReconciliationVerdict.IN_SYNC,
        target_fingerprint=target.fingerprint,
        observation_fingerprint=observation.fingerprint,
        destination_id=target.destination_id,
        remote_object_id=observation.remote_object_id,
        remote_url=observation.remote_url,
        evidence_id=observation.evidence_id,
        observed_at=observation.observed_at,
        created_at=datetime.now(timezone.utc),
    )


class FakeStore:
    def __init__(self, target, *, existing=None):
        self.target = target
        self.existing = existing
        self.calls = []

    async def get_existing(self, request):
        self.calls.append("existing")
        return self.existing

    async def load_target(self, request):
        self.calls.append("target")
        return self.target

    async def record(self, *, request, target, observation, verdict):
        self.calls.append("record")
        return make_record(request, target, observation, verdict)


class FakeObserver:
    def __init__(self, observation=None, error=None):
        self.observation = observation
        self.error = error
        self.calls = []

    async def observe(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.observation


class PlatformPublicationReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_by_default_fails_before_remote_read(self):
        request = make_request()
        target = make_target(request)
        observer = FakeObserver(make_observation(request, target))
        reconciler = PlatformPublicationReconciler(
            store=FakeStore(target), observer=observer,
        )
        with self.assertRaisesRegex(PlatformReconciliationError, "disabled") as caught:
            await reconciler.reconcile(request)
        self.assertEqual(caught.exception.code, "CAPABILITY_DISABLED")
        self.assertEqual(observer.calls, [])

    async def test_exact_replay_returns_without_configuration_or_remote_read(self):
        request = make_request()
        target = make_target(request)
        observation = make_observation(request, target)
        existing = make_record(request, target, observation, ReconciliationVerdict.IN_SYNC)
        observer = FakeObserver(error=AssertionError("must not call provider"))
        result = await PlatformPublicationReconciler(
            store=FakeStore(target, existing=existing), observer=observer,
        ).reconcile(request)
        self.assertIs(result, existing)
        self.assertEqual(observer.calls, [])

    async def test_success_binds_exact_identity_and_records_read_only_verdict(self):
        request = make_request()
        target = make_target(request)
        observation = make_observation(request, target)
        store = FakeStore(target)
        observer = FakeObserver(observation)
        result = await PlatformPublicationReconciler(
            store=store, observer=observer,
            policy=PlatformReconciliationPolicy(enabled=True),
        ).reconcile(request)
        self.assertEqual(result.verdict, ReconciliationVerdict.IN_SYNC)
        self.assertFalse(result.requires_human_review)
        self.assertEqual(store.calls, ["existing", "target", "record"])
        call = observer.calls[0]
        self.assertEqual(call["remote_object_id"], target.remote_object_id)
        self.assertEqual(call["credentials_ref"], target.credentials_ref)

    async def test_missing_exact_remote_identity_fails_without_observation(self):
        request = make_request()
        target = make_target(request, status="DRAFT", remote_id=None)
        observer = FakeObserver()
        reconciler = PlatformPublicationReconciler(
            store=FakeStore(target), observer=observer,
            policy=PlatformReconciliationPolicy(enabled=True),
        )
        with self.assertRaises(PlatformReconciliationError) as caught:
            await reconciler.reconcile(request)
        self.assertEqual(caught.exception.code, "REMOTE_ID_UNAVAILABLE")
        self.assertEqual(observer.calls, [])

    async def test_provider_exception_is_sanitized(self):
        request = make_request()
        target = make_target(request)
        reconciler = PlatformPublicationReconciler(
            store=FakeStore(target), observer=FakeObserver(error=RuntimeError("token=secret")),
            policy=PlatformReconciliationPolicy(enabled=True),
        )
        with self.assertRaises(PlatformReconciliationError) as caught:
            await reconciler.reconcile(request)
        self.assertEqual(caught.exception.code, "OBSERVATION_UNAVAILABLE")
        self.assertNotIn("secret", str(caught.exception))

    async def test_stale_and_future_observations_fail_closed(self):
        request = make_request()
        target = make_target(request)
        for observed_at in (
            datetime.now(timezone.utc) - timedelta(seconds=301),
            datetime.now(timezone.utc) + timedelta(seconds=31),
        ):
            with self.subTest(observed_at=observed_at):
                observation = make_observation(request, target, observed_at=observed_at)
                reconciler = PlatformPublicationReconciler(
                    store=FakeStore(target), observer=FakeObserver(observation),
                    policy=PlatformReconciliationPolicy(enabled=True),
                )
                with self.assertRaises(PlatformReconciliationError) as caught:
                    await reconciler.reconcile(request)
                self.assertEqual(caught.exception.code, "OBSERVATION_STALE")

    async def test_every_echoed_identity_is_required(self):
        request = make_request()
        target = make_target(request)
        variants = (
            {"request_id": uuid4()},
            {"publication_id": uuid4()},
            {"platform": PublicationPlatform.FACEBOOK,
             "state": RemotePublicationState.PROCESSING, "remote_url": None},
            {"destination": "other_channel"},
            {"remote_id": "other_video"},
        )
        for changes in variants:
            with self.subTest(changes=changes):
                observation = make_observation(request, target, **changes)
                reconciler = PlatformPublicationReconciler(
                    store=FakeStore(target), observer=FakeObserver(observation),
                    policy=PlatformReconciliationPolicy(enabled=True),
                )
                with self.assertRaises(PlatformReconciliationError) as caught:
                    await reconciler.reconcile(request)
                self.assertEqual(caught.exception.code, "OBSERVATION_IDENTITY_MISMATCH")

    def test_state_classifier_covers_alignment_and_divergence(self):
        cases = {
            ("PUBLISHED", RemotePublicationState.PUBLISHED): ReconciliationVerdict.IN_SYNC,
            ("PUBLISHED", RemotePublicationState.PROCESSING): ReconciliationVerdict.LOCAL_AHEAD,
            ("PUBLISHED", RemotePublicationState.DELETED): ReconciliationVerdict.CONFLICT,
            ("CANCELLED", RemotePublicationState.ABSENT): ReconciliationVerdict.IN_SYNC,
            ("CANCELLED", RemotePublicationState.PUBLISHED): ReconciliationVerdict.CONFLICT,
            ("FAILED", RemotePublicationState.FAILED): ReconciliationVerdict.IN_SYNC,
            ("FAILED", RemotePublicationState.ABSENT): ReconciliationVerdict.CONFLICT,
            ("PROCESSING", RemotePublicationState.PUBLISHED): ReconciliationVerdict.REMOTE_AHEAD,
            ("PROCESSING", RemotePublicationState.PROCESSING): ReconciliationVerdict.IN_SYNC,
            ("UPLOAD_STARTED", RemotePublicationState.ABSENT): ReconciliationVerdict.LOCAL_AHEAD,
            ("DRAFT", RemotePublicationState.ABSENT): ReconciliationVerdict.IN_SYNC,
            ("VERIFY_PENDING", RemotePublicationState.RESTRICTED): ReconciliationVerdict.CONFLICT,
            ("VERIFY_PENDING", RemotePublicationState.UNKNOWN): ReconciliationVerdict.UNKNOWN,
        }
        for (local, remote), expected in cases.items():
            with self.subTest(local=local, remote=remote):
                self.assertEqual(
                    PlatformPublicationReconciler.classify(local, remote), expected,
                )

    def test_published_observation_requires_canonical_public_url(self):
        request = make_request()
        target = make_target(request)
        with self.assertRaises(ValueError):
            make_observation(request, target, remote_url=None)
        with self.assertRaises(ValueError):
            replace(make_observation(request, target), remote_url="https://evil.example/video")

    def test_record_review_flag_must_match_verdict(self):
        request = make_request()
        target = make_target(request)
        observation = make_observation(request, target)
        record = make_record(request, target, observation, ReconciliationVerdict.IN_SYNC)
        with self.assertRaises(ValueError):
            replace(record, requires_human_review=True)


if __name__ == "__main__":
    unittest.main()
