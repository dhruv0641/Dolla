# TASK-067: Authorized comment ingestion

- **Parent epic:** EPIC-14 — Community Management
- **Assigned agent:** Community Workflow Engineer
- **Priority:** P2
- **Dependencies:** TASK-011, TASK-057, TASK-060
- **Estimated complexity:** 4 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Issue:** [#210](https://github.com/dhruv0641/Dolla/issues/210)
- **Branch:** `feature/TASK-067-authorized-comment-ingestion`
- **Related source documents:** ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want authorized comment ingestion, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver authorized comment ingestion as an independently verifiable capability within community management.

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

- Added `flowx_os.community.comments` with a disabled-by-default official-provider protocol, exact request/sync/publication/platform/destination/remote-object/page/cursor echoes, bounded pagination, freshness checks, sanitized errors and no outbound authority.
- Added owner-scoped `CommentIngestionRepository` reservations and immutable migration `0028_authorized_comment_ingestion.sql`. Current channel permissions, exact publication snapshots and a fresh independently reconciled `IN_SYNC` published remote object are required before the provider boundary. Database triggers independently verify targets, batches, comment versions, edit/deletion ordering and complete each batch atomically at commit.
- Raw provider author IDs are converted to SHA-256 before persistence. Deleted versions retain neither author identifiers nor text. Comment content is explicitly untrusted; account connection, moderation, replies, publication, spend and Flow authority are absent.
- Added `FLOWX_COMMENT_INGESTION_ENABLED=false`, operator documentation, domain/repository/config/migration tests and related publication/reconciliation regressions.
- Initial independent review rejected commit `70346dc` because an older healthy reconciliation could hide a newer conflict, provider comment-read scopes were not revalidated immediately before network access, an unknown outcome could permanently lock a publication, exact overlapping versions were reinserted, and direct SQL did not match Python text/ID validation. The correction selects and proves the latest reconciliation overall, requires typed expiring platform-specific read scopes with two final network-ready checks, adds bounded leases/exact retries/audited abandonment, links exact overlap before insertion, and aligns database validation.
- Corrected-head review rejected commit `2b02050` because lease retries lacked a fencing generation and Python still accepted ASCII DEL while SQL rejected it. The next correction binds an immutable reservation request/sync/generation to the target and requires the current, unexpired generation in both network-ready checks, failure recording and final persistence; stale workers cannot call the provider through the service, expire a replacement lease or persist evidence. Python now rejects DEL with focused parity coverage.
- Verification after correction: 107 focused tests passed; 29 migrations containing 312 statements parsed, including 40 statements in migration 0028; compilation, diff hygiene and the 76-task project validator passed.
- Live PostgreSQL execution, provider adapters, OAuth/account access, provider reads, privacy/retention approval and end-to-end verification remain unverified. Docker is installed but its daemon is unavailable. No external or public action occurred.

Corrected-head independent review and the single final full suite are pending.
