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
