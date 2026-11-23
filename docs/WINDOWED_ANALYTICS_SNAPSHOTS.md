# Windowed analytics snapshots

TASK-063 schedules analytics evidence at five fixed offsets from the
authoritative publication time: `1H`, `24H`, `72H`, `7D` and `28D`. It does not
add a provider adapter or enable analytics collection.

## Schedule and request identity

`WindowedSnapshotPlan` accepts one owner, one published object and a sorted set
of raw metrics from one platform. For each fixed window it derives a UUIDv5
request identity from:

- contract version `flowx-windowed-snapshot-v1`;
- publication and owner identities;
- the named window;
- metric registry version and fingerprint; and
- the exact sorted raw metric IDs.

The same inputs always produce the same request. The plan exposes only windows
whose end is at or before a UTC scheduling clock. `WindowedSnapshotCoordinator`
refuses an early window before delegation. The collector then repeats readiness
against the repository's authoritative `publication_jobs.published_at` value
before it creates a durable reservation, so stale caller schedule data cannot
poison a future window.

Migration `0024_windowed_snapshot_identity.sql` adds a unique database identity
over publication, window, registry and requested metric set. Concurrent workers
therefore cannot create two canonical attempts for the same snapshot. If a
reservation exists without immutable recorded evidence, replay fails with
`REQUEST_OUTCOME_UNKNOWN`; it does not perform another provider read blindly.
The window can be surfaced as `REQUIRES_REVIEW` until an operator reconciles the
unresolved attempt.

## Series and missing values

`WindowedSnapshotSeries` verifies every stored record against the deterministic
request, owner, publication, platform/destination/remote-object lineage,
registry, window timestamps and requested metric set. It exposes exactly five
ordered window views:

| State | Meaning |
|---|---|
| `FUTURE` | The fixed window end has not arrived. |
| `DUE` | The window is complete but no stored evidence was supplied. |
| `COMPLETE` | Every requested metric is explicitly available. |
| `PARTIAL` | One or all requested metrics are explicitly unavailable. |
| `REQUIRES_REVIEW` | A durable unresolved attempt prevents blind replay. |

Partial and all-missing snapshots retain each null value and its enumerated
reason. They are never filled with zero. A real observed zero remains distinct:
it is `AVAILABLE` with numeric value `0`.

## Operational limits

- Analytics collection remains disabled by default through
  `FLOWX_PLATFORM_ANALYTICS_ENABLED=false`.
- A plan is limited to 100 unique raw metrics from one platform.
- Custom/ad hoc windows are not accepted by this scheduler.
- Provider failures and reserved outcomes remain explicit; there is no automatic
  quota-consuming retry.
- The series is an immutable evidence view, not a cross-platform equivalence or
  derived-metric calculator.
- Retention and archival policy remain governed by deployment policy; this task
  does not delete observation evidence.

Local tests cover exact boundaries, all five windows, deterministic IDs, early
refusal before reservation, concurrent/replay barriers, complete/partial/all-
missing views, unresolved outcomes and lineage conflicts. Production PostgreSQL
index behavior, a live scheduler, OAuth, provider availability/quota semantics
and real analytics responses remain unverified. No external read or account
action occurred during implementation.
