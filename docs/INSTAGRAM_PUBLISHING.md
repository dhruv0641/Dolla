# Instagram Reels publishing boundary

TASK-058 provides a disabled-by-default application boundary for publishing an
exact human-approved `INSTAGRAM_REELS_V1` export to an authorized Instagram
professional account. It does not implement OAuth, resolve credentials, host
media, or call Meta by itself.

## Configuration and authorization

- `FLOWX_INSTAGRAM_PUBLISHING_ENABLED=false` is the safe default. Enabling the
  setting is necessary but not sufficient: the injected policy, current channel
  row, authorization evidence and exact approved artifact must also pass.
- Store only opaque references such as `FLOWX_META_CREDENTIALS_REF` and the
  per-request `media_source_ref`. Raw access tokens and public media URLs are not
  persisted in publication claims or logs.
- The implemented contract uses Instagram Login, `graph.instagram.com`, an
  Instagram User access token and both `instagram_business_basic` and
  `instagram_business_content_publish`. The authorization must identify the
  exact snapshotted professional account and be fresh at every network action.
- Real login, account connection, app review and permission grants require owner
  authorization and are outside this local verification.

## Official flow represented by the adapter

The current Meta documentation describes professional-account publishing as:

1. Create a `REELS` container with `POST /<IG_ID>/media`. Standard upload needs
   a publicly reachable media URL; Meta fetches the media asynchronously.
2. Query the exact container until `status_code=FINISHED`. Containers expire
   after 24 hours; `ERROR` and `EXPIRED` are terminal. The product bounds local
   reconciliation to five status observations per service policy; an operator
   must deliberately resume after that bound.
3. Publish the exact finished container with `POST /<IG_ID>/media_publish`.
4. Treat the returned media ID only as an identity, not final proof. Require the
   same container to report `PUBLISHED`, then read the media and verify the exact
   media ID, professional-account owner, `VIDEO` type and canonical Instagram
   Reel permalink before storing `PUBLISHED`.

Primary references:

- [Meta Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing)
- [IG User Media](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media)
- [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container)
- [IG Media](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/v21.0/)

The current local `INSTAGRAM_REELS_V1` export is MP4/H.264/AAC, 1080×1920 and
30 FPS. The repository additionally limits an accepted asset to 300 MB. This is
local contract evidence, not certification against every current Meta encoding
rule or account policy.

## Idempotency and unknown outcomes

Container creation and `media_publish` are two independent remote mutations.
Each has a transactionally persisted single-winner reservation before the
transport call:

- `CONTAINER_RESERVED` prevents a second container creation when the first
  response is lost.
- `PUBLISH_RESERVED` prevents a second publication when the publish response is
  lost.

An ambiguous reservation is never retried blindly. An operator must recover the
observed container/media ID or cancel the claim after confirming that no usable
remote object exists. Remote identities, destination snapshots, artifact proof,
request metadata and terminal evidence are immutable. Every network action
rechecks that the current enabled `INSTAGRAM` channel still matches the immutable
account and credential references.

## Explicit limitations

- No Meta app, OAuth grant, professional account, public media host, live
  container, publish request or public post was created during TASK-058.
- The transport is injected and fake-tested. Live HTTP semantics, app-review
  status, Page Publishing Authorization where applicable, quotas, rate limits,
  webhooks and production concurrency remain unverified.
- Publishing is a public external action. Keep the feature disabled until the
  owner authorizes the exact account, media source, deployment and action.
- Live PostgreSQL execution is not claimed; migration syntax and invariants are
  verified locally.
