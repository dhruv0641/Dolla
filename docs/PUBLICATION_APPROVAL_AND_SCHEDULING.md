# Publication approval, scheduling, and duplicate prevention

## Safety boundary

Publication scheduling is disabled by default. A deployment must explicitly set
`FLOWX_PUBLICATION_SCHEDULING_ENABLED=true` and construct
`PublicationSchedulePolicy(enabled=True)` before `PublicationSchedulingService`
accepts a schedule. This flag does not enable YouTube, Instagram, or Facebook
publishing; each publisher remains separately disabled and requires an
authorized provider implementation and account.

Approval is an explicit owner action. An approval snapshots the exact
publication request, content, platform, channel, export asset and artifact
version, publication state version, and destination fingerprint. Approvals are
immutable, expire at a bounded UTC instant, and cannot be reused after the
publication, destination, credentials, channel eligibility, or remote identity
changes. A rejection is retained as evidence and can never authorize a
schedule.

## Time and policy rules

The API accepts a timezone-naive civil time plus the brand's IANA timezone. It
converts that pair once to UTC and persists all of the following evidence:

- the original local value and timezone;
- an explicit `fold` for a repeated daylight-saving time;
- the resolved UTC offset and UTC delivery time;
- the UTC bounds of the corresponding local calendar day.

Nonexistent daylight-saving times fail closed. Repeated times require the
caller to choose fold 0 or 1. The default policy requires five minutes of lead
time, limits schedules to 90 days ahead and three deliveries per channel/local
day, and requires a four-hour channel gap. Local-day bounds use the first valid
civil instant when a timezone advances at midnight. All bounds are validated
in the domain service and again inside the locked database transaction. Exact
idempotent replays are loaded before moving clock/configuration gates, so a
lost response can recover the immutable approval or schedule after expiry,
lead time, or later disablement without creating new work.

## Atomic delivery reservation

Scheduling locks the publication and channel, revalidates current ownership,
contract, authorization snapshots, pristine remote state and approval, and
creates the due outbox job and immutable reservation in one transaction. The
reservation has unique request and publication identities. The database also
prevents the same content/platform/channel/artifact version from being reserved
twice.

Migration `0022_publication_approval_schedule_duplicate_prevention.sql` adds a
database trigger on the first provider-mutating transition for every supported
publisher. It requires an exact, due, unexpired approved reservation, unchanged
channel authorization, and no human-review reconciliation evidence. The same
transaction atomically changes `SCHEDULED` to `DISPATCH_RESERVED`; concurrent
workers therefore cannot both win the provider-call barrier. The repository
readiness checks repeat these conditions before provider authorization is
requested.

The outbox event is `publication.dispatch_due`.
`ScheduledPublicationDispatcher` is its executable consumer. It validates the
strict event envelope, reloads the exact due reservation under the current
outbox lease, selects only the matching platform executor, and acknowledges the
job only after that executor returns. A deployment must inject the reviewed
YouTube, Instagram, and Facebook executor adapters; none is silently configured
and a missing executor dead-letters safely. Existing publisher state machines
and the database transition trigger remain the idempotency fence across a crash
between a provider outcome and outbox acknowledgement. Unknown outcomes are
never retried blindly and require the platform recovery/reconciliation path.

Operators must not treat a scheduled reservation as a published post. A
cancelled reservation cannot be dispatched, restored, or deleted; a new
reviewed publication version and approval are required.

## Failure and recovery

- Reusing an idempotency key with different evidence is a conflict.
- Expired, rejected, stale, cross-owner, or mismatched approvals fail closed
  before initial dispatch. Once the atomic transition reaches
  `DISPATCH_RESERVED`, later expiry cannot block polling, verification, or
  recovery of that already-started exact operation.
- Daily-cap and minimum-gap violations fail before an outbox job is committed.
- A changed channel, credential reference, destination, publication state, or
  unresolved reconciliation prevents dispatch.
- The first mutation winner retains `DISPATCH_RESERVED`. If its provider result
  is ambiguous, the existing platform recovery and TASK-060 reconciliation
  paths apply; no automatic retry may create a second remote object.

## Verification limits

Unit and repository-boundary tests use database fakes, and all migrations are
parsed as PostgreSQL. Live PostgreSQL trigger ordering, transaction contention,
OAuth, concrete provider executor composition, provider scheduling behavior,
and public visibility are not verified. No account was connected and no upload,
publication, paid action, or public scheduling request was performed for this
task.
