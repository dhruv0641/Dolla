# TASK-069: Draft replies and escalation

- **Parent epic:** EPIC-14 — Community Management
- **Assigned agent:** Community Workflow Engineer
- **Priority:** P2
- **Dependencies:** TASK-068
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub issue:** [#216](https://github.com/dhruv0641/Dolla/issues/216)
- **Branch:** `feature/TASK-069-draft-replies-escalation`
- **Pull request:** [#217](https://github.com/dhruv0641/Dolla/pull/217), merged to `develop` as `2ddb6c21800d95868b3a5e2313906432e1cb5d11`
- **Related source documents:** ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want draft replies and escalation, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver draft replies and escalation as an independently verifiable capability within community management.

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

## Implementation Evidence
- `ReplyDraftService` emits fixed, non-personalized `community-reply-v1` templates only for clean, current TASK-068 evidence. It never interpolates untrusted comment text and every draft requires later human approval.
- Any safety signal or review flag produces an escalation with no draft; critical signals are urgent. Deleted content cannot be drafted.
- Migration 0030 binds owner, publication, latest analysis, current immutable comment version and classification; it independently recomputes deterministic decisions and fingerprints, stores `outbound_action_authorized=false`, and prevents updates/deletes.
- `FLOWX_COMMUNITY_REPLY_DRAFTING_ENABLED` defaults to `false`; no model/provider, reply-posting, moderation, account, publishing, spend or Flow method exists.
- Focused comment/analysis/reply/config/migration verification passes 89 tests and the single final full suite passes 688 tests. All 31 migrations and 342 statements parse, including nine statements in migration 0030; compileall, project validation and diff hygiene pass. Independent Caveman review accepted exact functional head `75206c1e542c39fa6d6993a9977749358d2e9ee5` with no remaining P0-P2 findings.
- Docker Engine and `psql` are unavailable, so live PostgreSQL trigger/locking/concurrency behavior and operator escalation quality remain unverified.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
