# TASK-065: Evidence-backed recommendations and experiments

- **Parent epic:** EPIC-13 — Analytics and Growth
- **Assigned agent:** Analytics Engineer
- **Priority:** P2
- **Dependencies:** TASK-064
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub issue:** [#204](https://github.com/dhruv0641/Dolla/issues/204)
- **Branch:** `feature/TASK-065-evidence-backed-recommendations-experiments`
- **Pull request:** [#205](https://github.com/dhruv0641/Dolla/pull/205), merged to `develop` as `83eabf4fe708ceaa18efad056cd2d4e881cc3931`
- **Related source documents:** ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want evidence-backed recommendations and experiments, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver evidence-backed recommendations and experiments as an independently verifiable capability within analytics and growth.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] A recommendation requires an immutable `DESCRIPTIVE` TASK-064 report with at least two eligible cohorts and preserves its exact request, report and typed source fingerprints.
- [x] The recommendation exposes platform, raw metric, window, sample sizes, median/IQR, small groups and all exclusion counts, and is explicitly association-only, non-causal and not a guaranteed winner.
- [x] An experiment proposal pins exactly one creative factor, control/treatment, owner, platform, metric, window, balanced allocation, minimum/target samples, fixed stop rule and fail-closed safety rules.
- [x] Proposals remain `DRAFT_REQUIRES_HUMAN_APPROVAL` and explicitly deny execution, generation, spend, account connection, scheduling, upload and publishing authority; TASK-066 owns any approved feedback loop.
- [x] Owner-scoped immutable insert-or-read persistence rejects request replay conflicts, substituted lineage, non-canonical JSON and direct-write authorization claims.
- [x] Errors and security boundaries are explicit; operator documentation records statistical, privacy and live-runtime limits without claiming external integration.

## Tests and Verification
- Focused domain/repository/cohort/migration suite: **45 passed**.
- Single final full suite: **628 passed**.
- Independent Caveman review: accepted with no critical, P1 or P2 findings.
- PostgreSQL parser review: **27 migrations / 239 statements** passed in the independent review environment; local live PostgreSQL execution remains unverified.
- `compileall`, `git diff --check` and project validator passed (15 epics, 76 tasks, no cycles).
- No provider call, account connection, paid generation, scheduling, upload, publication or other external action occurred.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
