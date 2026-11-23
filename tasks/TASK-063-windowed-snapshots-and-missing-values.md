# TASK-063: Windowed snapshots and missing values

- **Parent epic:** EPIC-13 — Analytics and Growth
- **Assigned agent:** Analytics Engineer
- **Priority:** P2
- **Dependencies:** TASK-062
- **Estimated complexity:** 4 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub issue:** [#198](https://github.com/dhruv0641/Dolla/issues/198)
- **Branch:** `feature/TASK-063-windowed-snapshots-missing-values`
- **Related source documents:** ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want windowed snapshots and missing values, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver windowed snapshots and missing values as an independently verifiable capability within analytics and growth.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] Capability is implemented behind documented interfaces and configuration.
- [x] Errors, state transitions and security boundaries are explicit and observable.
- [x] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.

## Implementation Evidence

- `WindowedSnapshotPlan` derives deterministic UUIDv5 requests for exactly `1H`,
  `24H`, `72H`, `7D` and `28D` from publication/owner/window/registry/raw metric
  identity. Derived or mixed-platform metric plans fail closed.
- `WindowedSnapshotCoordinator` refuses early windows and the repository repeats
  readiness against authoritative `published_at` before any durable reservation.
  Migration `0024` and a locked repository preflight enforce one canonical
  publication/window/registry/metric-set attempt across concurrent request IDs.
- A reserved but unrecorded attempt returns `REQUEST_OUTCOME_UNKNOWN` rather
  than repeating a provider read. Series views expose `REQUIRES_REVIEW` alongside
  `FUTURE`, `DUE`, `COMPLETE` and `PARTIAL`.
- Complete, partial and all-missing snapshots retain explicit availability,
  null values and bounded reasons; no missing value is converted to zero. Series
  assembly revalidates deterministic request, exact lineage, registry, window,
  timestamps and metric set.
- `docs/WINDOWED_ANALYTICS_SNAPSHOTS.md` records scheduling, state, retry,
  retention and live-integration boundaries. No provider adapter/read, OAuth,
  account connection or external operation was used.
- Focused verification: 91 analytics/configuration/migration/reconciliation
  tests pass. All 25 migrations/209 statements parse, compilation, diff hygiene
  and the 76-task project validator pass.
- Remaining gate: independent exact-head review, then the single final full
  suite and GitHub PR/CI. Live PostgreSQL index/concurrency and scheduler/provider
  behavior remain unverified.
