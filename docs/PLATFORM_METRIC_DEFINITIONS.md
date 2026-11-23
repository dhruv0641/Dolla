# Platform metric definitions and collection boundary

TASK-062 introduces a versioned, platform-specific analytics contract. It does
not connect an account or perform a live provider read. Analytics collection is
disabled unless `FLOWX_PLATFORM_ANALYTICS_ENABLED=true` is supplied explicitly
and an authorized provider adapter is injected.

## Registry identity

- Checked-in registry: `config/platform_metrics.v1.json`
- Registry version: `platform-metrics-v1`
- Canonical SHA-256 fingerprint:
  `b994293e90e26358aa2ad15628be4a7b6fac7f53e035bf189b76c16452f6a7e5`
- Missing-value policy: `UNAVAILABLE`; absence is never converted to numeric zero.
- Comparability policy: every v1 metric is `platform_only=true`. Names such as
  view, play, reach, impression and engagement are not treated as equivalent
  across platforms.

The loader rejects unknown fields, duplicate IDs, duplicate raw names within a
platform, derived inputs from another platform, unsafe source hosts, control or
bidirectional text, unsupported units and definitions that omit the explicit
missing-value policy. Registry fingerprints are independent of entry order.

## YouTube definitions

| Metric ID | Provider field | Unit | Meaning |
|---|---|---|---|
| `youtube.views` | `views` | count | YouTube report view count; not another platform's view/play metric. |
| `youtube.engaged_views` | `engagedViews` | count | YouTube engaged-view definition. |
| `youtube.watch_time_minutes` | `estimatedMinutesWatched` | minutes | Estimated minutes watched. |
| `youtube.average_view_duration_seconds` | `averageViewDuration` | seconds | Average view duration. |
| `youtube.likes` | `likes` | count | Likes under the selected YouTube report scope. |
| `youtube.comments` | `comments` | count | Comments under the selected YouTube report scope. |
| `youtube.shares` | `shares` | count | Shares under the selected YouTube report scope. |
| `youtube.engagement_rate_by_views` | derived | ratio | Versioned sum of likes, comments and shares divided by `youtube.views`. |

## Instagram definitions

| Metric ID | Provider field | Unit | Meaning |
|---|---|---|---|
| `instagram.total_views` | `total_views_count` | count | Instagram media views across provider-defined surfaces and replays. |
| `instagram.likes` | `total_like_count` | count | Media likes. |
| `instagram.comments` | `total_comments_count` | count | Media comments. |
| `instagram.shares` | `shares_count` | count | Media shares when available. |
| `instagram.saves` | `saved_count` | count | Media saves when available. |
| `instagram.engagement_rate_by_views` | derived | ratio | Versioned sum of likes, comments, shares and saves divided by `instagram.total_views`. |

## Facebook Page Reel definitions

| Metric ID | Provider field | Unit | Meaning |
|---|---|---|---|
| `facebook.reel_initial_plays` | `blue_reels_play_count` | count | Reel plays excluding replays under this provider definition. |
| `facebook.reel_total_plays` | `fb_reels_total_plays` | count | Reel plays including replays under this provider definition. |
| `facebook.reel_unique_impressions` | `post_impressions_unique` | count | Estimated unique impressions/reach; not a view count. |
| `facebook.reel_average_watch_ms` | `post_video_avg_time_watched` | milliseconds | Average watched time in milliseconds. |
| `facebook.reel_watch_time_ms` | `post_video_view_time` | milliseconds | Aggregate watched time in milliseconds. |
| `facebook.reel_follows` | `post_video_followers` | count | Follows attributed to the Reel. |
| `facebook.reel_reactions` | `post_video_likes_by_reaction_type` | structured | Reaction counts remain separated by provider-defined reaction type. |
| `facebook.reel_social_actions` | `post_video_social_actions` | structured | Provider-defined comment/share components; not flattened into a scalar. |

Definitions are based on the official [YouTube Analytics metrics](https://developers.google.com/youtube/analytics/metrics),
[Instagram media reference](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/),
and [Facebook video insights reference](https://developers.facebook.com/docs/graph-api/reference/video/video_insights).
Provider permissions, API versions and field availability can change; a live
adapter must return `UNAVAILABLE` with a reason when a requested field is not
returned, denied, unsupported or provider-redacted.

## Collection and persistence rules

Only fixed publish-relative windows are accepted: `1H`, `24H`, `72H`, `7D`
and `28D`. The repository derives the start from the authoritative
`publication_jobs.published_at` value and derives the end from the named window;
callers cannot substitute arbitrary timestamps.

Before a provider read, the repository locks and verifies the exact owner,
published job, platform, enabled channel, valid permission state, credential
reference snapshot, destination, remote object, publication state version and
registry fingerprint. Provider output must repeat the exact request,
publication, platform, destination, remote object, source, window, registry and
requested metric IDs. Every requested raw metric must have either:

- `AVAILABLE` plus a bounded, unit-correct non-negative value; or
- `UNAVAILABLE`, a null value and one of the allowed reasons.

Missing, extra, stale, future, derived, cross-platform or incorrectly typed
provider values are rejected. Provider exceptions are converted to stable error
codes without exposing provider details.

Migration `0023_platform_metric_observations.sql` stores a reservation and an
immutable observation. Request IDs and fingerprints provide replay safety;
locked target rechecks prevent writing evidence after the publication identity
changes; database triggers reject forged identities, malformed missing-value
envelopes, invalid state transitions, updates and deletes. Credential references
are used only for the injected adapter call and are not stored in observation
records.

Fixed-window scheduling, deterministic request identities, unresolved replay
behavior and series states are documented in
[`WINDOWED_ANALYTICS_SNAPSHOTS.md`](WINDOWED_ANALYTICS_SNAPSHOTS.md).

## Current verification limits

The contracts, migration syntax, failure cases and repository behavior are
verified locally. No analytics OAuth connection, provider adapter, provider
request, production PostgreSQL migration or live metric comparison has been
performed. Consequently this capability is implemented but not live-integration
or production verified. TASK-063 owns scheduled window snapshots and downstream
missing-value reporting behavior.
