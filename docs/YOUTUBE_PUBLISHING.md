# Official YouTube publisher

TASK-057 adds a transport-injected boundary for the official YouTube Data API.
It is disabled by default and does not implement an OAuth consent flow, resolve
credentials, connect a channel, schedule a publication, or invoke Google by
itself. No live upload was performed while implementing this task.

## Safety and evidence boundary

- Set `FLOWX_YOUTUBE_PUBLISHING_ENABLED=true` only after an owner authorizes the
  deployment, and construct `YouTubePolicy(enabled=settings.youtube_publishing_enabled)`.
- Keep OAuth material outside PostgreSQL and application logs. Configuration and
  channel rows contain only `secretref://provider/path` references. A resumable
  session URI is also sensitive and the transport must persist it behind an
  opaque secret reference.
- Use the least-privilege `https://www.googleapis.com/auth/youtube.upload` scope.
  The injected transport must prove that the grant belongs to the exact enabled
  channel before upload starts.
- A claim requires `READY` content, an active `YOUTUBE_SHORTS_V1` export from the
  exact completed render version, and an immutable human `APPROVE` decision over
  that exact asset. The asset is copied to a bounded temporary snapshot only
  after its path, MP4 signature, size and SHA-256 digest are revalidated.
- Metadata always sends `notifySubscribers=false`. The default policy allows
  only `private`; `unlisted` or `public` requires an explicit policy change.
- The request fingerprint, immutable channel/credential destination fingerprint
  and unique request/approval-channel keys make claim creation idempotent. The
  current channel must still be enabled, `VALID` and equal to that snapshot
  before every network operation.
- A transactional `PUBLISH_REQUESTED` transition is the single-winner barrier
  before `videos.insert`; the adapter fingerprint is not assumed to be a remote
  YouTube idempotency key. A stored upload-session reference and committed byte
  count support resumable re-entry. Unknown initiation outcomes become
  `VERIFY_PENDING` and never start a replacement upload automatically. An
  authenticated operator may attach a recovered opaque session reference or
  cancel the unknown claim after investigation.
- A completed upload response is not publication proof. The job reaches
  `PUBLISHED` only after owner-authorized `videos.list` evidence matches the
  exact video ID and channel, reports `status.uploadStatus=processed`, reports
  `processingDetails.processingStatus=succeeded`, and matches the requested
  privacy. Failed, rejected, deleted or terminal processing states become
  `FAILED`; other states remain `PROCESSING`.

## Transport contract

Implement `YouTubeTransport` using the official API client or HTTPS endpoints.
It must validate every remote response before constructing the strict typed
models. It must classify timeouts and connection loss after a request is sent as
ambiguous `YouTubeError` failures. Never put bearer/refresh tokens, resumable
URLs, response bodies, or credential values into an exception message.

The official API contract used for this implementation:

- [`videos.insert`](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert)
  requires OAuth, accepts video media and returns a video resource.
- [Resumable uploads](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol)
  return a session URI, use `308 Resume Incomplete` and require resuming from the
  server-confirmed byte range rather than assuming an interrupted request failed.
- [`videos.list`](https://developers.google.com/youtube/data/reference/rest/v3/videos/list)
  exposes owner-only processing details needed for verification.
- [Video resource status](https://developers.google.com/youtube/data/reference/rest/v3/videos)
  defines upload, processing and privacy states.

## Verification scope

Fake transports exercise disabled behavior, scope/channel mismatch, immutable
snapshotting, resumable replay, ambiguous state, processing, terminal failure
and verified completion. Repository tests cover owner concealment, exact approval
and render binding, enabled-channel gates, idempotency and canonical remote
evidence. Migration 0018 adds matching direct-SQL constraints and immutable
terminal evidence. Live OAuth, quota behavior, actual resumable HTTP transfers,
PostgreSQL concurrency and public visibility remain unverified and must not be
claimed as production-ready.
