# Implementation Roadmap and Development Log

This is the single Markdown record of planned development, estimated effort, milestones and dated progress. Estimates are engineering-hour ranges, not calendar commitments; duration depends on staffing, credentials, reviews and external API readiness. Feature work has not started.

## Dependency spine
`Foundation → Data model/outbox → Domain APIs/workers → actual Flow capability proof + credit safety → scenes/assets → local TTS/FFmpeg → QC/approval → dashboard → official publishing → analytics/community → operational hardening`. P0 is an early external checkpoint; no Flow integration claim before live evidence. Task-level edges are listed in `TASKS.md` and `tasks/`.

## Milestones and phase estimates
| Phase | Scope | Estimated effort | Acceptance gate |
|---|---|---:|---|
| P0 Flow proof | Discover MCP manifest/auth; authorized capped generation, download, ffprobe, credit reconcile | 16–40h plus external wait | Playable asset and reconciled cost; stop if unavailable. |
| P1 Video vertical slice | Idea, script, 3–4 scenes, local voice at 0:00, FFmpeg and QC | 80–140h | One accepted 24–32 second video. |
| P2 Production management | Migrations, durable jobs, assets, retries, QA/approval and dashboard | 120–220h | Restart-safe jobs and visible failures. |
| P3 Official publishing | Separate YouTube, Instagram professional and Facebook Page adapters | 60–120h plus platform wait | Authorized test publish verified per platform. |
| P4 Scheduling | Calendar, variants, timezone, reconciliation and authorization policy | 40–80h | Repeatable schedule without duplicate posts. |
| P5 Intelligence/community | Analytics, experiments, community drafts and recommendations | 80–140h | Decisions trace to real metrics; human override. |
| P6 Operations | Account ledgers, security, observability, backups, deployment | 60–110h | No uncertain spend or terms/security bypass. |

## Task dependency structure
There are 15 epics and 76 task specifications. Tasks within an epic are ordered by their prior task; the first task of each epic depends on the first task of the preceding epic. This conservative spine makes dependencies explicit while potentially serializing work. Refine edges once implementation goals establish stable interfaces. Full titles, owners, priorities and estimates are in `TASKS.md`.

## Minimal end-to-end MVP
One authorized Flow account → evidence-backed idea → approved script/storyboard → 3–4 individually tracked scenes → local narration from 0:00 and subtitles → normalized FFmpeg render → QC → human-approved MP4. Publishing/analytics follow as later verified phases.

## Testing and deployment strategy
Later goals should unit-test state rules, schemas, idempotency and media checks; integration-test PostgreSQL/outbox/adapters; use controlled authorized external tests for Flow/platform capabilities; and verify restart/recovery and duplicate-publish behavior end to end. Do not report tests unless run. Live paid calls require explicit authorization. Initial deployment target: Docker Compose on secure local workstation/self-hosted VM with frontend, FastAPI, PostgreSQL, scheduler/worker and persistent media; Flow MCP may run separately under least privilege. Add remote TLS/auth, encrypted backups, metrics, alerts and recovery runbooks.

## Development log — single chronological record
| Date/time (Asia/Kolkata) | Type | Description | Estimate / actual | Status |
|---|---|---|---:|---|
| 2026-11-17 23:26 IST (filesystem timestamp, minute precision) | Initialization | Read Master Prompt and four architecture assets; inspected repository; created memory files, 15 epics, 76 task specs, capability matrix, ADRs and roadmap. No feature code or external calls. | Actual time not instrumented; 0 feature hours | Complete |
| 2026-11-17 23:29:17 IST | Audit and correction | Aligned task owners with specialist roles; replaced placeholder cross-epic edges with prerequisite-based edges; added explicit delegation/approval/escalation rules. Audited all 76 task specs and checked dependency refs/cycles. | 0 feature hours | Complete |
| 2026-11-17 23:29 IST | MCP inventory check | Queried connected MCP resources; no Google Flow MCP server was listed, so Flow operations remain UNVERIFIED. Updated capability matrix and source interpretation ADR. | 0 feature hours | Complete |
| 2026-11-17 23:47 IST | GitHub bootstrap | Verified `dhruv0641` admin/push access, created goal/task issues, enabled active `main` protection ruleset 27482128, initialized local Git with `develop`, and pushed planning seed commit `1da41e4`. No history existed on remote. | 0 feature hours | Complete |
| 2026-11-17 23:49 IST | TASK-001 PR and branch policy | Opened [PR #3](https://github.com/dhruv0641/Dolla/pull/3) to `develop`; initial Actions checks passed. Enabled active `develop` ruleset 27482560 and required `validate-project-plan` on both protected branches. Recorded issue/PR/ruleset references in project trackers. | 0 feature hours | In review |
| 2026-11-17 23:49 IST | TASK-001 merge | Merged [PR #3](https://github.com/dhruv0641/Dolla/pull/3) to `develop` at `062b7bb0273360dcf483a4e804e526c0c4bc9b21`; GitHub Actions passed and issue #2 closed. `main` remains untouched. | 0 feature hours | Done |
| 2026-11-17 23:55 IST | TASK-002 start | Opened issue [#4](https://github.com/dhruv0641/Dolla/issues/4); began environment configuration and secret-reference handling on the task branch. Added side-effect-free settings, `.env` precedence, docs, and 7 unit tests; all local checks pass. PR pending. | 12h estimate | In progress |
| 2026-11-18 00:00 IST | TASK-002 merge | Merged [PR #5](https://github.com/dhruv0641/Dolla/pull/5) to `develop` at `7c5537a8af31dc90baaef3cb9b33437a3850c957`; 7 local tests and post-merge GitHub Actions passed; issue #4 closed. | 12h estimate | Done |
| 2026-11-18 00:12 IST | TASK-003 start | Opened issue [#6](https://github.com/dhruv0641/Dolla/issues/6); started FastAPI service shell, endpoint tests, and Next.js dashboard shell on `feature/TASK-003-api-and-frontend-shells`. Frontend package audit found high-severity dev-only `picomatch` advisories; removed unused ESLint/Tailwind tooling while retaining production dependencies. | 16h estimate | In progress |
| 2026-11-18 00:22 IST | TASK-003 implementation and PR | Added FastAPI/Next.js shells, API tests, setup docs, frontend build/typecheck/audit in CI, and dashboard screenshot. Local plan validation, 10 Python tests, frontend typecheck/build, dependency audit (0 vulnerabilities) and diff whitespace check passed. Opened [PR #7](https://github.com/dhruv0641/Dolla/pull/7) to `develop`; both push and PR GitHub Actions runs passed on implementation commit `7d0a9d0`. | 16h estimate | In review |
| 2026-11-18 00:24 IST | TASK-003 merge | Merged [PR #7](https://github.com/dhruv0641/Dolla/pull/7) to `develop` at `d33b9451e18933f37e4fc5b35f0fa7cae7fad269`; PR and post-merge GitHub Actions passed; issue #6 closed. | 16h estimate | Done |
| 2026-11-18 00:26 IST | TASK-004 start | Opened issue [#8](https://github.com/dhruv0641/Dolla/issues/8) and started a typed versioned JSON prompt/policy registry with schema validation and safe defaults. | 4h estimate | In progress |
| 2026-11-18 00:26 IST | TASK-004 implementation and PR | Added strict typed registry loading, safe prompt/publishing policy defaults, operator documentation, and five policy tests. Plan validation and all 16 Python tests passed. Opened [PR #9](https://github.com/dhruv0641/Dolla/pull/9); PR and push CI passed. | 4h estimate | In review |
| 2026-11-18 00:28 IST | TASK-004 merge | Merged [PR #9](https://github.com/dhruv0641/Dolla/pull/9) to `develop` at `dc81b5b112a03266a0421ce943a1072b95ae5c4b`; CI passed and issue #8 closed. | 4h estimate | Done |
| 2026-11-18 00:28 IST | TASK-005 start | Opened issue [#10](https://github.com/dhruv0641/Dolla/issues/10); added `/readyz` design on top of process-only `/healthz`, including explicit probe states and no secret-bearing errors. | 6h estimate | In progress |
| 2026-11-18 00:28 IST | TASK-005 implementation and PR | Implemented `/readyz` with injected probes, fail-closed states, and suppressed probe exception details; added docs and tests. Opened [PR #11](https://github.com/dhruv0641/Dolla/pull/11); local checks passed. | 6h estimate | In review |
| 2026-11-18 00:34 IST | TASK-005 merge | Merged PR #11 to `develop` at `404abb450460c30ccd16507708e7c5f73de26382`; PR CI passed and issue #10 closed. | 6h estimate | Done |
| 2026-11-18 00:35 IST | TASK-006 start | Opened issue #12; reviewed supplied PostgreSQL schema, drafted one-time migration, added asset lineage FK and recommendation-period constraint, and documented multi-tenant/RLS, data-retention, credit-ledger, and lease follow-ups. Parser accepted all 33 statements; local server unavailable. | 12h estimate | In progress |
| 2026-11-18 00:41 IST | TASK-006 PR | Added `pglast` grammar parsing to the CI backend suite (22 tests pass locally) and opened [PR #13](https://github.com/dhruv0641/Dolla/pull/13). PostgreSQL execution remains unverified because no local server/client is available. | 12h estimate | In review |
| 2026-11-18 00:43 IST | TASK-006 merge | Merged PR #13 to `develop` at `3d61d80fdeb398c96e5cdb0f6b161af4526ff279`; parser and CI passed; issue #12 closed. | 12h estimate | Done |
| 2026-11-18 00:44 IST | TASK-007 start | Opened issue #14; began an async unit-of-work boundary with commit-on-success and rollback-on-error tests. | 16h estimate | In progress |
| 2026-11-18 00:47 IST | TASK-007 PR | Added driver-neutral unit-of-work, connection-release/commit/rollback tests and docs; 24 Python tests passed. Opened [PR #15](https://github.com/dhruv0641/Dolla/pull/15). | 16h estimate | In review |
| 2026-11-18 00:48 IST | TASK-007 merge | Merged PR #15 to `develop` at `4687820978745e4abbd0e8c43c2b4d9388b46a04`; PR/push CI passed and issue #14 closed. | 16h estimate | Done |
| 2026-11-18 00:49 IST | TASK-008 start | Opened issue #16; began parameterized workflow event persistence inside the established unit-of-work, with payload validation and audit redaction guidance. | 4h estimate | In progress |
| 2026-11-18 00:52 IST | TASK-008 PR | Added parameterized event inserts, UUID/field/payload validation, docs, and three tests; 27 Python tests passed. Opened [PR #17](https://github.com/dhruv0641/Dolla/pull/17). | 4h estimate | In review |
| 2026-11-18 00:53 IST | TASK-008 merge | Merged PR #17 to `develop` at `5d0845c9ab6afec85e818417af0ffdc6765f7ca8`; PR/push CI passed and issue #16 closed. | 4h estimate | Done |
| 2026-11-18 00:54 IST | TASK-009 start | Opened issue #18; added idempotent outbox enqueue, SKIP LOCKED lease query, lease-owner completion, migration indexes, and lifecycle documentation. | 6h estimate | In progress |
| 2026-11-18 00:58 IST | TASK-009 PR | Added outbox enqueue/lease operations, second migration, grammar validation, docs, and five tests; 32 Python tests passed. Opened [PR #19](https://github.com/dhruv0641/Dolla/pull/19). | 6h estimate | In review |
| 2026-11-18 00:59 IST | TASK-009 merge | Merged PR #19 to `develop` at `ff6f521f66e710ae0c06cf1b1991c4771c3aac6e`; CI passed and issue #18 closed. | 6h estimate | Done |
| 2026-11-18 01:00 IST | TASK-010 start | Opened issue #20; implemented safe pg_dump/pg_restore primitives and dry-run retention planning without running database or deletion operations. | 8h estimate | In progress |
| 2026-11-18 01:06 IST | TASK-010 implementation | Added archive verification and checksum manifests, safe service-file credentials, transactional restore flags, and dry-run retention planning. Mocked tests use temporary directories only; all 37 Python tests and project-plan validation passed. Live backup/restore remain unverified. | 8h estimate | In progress |
| TBD | P0 | Discover actual MCP tools/auth; after spend authorization generate one short clip, inspect download and reconcile credits. | 16–40h + wait | Not started |
| TBD | P1 | Build one reviewed end-to-end video using Flow, local narration, FFmpeg and QC. | 80–140h | Not started |
| TBD | P2 | Durable persistence, APIs, workers, asset lineage, approvals and data-backed dashboard. | 120–220h | Not started |
| TBD | P3 | Implement and verify official platform adapters. | 60–120h + wait | Not started |
| TBD | P4 | Calendar, variants, timezone-safe schedule and duplicate reconciliation. | 40–80h | Not started |
| TBD | P5 | Analytics, experiments, community and recommendation workflow. | 80–140h | Not started |
| TBD | P6 | Multi-account ledgers, security, observability, backup and deployment. | 60–110h | Not started |

## Critical path and blockers
Actual Flow MCP identity/manifest and authorized account → capability/auth proof → spend-authorized short generation → media retrieval and credit reconciliation. This precedes production claims. Publishing requires eligible accounts, OAuth and current policy/API validation. Auth provider, local model choices, TTS hardware, storage and deployment host remain goal-specific decisions.

## Source traceability
- Master Agentic Prompt: objectives, stack constraints, roles, goal workflow and initialization boundary.
- `ARCHITECTURE (1).md`: HLD/LLD, lifecycle, safety, media, publishing, analytics, dashboard, operations and P0–P6 gates.
- `SCHEMA.sql`: PostgreSQL entities/constraints; design-only, migration review required.
- `FLOW_MCP_ADAPTER_CONTRACT.json`: proposed normalized contract and guardrails, not server support.
- `DASHBOARD_DEMO.html`: UX reference with explicitly illustrative data.
