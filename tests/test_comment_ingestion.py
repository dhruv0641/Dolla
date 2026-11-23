from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import unittest
from uuid import uuid4

from flowx_os.community.comments import (
    AuthorizedCommentIngestor,
    CommentIngestionBatch,
    CommentIngestionError,
    CommentIngestionPolicy,
    CommentIngestionRequest,
    CommentIngestionTarget,
    CommentReadAuthorization,
    CommentState,
    ProviderComment,
    ProviderCommentBatch,
    YOUTUBE_COMMENT_READ_SCOPE,
)
from flowx_os.publishing.reconciliation import PublicationPlatform


NOW = datetime.now(timezone.utc)


def make_authorization(target):
    return CommentReadAuthorization(
        platform=target.platform,
        destination_id=target.destination_id,
        granted_scopes=(YOUTUBE_COMMENT_READ_SCOPE,),
        checked_at=NOW,
        valid_until=NOW + timedelta(hours=1),
    )


def make_request(*, page_index=1):
    return CommentIngestionRequest(uuid4(), uuid4(), uuid4(), "owner-1", page_index)


def make_target(request, *, cursor=None, reconciled_at=NOW):
    credentials = "secretref://os/youtube-owner-1"
    destination = "channel_1"
    return CommentIngestionTarget(
        publication_id=request.publication_id,
        owner_user_id=request.owner_user_id,
        platform=PublicationPlatform.YOUTUBE,
        publication_state_version=3,
        publication_request_fingerprint="a" * 64,
        channel_id=uuid4(),
        destination_id=destination,
        credentials_ref=credentials,
        destination_fingerprint=hashlib.sha256(
            f"{destination}|{credentials}".encode()
        ).hexdigest(),
        remote_object_id="video_1",
        remote_url="https://www.youtube.com/watch?v=video_1",
        reconciliation_request_id=uuid4(),
        reconciliation_target_fingerprint="b" * 64,
        reconciliation_observation_fingerprint="c" * 64,
        reconciliation_observed_at=reconciled_at,
        page_index=request.page_index,
        cursor=cursor,
    )


def make_comment(*, remote_id="comment_1", state=CommentState.ACTIVE, updated_at=NOW):
    deleted = state is CommentState.DELETED
    return ProviderComment(
        remote_comment_id=remote_id,
        parent_remote_comment_id=None,
        author_external_id=None if deleted else "provider-author-1",
        text=None if deleted else "Useful feedback, treated as untrusted text.",
        state=state,
        published_at=updated_at - timedelta(minutes=2),
        provider_updated_at=updated_at,
    )


def make_provider_batch(request, target, **changes):
    authorization = make_authorization(target)
    values = {
        "request_id": request.request_id,
        "sync_id": request.sync_id,
        "publication_id": request.publication_id,
        "platform": target.platform,
        "destination_id": target.destination_id,
        "remote_object_id": target.remote_object_id,
        "page_index": request.page_index,
        "cursor_fingerprint": target.cursor_fingerprint,
        "comments": (make_comment(),),
        "has_more": False,
        "next_cursor": None,
        "observed_at": NOW,
        "evidence_id": "youtube:comments:etag-1",
        "authorization_fingerprint": authorization.fingerprint,
    }
    values.update(changes)
    return ProviderCommentBatch(**values)


def make_stored(request, target, provider_batch, authorization=None):
    authorization = authorization or make_authorization(target)
    return CommentIngestionBatch(
        request_id=request.request_id,
        sync_id=request.sync_id,
        publication_id=request.publication_id,
        platform=target.platform,
        destination_id=target.destination_id,
        remote_object_id=target.remote_object_id,
        page_index=request.page_index,
        target_fingerprint=target.fingerprint,
        batch_fingerprint=provider_batch.fingerprint,
        cursor_fingerprint=target.cursor_fingerprint,
        next_cursor_fingerprint=provider_batch.next_cursor_fingerprint,
        comment_count=len(provider_batch.comments),
        has_more=provider_batch.has_more,
        evidence_id=provider_batch.evidence_id,
        observed_at=provider_batch.observed_at,
        created_at=NOW,
        authorization_fingerprint=authorization.fingerprint,
        authorization_scopes=authorization.granted_scopes,
        authorization_checked_at=authorization.checked_at,
        authorization_valid_until=authorization.valid_until,
    )


class FakeStore:
    def __init__(self, target, *, existing=None, error=None, network_error_at=None):
        self.target = target
        self.existing = existing
        self.error = error
        self.calls = []
        self.maximum_pages = None
        self.maximum_reconciliation_age_seconds = None
        self.network_checks = []
        self.failures = []
        self.network_error_at = network_error_at

    async def get_existing(self, request):
        self.calls.append("existing")
        return self.existing

    async def reserve(
        self, request, *, maximum_pages, maximum_reconciliation_age_seconds,
        maximum_provider_attempts, reservation_lease_seconds,
    ):
        self.calls.append("reserve")
        self.maximum_pages = maximum_pages
        self.maximum_reconciliation_age_seconds = maximum_reconciliation_age_seconds
        if self.error:
            raise self.error
        return self.target

    async def assert_network_ready(self, target):
        self.network_checks.append(target)
        if self.network_error_at == len(self.network_checks):
            raise RuntimeError("authorization changed")

    async def record_failure(self, *, request, target, error_code):
        self.failures.append(error_code)

    async def record(self, *, request, target, batch, authorization):
        self.calls.append("record")
        return make_stored(request, target, batch, authorization)


class FakeProvider:
    def __init__(self, result=None, error=None, authorization=None, authorization_error=None):
        self.result = result
        self.error = error
        self.authorization = authorization
        self.authorization_error = authorization_error
        self.calls = []

    async def check_authorization(self, **kwargs):
        self.calls.append(("authorize", kwargs))
        if self.authorization_error:
            raise self.authorization_error
        return self.authorization or CommentReadAuthorization(
            platform=kwargs["platform"],
            destination_id=kwargs["destination_id"],
            granted_scopes=(YOUTUBE_COMMENT_READ_SCOPE,),
            checked_at=NOW,
            valid_until=NOW + timedelta(hours=1),
        )

    async def fetch_comments(self, **kwargs):
        self.calls.append(("fetch", kwargs))
        if self.error:
            raise self.error
        return self.result


class AuthorizedCommentIngestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_by_default_fails_before_reservation_or_provider_read(self):
        request = make_request()
        target = make_target(request)
        store = FakeStore(target)
        provider = FakeProvider(error=AssertionError("must not call provider"))
        with self.assertRaises(CommentIngestionError) as caught:
            await AuthorizedCommentIngestor(store=store, provider=provider).ingest(request)
        self.assertEqual(caught.exception.code, "CAPABILITY_DISABLED")
        self.assertEqual(store.calls, ["existing"])
        self.assertEqual(provider.calls, [])

    async def test_exact_replay_returns_before_configuration_or_provider_read(self):
        request = make_request()
        target = make_target(request)
        provider_batch = make_provider_batch(request, target)
        existing = make_stored(request, target, provider_batch)
        result = await AuthorizedCommentIngestor(
            store=FakeStore(target, existing=existing),
            provider=FakeProvider(error=AssertionError("must not call provider")),
        ).ingest(request)
        self.assertIs(result, existing)

    async def test_success_binds_exact_read_only_identity_and_bounded_page(self):
        request = make_request()
        target = make_target(request)
        provider_batch = make_provider_batch(request, target)
        store = FakeStore(target)
        provider = FakeProvider(provider_batch)
        result = await AuthorizedCommentIngestor(
            store=store,
            provider=provider,
            policy=CommentIngestionPolicy(enabled=True, page_size=25, maximum_pages_per_sync=9),
        ).ingest(request)
        self.assertEqual(result.batch_fingerprint, provider_batch.fingerprint)
        self.assertEqual(store.calls, ["existing", "reserve", "record"])
        self.assertEqual(store.maximum_pages, 9)
        self.assertEqual(store.maximum_reconciliation_age_seconds, 3_600)
        self.assertEqual([name for name, _ in provider.calls], ["authorize", "fetch"])
        self.assertEqual(len(store.network_checks), 2)
        call = provider.calls[1][1]
        self.assertEqual(call["credentials_ref"], target.credentials_ref)
        self.assertEqual(call["remote_object_id"], target.remote_object_id)
        self.assertEqual(call["cursor"], target.cursor)
        self.assertEqual(call["limit"], 25)
        self.assertFalse(hasattr(result, "reply"))

    async def test_stale_reconciliation_fails_before_provider_read(self):
        request = make_request()
        target = make_target(request, reconciled_at=NOW - timedelta(hours=2))
        provider = FakeProvider(error=AssertionError("must not call provider"))
        with self.assertRaises(CommentIngestionError) as caught:
            await AuthorizedCommentIngestor(
                store=FakeStore(target),
                provider=provider,
                policy=CommentIngestionPolicy(enabled=True),
            ).ingest(request)
        self.assertEqual(caught.exception.code, "AUTHORIZATION_STALE")
        self.assertEqual(provider.calls, [])

    async def test_provider_exception_is_sanitized(self):
        request = make_request()
        target = make_target(request)
        with self.assertRaises(CommentIngestionError) as caught:
            await AuthorizedCommentIngestor(
                store=FakeStore(target),
                provider=FakeProvider(error=RuntimeError("token=do-not-log")),
                policy=CommentIngestionPolicy(enabled=True),
            ).ingest(request)
        self.assertEqual(caught.exception.code, "PROVIDER_UNAVAILABLE")
        self.assertNotIn("do-not-log", str(caught.exception))

    async def test_comment_read_scope_and_final_network_recheck_are_required(self):
        request = make_request()
        target = make_target(request)
        invalid = CommentReadAuthorization(
            platform=target.platform,
            destination_id=target.destination_id,
            granted_scopes=("https://www.googleapis.com/auth/youtube.upload",),
            checked_at=NOW,
            valid_until=NOW + timedelta(hours=1),
        )
        store = FakeStore(target)
        provider = FakeProvider(
            make_provider_batch(request, target), authorization=invalid,
        )
        with self.assertRaises(CommentIngestionError) as caught:
            await AuthorizedCommentIngestor(
                store=store, provider=provider,
                policy=CommentIngestionPolicy(enabled=True),
            ).ingest(request)
        self.assertEqual(caught.exception.code, "AUTHORIZATION_INVALID")
        self.assertEqual([name for name, _ in provider.calls], ["authorize"])
        self.assertEqual(store.failures, ["AUTHORIZATION_INVALID"])

        store = FakeStore(target, network_error_at=2)
        provider = FakeProvider(make_provider_batch(request, target))
        with self.assertRaises(CommentIngestionError) as caught:
            await AuthorizedCommentIngestor(
                store=store, provider=provider,
                policy=CommentIngestionPolicy(enabled=True),
            ).ingest(request)
        self.assertEqual(caught.exception.code, "NETWORK_NOT_READY")
        self.assertEqual([name for name, _ in provider.calls], ["authorize"])
        self.assertEqual(store.failures, ["NETWORK_NOT_READY"])

    async def test_every_echoed_identity_and_cursor_are_required(self):
        request = make_request()
        target = make_target(request)
        variants = (
            {"request_id": uuid4()},
            {"sync_id": uuid4()},
            {"publication_id": uuid4()},
            {"platform": PublicationPlatform.FACEBOOK},
            {"destination_id": "other_channel"},
            {"remote_object_id": "other_video"},
            {"page_index": 2},
            {"cursor_fingerprint": "f" * 64},
        )
        for changes in variants:
            with self.subTest(changes=changes):
                provider_batch = make_provider_batch(request, target, **changes)
                with self.assertRaises(CommentIngestionError) as caught:
                    await AuthorizedCommentIngestor(
                        store=FakeStore(target),
                        provider=FakeProvider(provider_batch),
                        policy=CommentIngestionPolicy(enabled=True),
                    ).ingest(request)
                self.assertEqual(caught.exception.code, "BATCH_IDENTITY_MISMATCH")

    async def test_page_size_and_observation_window_fail_closed(self):
        request = make_request()
        target = make_target(request)
        too_many = tuple(make_comment(remote_id=f"comment_{index}") for index in range(2))
        cases = (
            (
                make_provider_batch(request, target, comments=too_many),
                CommentIngestionPolicy(enabled=True, page_size=1),
                "BATCH_LIMIT_EXCEEDED",
            ),
            (
                make_provider_batch(
                    request, target, observed_at=NOW - timedelta(minutes=6),
                    comments=(make_comment(updated_at=NOW - timedelta(minutes=6)),),
                ),
                CommentIngestionPolicy(enabled=True),
                "BATCH_STALE",
            ),
        )
        for provider_batch, policy, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(CommentIngestionError) as caught:
                    await AuthorizedCommentIngestor(
                        store=FakeStore(target),
                        provider=FakeProvider(provider_batch),
                        policy=policy,
                    ).ingest(request)
                self.assertEqual(caught.exception.code, code)

    def test_comment_versions_are_typed_minimized_and_immutable(self):
        active = make_comment()
        self.assertEqual(active.author_external_id_hash, hashlib.sha256(
            b"provider-author-1"
        ).hexdigest())
        self.assertNotIn("provider-author-1", active.fingerprint)
        deleted = make_comment(state=CommentState.DELETED)
        self.assertIsNone(deleted.text)
        self.assertIsNone(deleted.author_external_id_hash)
        with self.assertRaises(ValueError):
            replace(deleted, text="retained deleted content")
        with self.assertRaises(ValueError):
            replace(active, text="\x00provider instruction")

    def test_batch_rejects_duplicates_and_requires_cursor_state_consistency(self):
        request = make_request()
        target = make_target(request)
        comment = make_comment()
        with self.assertRaises(ValueError):
            make_provider_batch(request, target, comments=(comment, comment))
        with self.assertRaises(ValueError):
            make_provider_batch(request, target, has_more=True, next_cursor=None)
        continued = make_provider_batch(
            request, target, has_more=True, next_cursor="opaque-next-page",
        )
        self.assertNotEqual(
            continued.next_cursor_fingerprint,
            hashlib.sha256(b"").hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()

