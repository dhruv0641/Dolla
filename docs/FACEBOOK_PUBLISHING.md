# Facebook Page Reels publishing boundary

TASK-059 implements a disabled-by-default, transport-injected boundary for the
official Facebook Page Reels API. It does not implement Facebook Login, resolve
Page access tokens, connect a Page, call Meta, or publish content by itself.

## Verified official contract

The implementation was checked against Meta's current documentation on
2026-11-22:

- [Reels Publishing API](https://developers.facebook.com/documentation/video-api/guides/reels-publishing)
- [Page Video Reels reference](https://developers.facebook.com/docs/graph-api/reference/page/video_reels/)
- [Video reference and status](https://developers.facebook.com/docs/graph-api/reference/video/)
- [Page Post reference](https://developers.facebook.com/docs/graph-api/reference/pagepost)

The injected transport must use a Page access token for the exact configured
Page. Authorization evidence must include the `CREATE_CONTENT` Page task and
`pages_show_list`, `pages_read_engagement`, and `pages_manage_posts` permissions.
The official workflow initializes `/{page_id}/video_reels`, uploads through the
returned `rupload.facebook.com` session, and finishes the same Page Reel with
`video_state=PUBLISHED`. Page publishing is public. The API currently limits
API-published Reels to 30 posts per Page in a moving 24-hour period; scheduling
and policy-level rate accounting belong to TASK-061.

Transport adapters normalize Meta phase values to `completed`, `error`,
`not_started`, or `in_progress`, and retain the separate publishing
`publish_status` value. They must not weaken an unrecognized value to a
successful state. A Reel is locally `PUBLISHED` only after the exact video is
`ready`, reports completed upload, processing and publishing phases, has
`publish_status=published`, and a separately retrieved
Page Reel/Post proof binds the expected Page, video, post and Facebook permalink.

## Local safety contract

`FLOWX_FACEBOOK_PUBLISHING_ENABLED` defaults to `false`. Enabling it only permits
an injected transport to be used; it does not authorize OAuth, account changes,
uploads, paid operations, or public publication.

Every claim binds:

- owner, brand, content, Page channel, approved asset and render version;
- the `FACEBOOK_REELS_V1` MP4 export, managed URI, SHA-256 and exact byte size;
- immutable Page ID, opaque credential reference and destination fingerprint;
- title, description, public state and AI-generation disclosure;
- the exact human approval decision.

Raw tokens and the remote upload URL are never persisted. The transport must
store the upload URL in an approved secret store and return only a
`secretref://...` upload-session reference.

## Mutation and recovery phases

Remote mutations are separately fenced:

1. `START_RESERVED` protects upload-session initialization.
2. `UPLOAD_RESERVED` protects binary transfer.
3. `PUBLISH_RESERVED` protects publish finalization.

Only the transaction that acquires the relevant phase may perform that remote
mutation. A lost response remains in its reserved phase and is never retried
blindly. An operator must bind independently confirmed evidence with
`recover_session`, `recover_upload`, or `recover_publish`, or terminally cancel
the unknown outcome with a safe reason. Every network path rechecks the current
owner-scoped Page ID, credential reference, enabled flag, permission status and
fresh provider authorization immediately before mutation.

Status polling is bounded by a persisted verification counter. Failed, expired
or upload-failed video evidence becomes terminal. A publish acknowledgment is
not publication proof. Final proof is immutable and contains no credentials.

## Verification limits

Unit and repository-boundary tests use fake transports and fake database
connections. Migration SQL is parsed as PostgreSQL and enforces immutable
claims, phase transitions, remote identities and final proof. Live PostgreSQL,
Facebook Login, Page eligibility, Graph/rupload HTTP behavior, resumability,
copyright checks, API rate limits and public visibility remain unverified.
