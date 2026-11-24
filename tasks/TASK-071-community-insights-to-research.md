# TASK-071: Community insights to research

- **Parent epic:** EPIC-14 — Community Management
- **Assigned agent:** Community Workflow Engineer
- **Priority:** P2
- **Dependencies:** TASK-070
- **Estimated complexity:** 16 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub issue:** [#222](https://github.com/dhruv0641/Dolla/issues/222)
- **Implementation PR:** [#223](https://github.com/dhruv0641/Dolla/pull/223)
- **Tracker closeout PR:** [#224](https://github.com/dhruv0641/Dolla/pull/224)
- **Branch:** `feature/TASK-071-community-insights-research`
- **Related source documents:** ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want community insights to research, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver community insights to research as an independently verifiable capability within community management.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
- `src/flowx_os/community/insights.py` — deterministic proposal policy and typed inert records.
- `src/flowx_os/db/community_insights.py` — owner/source-bound PostgreSQL repository.
- `migrations/0032_community_insights_research.sql` — immutable evidence, database recomputation and deferred completeness.
- `tests/test_community_insights.py`, `tests/test_community_insight_repository.py` — rules, replay, failure and persistence boundaries.
- `.env.example`, `src/flowx_os/config.py`, `docs/COMMUNITY_INSIGHTS_RESEARCH.md` — disabled-by-default operation and limits.

## Acceptance Criteria
- [x] Capability is implemented behind documented interfaces and disabled-by-default configuration.
- [x] Errors, immutable state, exact replay and no-execution security boundaries are explicit and observable.
- [x] Acceptance evidence and operator documentation are recorded; no live integration is claimed.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

### Implementation evidence — 2026-11-24

- `python -m unittest tests.test_community_insights tests.test_community_insight_repository tests.test_community_analysis tests.test_community_analysis_repository tests.test_config tests.test_migrations -v` — 70 passed.
- All 33 migrations parse as PostgreSQL: 395 statements.
- `python -m compileall -q src tests`, `git diff --check`, and `python scripts/validate_project_plan.py` passed.
- PostgreSQL runtime verification is unavailable: `psql` is not installed and the Docker engine is not running. Trigger/locking behavior is therefore not production-verified.
- No browser, model, provider, account, response, moderation, publishing, paid, spend, or Google Flow action occurred.
- Independent Caveman accepted exact commit `4fc77397f9bdaf2a1cbe307fbe0b8784fd6b1e07` with no P0-P2 findings after separately passing the same 70 focused tests, 33 migrations/395 statements parsing, compilation, diff hygiene and project validation. Review confirmed owner/publication/latest-analysis binding, publication-first locking, SQL/Python fingerprint parity, bounded immutable replay, mandatory human review, raw-text isolation and all no-execution authorities.
- The single final `python -m unittest discover -s tests -v` run passed all 721 tests. Project validation, frontend TypeScript checking and the Next.js production build also passed.
- Implementation PR [#223](https://github.com/dhruv0641/Dolla/pull/223) passed both required checks on exact head `004fc3e996e4503d30514750b6fcb00eccdedbb8`, merged only to protected `develop` as `080131bdf20e9149ed2a170b34d23e4e8bbe85b3`, closed issue #222, and passed post-merge project validation.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
