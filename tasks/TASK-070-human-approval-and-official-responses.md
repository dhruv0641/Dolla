# TASK-070: Human approval and official responses

- **Parent epic:** EPIC-14 — Community Management
- **Assigned agent:** Community Workflow Engineer
- **Priority:** P2
- **Dependencies:** TASK-069
- **Estimated complexity:** 12 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub issue:** [#219](https://github.com/dhruv0641/Dolla/issues/219)
- **Branch:** `feature/TASK-070-human-approval-official-responses`
- **Pull request:** [#220](https://github.com/dhruv0641/Dolla/pull/220) merged to `develop` as `1902302a0c911839456612446329189a02935edc`
- **Related source documents:** ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want human approval and official responses, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver human approval and official responses as an independently verifiable capability within community management.

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

- Added typed reviewer/admin approvals over one exact TASK-069 draft, including role, owner, immutable text/classification evidence, expiry and rejection handling. Safety escalations, deleted comments and non-draft records cannot be approved.
- Added a disabled-by-default transport protocol and response service for YouTube, Instagram and Facebook official interfaces. Fresh exact-destination scopes, a database-backed single-winner mutation reservation, fail-closed receipt validation, unknown-outcome recovery and independent official reads are mandatory.
- Added migration `0031_community_human_approval_official_responses.sql`. PostgreSQL independently rechecks current owner/publication/channel/comment/latest-analysis evidence before mutation, recomputes authorization/receipt/verification fingerprints, limits legal state transitions and protects immutable approval/terminal history.
- Added repository boundaries, configuration (`FLOWX_COMMUNITY_OFFICIAL_RESPONSES_ENABLED=false`), operator documentation and domain/repository/migration/config regressions.
- Independent review rejected the first checkpoint `ffb46d6` for a publication-lock snapshot race, authorization expiry between reservation and mutation, forgeable ordinary-runtime approval inserts and direct-SQL ambiguous response-ID injection. Corrections now lock publication in a separate statement before current-evidence reads, recheck and persist a second authorization with a 30-second validity floor, isolate approval writes behind a dedicated security-definer/no-login role, separate response runtime privileges, and require recovery evidence for identity injection.
- Corrected-head review then found that narrow capability roles could not take direct row locks and that recovery timestamps were caller-controlled. A fixed-search-path security-definer lock helper now preserves least privilege for both roles, response triggers run with audited definer privileges, recovery time must be after reservation and no later than database time, and final proof cannot predate recovery.
- Focused verification on 2026-11-24: 87 tests passed across TASK-067 through TASK-070 community boundaries, configuration and every migration parser check. The single final backend suite passed 712 tests. All 32 migrations/375 statements parsed; `compileall`, diff hygiene, the 76-task project validator, frontend type-check and production build passed.
- External limits: no concrete provider adapter, OAuth/account connection, credential resolution or response execution was configured or invoked. Live PostgreSQL triggers/concurrency and real provider authorization/revocation/recovery remain unverified, so production readiness is not claimed.
- Independent Technical Reviewer: accepted exact functional head `ab579b87cde10cb75e5393844906f5fbb4492be4` with no remaining P0-P2 findings after independently checking all corrected boundaries and passing 87 focused tests, all 32 migrations/375 statements, compilation, project validation and diff hygiene. The reviewer separately accepted exact test/documentation head `2951c77b43e2213faf5f944f79b28b4be1888624`, confirming the CI-native `unittest` conversion preserves all 16 original scenarios and assertions.
