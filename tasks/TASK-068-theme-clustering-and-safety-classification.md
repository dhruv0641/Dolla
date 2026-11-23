# TASK-068: Theme clustering and safety classification

- **Parent epic:** EPIC-14 — Community Management
- **Assigned agent:** Community Workflow Engineer
- **Priority:** P2
- **Dependencies:** TASK-067
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** IN_PROGRESS
- **GitHub issue:** [#213](https://github.com/dhruv0641/Dolla/issues/213)
- **Branch:** `feature/TASK-068-theme-clustering-safety`
- **Related source documents:** ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want theme clustering and safety classification, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver theme clustering and safety classification as an independently verifiable capability within community management.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [ ] Capability is implemented behind documented interfaces and configuration.
- [ ] Errors, state transitions and security boundaries are explicit and observable.
- [ ] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Implementation Evidence
- `CommunityAnalyzer` implements bounded local `community-theme-v1` and `community-safety-v1` rules over the exact latest complete TASK-067 snapshot. `NO_DETECTED_SIGNAL` is explicitly not a safety guarantee, and all matched safety signals require human review.
- Migration `0029_community_theme_safety_analysis.sql` stores immutable reports, per-comment classifications and clusters; database triggers independently verify current owner/source lineage, fixed policy results, fingerprints, completeness and `outbound_action_authorized=false`.
- `FLOWX_COMMUNITY_ANALYSIS_ENABLED` defaults to `false`; no model/provider, reply, moderation, account, publishing, spend or Flow method exists in this boundary.
- Focused community/config/migration verification passes 75 tests. All 30 migrations and 333 statements parse, including 21 statements in migration 0029; compileall, project-plan validation and diff hygiene pass.
- Docker is installed but its Linux engine is unavailable, and `psql` is unavailable. Live PostgreSQL trigger/concurrency behavior, linguistic calibration, multilingual recall, adversarial evasion and operator escalation quality remain unverified.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
