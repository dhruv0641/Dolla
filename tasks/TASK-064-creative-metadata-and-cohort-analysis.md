# TASK-064: Creative metadata and cohort analysis

- **Parent epic:** EPIC-13 — Analytics and Growth
- **Assigned agent:** Analytics Engineer
- **Priority:** P2
- **Dependencies:** TASK-063
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub issue:** [#201](https://github.com/dhruv0641/Dolla/issues/201)
- **Implementation PR:** [#202](https://github.com/dhruv0641/Dolla/pull/202) targeting `develop`
- **Branch:** `feature/TASK-064-creative-metadata-cohort-analysis`
- **Related source documents:** ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want creative metadata and cohort analysis, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver creative metadata and cohort analysis as an independently verifiable capability within analytics and growth.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] Immutable owner/content/publication/artifact/storyboard-bound snapshots cover all 13 declared creative factors with explicit observed, unavailable or inapplicable evidence.
- [x] Versioned requests compare exactly one declared factor against one raw scalar metric on the same platform, registry and fixed collection window.
- [x] Reports disclose candidates, included samples, exclusion reasons, minimum-sample eligibility, median/IQR and immutable source fingerprints.
- [x] Small cohorts and missing values fail closed without imputation; viral outliers do not replace the median; every interpretation is explicitly descriptive and non-causal.
- [x] Owner scoping, exact replay, immutable persistence, bounded payloads and direct-write database defenses are implemented.
- [x] Operator privacy, limitations and downstream TASK-065/TASK-066 boundaries are documented; no external integration is claimed.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Implementation Evidence
- `src/flowx_os/analytics/cohorts.py` defines strict creative-factor snapshots, one-factor requests and robust non-causal summaries.
- `src/flowx_os/db/cohorts.py` provides owner-scoped insert-or-read persistence with immutable replay conflict detection.
- `migrations/0025_creative_metadata_cohort_analysis.sql` binds persisted evidence to published artifacts, metric definitions and owned source fingerprints; both tables reject update/delete.
- `docs/CREATIVE_COHORT_ANALYSIS.md` records privacy, missing-value, comparability and interpretation limits.
- Focused command: `python -m unittest tests.test_creative_cohorts tests.test_creative_cohort_repository tests.test_metric_definitions tests.test_metric_collection tests.test_metric_observation_repository tests.test_migrations -v` — 61 tests passed after review corrections.
- Final full-suite command: `python -m unittest discover -s tests -v` — all 619 tests passed once on the accepted implementation head.
- `python scripts/validate_project_plan.py`, `python -m compileall -q src tests`, migration parsing through `tests.test_migrations`, and `git diff --check` passed.
- No provider, account, paid generation, publication or live PostgreSQL action occurred. Live PostgreSQL trigger/locking behavior remains unverified.
- Independent review initially rejected caller-selected factor/report evidence. The correction binds every factor to authoritative versioned rows, derives request/snapshot/report fingerprints, persists one typed metadata/metric pair per included publication, and defers recomputation of sample sizes, eligibility, medians and quartiles until all source rows exist. Posting-time cohorts now use the versioned UTC weekday/hour projection instead of absolute instants.
- Technical Reviewer accepted exact implementation head `0a0c21f8e067f37e850596f84624fe1b28fddaaa` with no P0/P1/P2 finding after verifying the published `EXPORT_VARIANT` contract and all prior corrections.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
