# TASK-058: Instagram Reels publisher and verification

- **Parent epic:** EPIC-12 — Social Publishing
- **Assigned agent:** Publishing Integration Engineer
- **Priority:** P2
- **Dependencies:** TASK-057
- **Estimated complexity:** 16 engineering hours (planning estimate)
- **Status:** IN_PROGRESS
- **Related source documents:** ARCHITECTURE
- **GitHub issue:** [#183](https://github.com/dhruv0641/Dolla/issues/183)
- **Branch:** `feature/TASK-058-instagram-reels-publisher-verification`
- **Blockers:** No blocker for disabled-by-default local implementation. Real Meta OAuth, professional-account connection, hosted media transfer, container creation and publication require separate explicit authorization and remain out of scope for development verification.

## User Story
As a FLOW AI Content OS operator, I want instagram reels publisher and verification, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver instagram reels publisher and verification as an independently verifiable capability within social publishing.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Typed official Instagram authorization/transport contracts, owner-scoped publication repository, container creation/publish verification service, migration 0019, fake-transport tests and operator documentation. Persist credential references only; never treat container creation or publish-request acceptance as proof of publication.

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

## Implementation evidence
- Added disabled-by-default, transport-injected Instagram Login contracts and a
  professional-account authorization gate using current official Meta scopes.
- Claims bind the exact approved `INSTAGRAM_REELS_V1` artifact, immutable account
  and credential references, source reference, caption/feed/AI disclosure metadata
  and human approval. Raw tokens and public media URLs are not persisted.
- Migration `0019` distinguishes YouTube and Instagram contracts, preserves new
  YouTube claims after the discriminator, and enforces separate single-winner
  `CONTAINER_RESERVED` and `PUBLISH_RESERVED` barriers plus immutable recovery,
  terminal state and final remote-proof rules.
- Final `PUBLISHED` requires the exact container to report `PUBLISHED` and exact
  media/account/type/permalink proof. Ambiguous mutations require operator recovery
  or cancellation and are never retried blindly.
- Verification: 77 focused Instagram/YouTube/config/migration tests passed; the
  pre-review complete 496-test suite passed; all 19 migrations parsed; compileall,
  dependency validation and diff hygiene passed. Final full-suite evidence follows
  the independent correction re-review.
- External limit: no Meta OAuth, account connection, public media hosting,
  container creation, publish request or public action was performed. Live
  PostgreSQL and Meta HTTP behavior remain unverified.
