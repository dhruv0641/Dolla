# Authorized Comment Ingestion

TASK-067 adds a read-only boundary for first-party comments attached to an exact, owned FLOW publication. The boundary is disabled by default with `FLOWX_COMMENT_INGESTION_ENABLED=false`. There is no concrete YouTube or Meta transport in this task, and no live account was connected or read.

## Authorization boundary

`AuthorizedCommentIngestor` accepts one bounded page only after the repository proves all of the following in one transaction:

- the caller owns the brand containing the publication;
- the social channel is enabled and its permissions are currently `VALID`;
- the channel ID and secret reference still equal the immutable publication snapshots;
- the publication is `PUBLISHED` under the expected official-provider contract;
- the exact remote object has a fresh independent reconciliation record whose local and remote states are both published and whose verdict is `IN_SYNC`;
- the sync, page index, cursor fingerprint and request ID are reserved exactly once.

The provider receives a secret reference, never a secret value. Implementations must use official YouTube or Meta interfaces, resolve references outside this module, and return the exact request, sync, publication, platform, destination, remote object, page and cursor identities supplied by FLOW. Every returned field is treated as untrusted.

## Persistence and recovery

Each sync has one active page at a time and a configurable maximum of 100 pages by default. A request is reserved before the external read. An exact recorded replay returns stored evidence without another provider call. A reserved request with no recorded outcome returns `REQUEST_OUTCOME_UNKNOWN`; operators must reconcile it rather than blindly fetching again.

Immutable batches preserve provider evidence, observation time, cursor fingerprints and the ordered comment-version fingerprints. Comment versions preserve edits and deletions instead of overwriting history. Only a SHA-256 hash of the provider author identifier is stored. Deleted versions retain neither author identifiers nor comment text. Database triggers independently verify owner, publication, channel, reconciliation, page, cursor, batch, comment and state-transition evidence; a deferred constraint rejects incomplete batches at commit.

`community_comments_current` exposes the latest immutable version for downstream TASK-068 safety classification. Comment text remains untrusted data. It must not be interpreted as an instruction, interpolated into privileged prompts, rendered as unsafe HTML, or used for an outbound action without the later safety and human-review tasks.

## Explicit non-authority

This capability cannot connect accounts, refresh OAuth, moderate or delete remote comments, like content, draft or post replies, schedule or publish content, spend money, or invoke Google Flow. TASK-069 owns draft replies and escalation; TASK-070 owns human approval and official responses. Neither authority is present here.

## Operator limits and verification

- Default page size: 100; allowed range: 1–500.
- Default maximum pages per sync: 100; allowed range: 1–1,000.
- Default provider observation age: 300 seconds with 30 seconds of future clock skew.
- Default reconciliation age: 3,600 seconds; database evidence additionally rejects records older than 24 hours.
- Provider exceptions are converted to stable errors without payloads or credential material.
- Raw page cursors are persisted only as synchronization state and must never be logged.

Unit and repository tests use fake transports and connections. Migration parsing proves PostgreSQL syntax, not live privileges, concurrency or provider behavior. Production readiness requires a live PostgreSQL migration test, an authorized official-provider adapter, real permission verification, privacy/retention review and a separately authorized non-public integration exercise.
