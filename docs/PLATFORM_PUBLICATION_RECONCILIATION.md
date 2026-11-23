# Independent platform publication state

## Boundary

`PlatformPublicationReconciler` performs one read-only observation of the exact
remote object already bound to a YouTube, Instagram, or Facebook publication.
It does not call any publisher method, discover content by title, infer success
from a local status, create or repair a remote object, or update
`publication_jobs`. The default policy and
`FLOWX_PLATFORM_RECONCILIATION_ENABLED` are both disabled.

The injected `PlatformPublicationObserver` is the only provider-facing
interface. The repository first proves the requesting owner, supported
publication contract, enabled channel, valid permission state, unchanged
external destination and unchanged opaque credential reference. Only then does
the observer receive the opaque secret reference and exact platform,
destination, publication, request and remote-object identities. No observer is
wired into the default application configuration.

## Evidence and decisions

Provider output is untrusted until it echoes every requested identity and passes
the canonical-URL and freshness bounds. A provider exception is replaced by a
stable safe error; raw payloads, exceptions, access tokens and credential
references are never persisted in reconciliation history.

Each accepted read records a normalized remote state (`ABSENT`, `PROCESSING`,
`PUBLISHED`, `FAILED`, `DELETED`, `RESTRICTED`, or `UNKNOWN`) and one verdict:

- `IN_SYNC` is the only verdict that does not require human review.
- `REMOTE_AHEAD` means the exact remote object is published while the local
  workflow has not recorded publication.
- `LOCAL_AHEAD` means local state claims more progress than the independent
  remote observation proves.
- `CONFLICT` represents a definite incompatible terminal or visibility state.
- `UNKNOWN` preserves ambiguity; it never means absent, failed, or successful.

The classifier does not mutate local publication state. TASK-061 owns any
separately approved scheduling/duplicate-prevention transition policy.

## Persistence, races, and retries

Migration `0021_platform_publication_reconciliation.sql` gives every publication
a monotonic `publication_state_version`. After the remote read, persistence
locks the publication and repeats ownership, channel, destination, credential,
contract, local-state, remote-identity and version checks. A concurrent local
change therefore rejects the stale observation instead of attaching it to a
different state.

Reconciliation rows are immutable and cannot be deleted. `request_id` is
unique, and target/observation fingerprints bind an exact replay. A completed
request returns its stored result without another provider call; changed
evidence conflicts. Provider evidence is represented by a bounded opaque ID,
not a raw response. All divergence and unknown outcomes require human review.

## Verification limits

Unit tests use synthetic observers and database fakes. All migration files are
parsed as PostgreSQL, but migration execution, row-lock behavior, provider API
semantics, OAuth scopes, rate limits, deleted/private-object visibility and
eventual consistency have not been verified against live PostgreSQL or social
platforms. Enabling this read-only boundary requires separately authorized
accounts and a reviewed provider implementation. It does not authorize account
connection, upload, publication, deletion, scheduling, paid use or any public
action.
