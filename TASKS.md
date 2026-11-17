# TASKS — Master Backlog

Statuses: `BACKLOG`, `READY`, `IN_PROGRESS`, `BLOCKED`, `IN_REVIEW`, `TESTING`, `DONE`. Estimates are engineering hours, not calendar commitments. Individual task files define acceptance.

## EPIC-01: Project Foundation


- **TASK-001 Repository baseline and developer workflow** — DONE · DevOps Engineer · 8h · deps: none · Issue: [#2](https://github.com/dhruv0641/Dolla/issues/2) · PR: [#3](https://github.com/dhruv0641/Dolla/pull/3) · merged to develop as `062b7bb`; CI passed
- **TASK-002 Environment and secret handling** — DONE · DevOps Engineer · 12h · deps: TASK-001 · Issue: [#4](https://github.com/dhruv0641/Dolla/issues/4) · PR: [#5](https://github.com/dhruv0641/Dolla/pull/5) · merged to develop as `7c5537a`; CI passed
- **TASK-003 API and frontend shells** — DONE · Backend Engineer · 16h · deps: TASK-002 · Issue: [#6](https://github.com/dhruv0641/Dolla/issues/6) · PR: [#7](https://github.com/dhruv0641/Dolla/pull/7) · merged to develop as `d33b945`; CI passed
- **TASK-004 Prompt and policy registry** — DONE · AI Workflow Engineer · 4h · deps: TASK-003 · Issue: [#8](https://github.com/dhruv0641/Dolla/issues/8) · PR: [#9](https://github.com/dhruv0641/Dolla/pull/9) · merged to develop as `dc81b5b`; CI passed
- **TASK-005 Health and readiness endpoints** — DONE · Backend Engineer · 6h · deps: TASK-004 · Issue: [#10](https://github.com/dhruv0641/Dolla/issues/10) · PR: [#11](https://github.com/dhruv0641/Dolla/pull/11) · merged to develop as `404abb4`; PR CI passed

## EPIC-02: Database and Persistence

- **TASK-006 Review schema and create migrations** — DONE · Backend Engineer · 12h · deps: TASK-001 · Issue: [#12](https://github.com/dhruv0641/Dolla/issues/12) · PR: [#13](https://github.com/dhruv0641/Dolla/pull/13) · merged to develop as `3d61d80`; CI passed
- **TASK-007 Data access and transaction boundaries** — DONE · Backend Engineer · 16h · deps: TASK-006 · Issue: [#14](https://github.com/dhruv0641/Dolla/issues/14) · PR: [#15](https://github.com/dhruv0641/Dolla/pull/15) · merged to develop as `4687820`; CI passed
- **TASK-008 Workflow event and audit persistence** — DONE · Backend Engineer · 4h · deps: TASK-007 · Issue: [#16](https://github.com/dhruv0641/Dolla/issues/16) · PR: [#17](https://github.com/dhruv0641/Dolla/pull/17) · merged to develop as `5d0845c`; CI passed
- **TASK-009 Transactional outbox and worker leasing** — DONE · Backend Engineer · 6h · deps: TASK-008 · Issue: [#18](https://github.com/dhruv0641/Dolla/issues/18) · PR: [#19](https://github.com/dhruv0641/Dolla/pull/19) · merged to develop as `ff6f521`; CI passed
- **TASK-010 Backup, restore and retention** — DONE · Backend Engineer · 8h · deps: TASK-009 · Issue: [#20](https://github.com/dhruv0641/Dolla/issues/20) · PR: [#21](https://github.com/dhruv0641/Dolla/pull/21) · merged to develop as `426bf84`; CI passed

## EPIC-03: Backend and Orchestration

- **TASK-011 Authentication and role model** — DONE · Backend Engineer · 16h · deps: TASK-003, TASK-006, TASK-009 · Issue: [#22](https://github.com/dhruv0641/Dolla/issues/22) · Branch: `feature/TASK-011-authentication-and-role-model` · PR: [#23](https://github.com/dhruv0641/Dolla/pull/23) · merged to develop as `46c6caa`; CI passed
- **TASK-012 Brand and content lifecycle APIs** — DONE · Backend Engineer · 4h · deps: TASK-011 · Issues: [#24](https://github.com/dhruv0641/Dolla/issues/24), [#26](https://github.com/dhruv0641/Dolla/issues/26) · PRs: [#25](https://github.com/dhruv0641/Dolla/pull/25), [#27](https://github.com/dhruv0641/Dolla/pull/27) · merged to develop at `8a8338c` and `28b5677`; CI and independent review passed
- **TASK-013 Typed state machines and validation** — DONE · Backend Engineer · 6h · deps: TASK-012 · Issue: [#29](https://github.com/dhruv0641/Dolla/issues/29) · PR: [#30](https://github.com/dhruv0641/Dolla/pull/30) · merged to develop as `527586c`; CI and independent review passed
- **TASK-014 Idempotent workflow processing** — IN_REVIEW · Backend Engineer · 8h · deps: TASK-013 · Issue: [#31](https://github.com/dhruv0641/Dolla/issues/31) · Branch: `feature/TASK-014-idempotent-workflow-processing` · PR: [#32](https://github.com/dhruv0641/Dolla/pull/32) · independent review passed; CI pending
- **TASK-015 Scheduling, retries and dead letters** — BACKLOG · Backend Engineer · 12h · deps: TASK-014

## EPIC-04: AI Agent System

- **TASK-016 Agent schemas and validation** — BACKLOG · AI Workflow Engineer · 4h · deps: TASK-011, TASK-013
- **TASK-017 Research with source evidence** — BACKLOG · AI Workflow Engineer · 6h · deps: TASK-016
- **TASK-018 Strategy and idea scoring** — BACKLOG · AI Workflow Engineer · 8h · deps: TASK-017
- **TASK-019 Script and storyboard generation** — BACKLOG · AI Workflow Engineer · 12h · deps: TASK-018
- **TASK-020 Prompt, review and analyst agents** — BACKLOG · AI Workflow Engineer · 16h · deps: TASK-019

## EPIC-05: Google Flow MCP Integration

- **TASK-021 Discover actual MCP manifest** — BACKLOG · Flow MCP Integration Engineer · 6h · deps: TASK-002
- **TASK-022 Capability-gated adapter interface** — BACKLOG · Flow MCP Integration Engineer · 8h · deps: TASK-021
- **TASK-023 Auth and account health** — BACKLOG · Flow MCP Integration Engineer · 12h · deps: TASK-022
- **TASK-024 Safe submit, polling and recovery** — BACKLOG · Flow MCP Integration Engineer · 16h · deps: TASK-023
- **TASK-025 Media retrieval and metadata** — BACKLOG · Flow MCP Integration Engineer · 4h · deps: TASK-024

## EPIC-06: Credit and Account Management

- **TASK-026 Authorized account registry** — BACKLOG · Credit and Account Engineer · 8h · deps: TASK-006, TASK-021
- **TASK-027 Credit quote, reservation and limits** — BACKLOG · Credit and Account Engineer · 12h · deps: TASK-026
- **TASK-028 Observed credit ledger and reconciliation** — BACKLOG · Credit and Account Engineer · 16h · deps: TASK-027
- **TASK-029 Concurrency, pause and reset tracking** — BACKLOG · Credit and Account Engineer · 4h · deps: TASK-028
- **TASK-030 Unknown-spend alarms and fail-closed controls** — BACKLOG · Credit and Account Engineer · 6h · deps: TASK-029

## EPIC-07: Scene and Media Management

- **TASK-031 Versioned storyboard and scene timeline** — BACKLOG · Media Pipeline Engineer · 12h · deps: TASK-006, TASK-019, TASK-025, TASK-030
- **TASK-032 Asset storage, hashes and lineage** — BACKLOG · Media Pipeline Engineer · 16h · deps: TASK-031
- **TASK-033 Scene jobs and bounded retries** — BACKLOG · Media Pipeline Engineer · 4h · deps: TASK-032
- **TASK-034 Media probing and validation** — BACKLOG · Media Pipeline Engineer · 6h · deps: TASK-033
- **TASK-035 Asset search and retention** — BACKLOG · Media Pipeline Engineer · 8h · deps: TASK-034

## EPIC-08: Local Audio and Voiceover

- **TASK-036 Evaluate local TTS** — BACKLOG · Media Pipeline Engineer · 16h · deps: TASK-031
- **TASK-037 Voice profiles and synthesis** — BACKLOG · Media Pipeline Engineer · 4h · deps: TASK-036
- **TASK-038 Timing, normalization and zero-second narration** — BACKLOG · Media Pipeline Engineer · 6h · deps: TASK-037
- **TASK-039 Captions and subtitle alignment** — BACKLOG · Media Pipeline Engineer · 8h · deps: TASK-038
- **TASK-040 Audio preview and management** — BACKLOG · Media Pipeline Engineer · 12h · deps: TASK-039

## EPIC-09: Automated Video Editing

- **TASK-041 FFmpeg render worker and manifests** — BACKLOG · Media Pipeline Engineer · 4h · deps: TASK-032, TASK-036
- **TASK-042 Normalize codecs, fps and aspect ratios** — BACKLOG · Media Pipeline Engineer · 6h · deps: TASK-041
- **TASK-043 Compose scenes, audio and subtitles** — BACKLOG · Media Pipeline Engineer · 8h · deps: TASK-042
- **TASK-044 Platform export variants** — BACKLOG · Media Pipeline Engineer · 12h · deps: TASK-043
- **TASK-045 Render versions and artifacts** — BACKLOG · Media Pipeline Engineer · 16h · deps: TASK-044

## EPIC-10: Video Quality Assurance

- **TASK-046 Deterministic integrity checks** — BACKLOG · QA and Security Engineer · 6h · deps: TASK-034, TASK-045
- **TASK-047 Visual and audio evaluation** — BACKLOG · QA and Security Engineer · 8h · deps: TASK-046
- **TASK-048 Policy, factuality and copyright signals** — BACKLOG · QA and Security Engineer · 12h · deps: TASK-047
- **TASK-049 Scene retry limits and spend gate** — BACKLOG · QA and Security Engineer · 16h · deps: TASK-048
- **TASK-050 Human review and approvals** — BACKLOG · QA and Security Engineer · 4h · deps: TASK-049

## EPIC-11: Frontend Dashboard

- **TASK-051 Responsive design system and shell** — BACKLOG · Frontend Engineer · 8h · deps: TASK-003, TASK-012
- **TASK-052 Live executive command center** — BACKLOG · Frontend Engineer · 12h · deps: TASK-051
- **TASK-053 Production board, scenes and assets** — BACKLOG · Frontend Engineer · 16h · deps: TASK-052
- **TASK-054 Flow control, ledger and jobs** — BACKLOG · Frontend Engineer · 4h · deps: TASK-053
- **TASK-055 QA, voice, calendar and publishing screens** — BACKLOG · Frontend Engineer · 6h · deps: TASK-054
- **TASK-056 Agent, analytics, community and settings screens** — BACKLOG · Frontend Engineer · 8h · deps: TASK-055

## EPIC-12: Social Publishing

- **TASK-057 Official YouTube publisher and verification** — BACKLOG · Publishing Integration Engineer · 12h · deps: TASK-011, TASK-045, TASK-050, TASK-072
- **TASK-058 Instagram Reels publisher and verification** — BACKLOG · Publishing Integration Engineer · 16h · deps: TASK-057
- **TASK-059 Facebook Page Reels publisher and verification** — BACKLOG · Publishing Integration Engineer · 4h · deps: TASK-058
- **TASK-060 Independent platform state and reconciliation** — BACKLOG · Publishing Integration Engineer · 6h · deps: TASK-059
- **TASK-061 Approval, schedule and duplicate prevention** — BACKLOG · Publishing Integration Engineer · 8h · deps: TASK-060

## EPIC-13: Analytics and Growth

- **TASK-062 Platform metrics and definitions** — BACKLOG · Analytics Engineer · 16h · deps: TASK-006, TASK-057, TASK-060
- **TASK-063 Windowed snapshots and missing values** — BACKLOG · Analytics Engineer · 4h · deps: TASK-062
- **TASK-064 Creative metadata and cohort analysis** — BACKLOG · Analytics Engineer · 6h · deps: TASK-063
- **TASK-065 Evidence-backed recommendations and experiments** — BACKLOG · Analytics Engineer · 8h · deps: TASK-064
- **TASK-066 Spend-aware approved feedback loop** — BACKLOG · Analytics Engineer · 12h · deps: TASK-065

## EPIC-14: Community Management

- **TASK-067 Authorized comment ingestion** — BACKLOG · Community Workflow Engineer · 4h · deps: TASK-011, TASK-057, TASK-060
- **TASK-068 Theme clustering and safety classification** — BACKLOG · Community Workflow Engineer · 6h · deps: TASK-067
- **TASK-069 Draft replies and escalation** — BACKLOG · Community Workflow Engineer · 8h · deps: TASK-068
- **TASK-070 Human approval and official responses** — BACKLOG · Community Workflow Engineer · 12h · deps: TASK-069
- **TASK-071 Community insights to research** — BACKLOG · Community Workflow Engineer · 16h · deps: TASK-070

## EPIC-15: Security Observability and Deployment

- **TASK-072 Threat model, access and audit** — BACKLOG · DevOps Engineer · 6h · deps: none
- **TASK-073 Logs, metrics, traces and alerts** — BACKLOG · DevOps Engineer · 8h · deps: TASK-072
- **TASK-074 Docker Compose and environment profiles** — BACKLOG · DevOps Engineer · 12h · deps: TASK-073
- **TASK-075 Encrypted backups and runbooks** — BACKLOG · DevOps Engineer · 16h · deps: TASK-074
- **TASK-076 Security and release gates** — BACKLOG · DevOps Engineer · 4h · deps: TASK-075

## Totals

- Epics: 15
- Tasks: 76
- Estimated effort: 698 engineering hours
- DONE: 13 (TASK-001 through TASK-013); TASK-014 is in progress.

## GitHub delivery references

- Repository: [dhruv0641/Dolla](https://github.com/dhruv0641/Dolla)
- Main branch ruleset: [ID 27482128](https://github.com/dhruv0641/Dolla/settings/rules/27482128) — active; PR, one approval, required CI, deletion and force-push blocked.
- Develop branch ruleset: [ID 27482560](https://github.com/dhruv0641/Dolla/settings/rules/27482560) — active; PR and required CI.
- TASK-001 PR: [#3](https://github.com/dhruv0641/Dolla/pull/3), merged to `develop`; issue [#2](https://github.com/dhruv0641/Dolla/issues/2) closed by merge.
- TASK-002 issue: [#4](https://github.com/dhruv0641/Dolla/issues/4), closed; PR [#5](https://github.com/dhruv0641/Dolla/pull/5) merged to `develop`.
- TASK-002 merged to `develop` at `7c5537a8af31dc90baaef3cb9b33437a3850c957`; issue [#4](https://github.com/dhruv0641/Dolla/issues/4) closed by merge.
- TASK-003 issue: [#6](https://github.com/dhruv0641/Dolla/issues/6); branch `feature/TASK-003-api-and-frontend-shells`.
- TASK-003 PR: [#7](https://github.com/dhruv0641/Dolla/pull/7), targeting `develop`; GitHub Actions passed on head `7d0a9d0d777d9fa9e3389eefdbd1d27f5c750209`.
- TASK-003 merged to `develop` at `d33b9451e18933f37e4fc5b35f0fa7cae7fad269`; issue [#6](https://github.com/dhruv0641/Dolla/issues/6) closed and post-merge CI passed.
- TASK-004 issue: [#8](https://github.com/dhruv0641/Dolla/issues/8); branch `feature/TASK-004-prompt-and-policy-registry`.
- TASK-004 PR: [#9](https://github.com/dhruv0641/Dolla/pull/9), merged to `develop`; CI passed.
- TASK-004 merged to `develop` at `dc81b5b112a03266a0421ce943a1072b95ae5c4b`; issue [#8](https://github.com/dhruv0641/Dolla/issues/8) closed and PR/push CI passed.
- TASK-005 issue: [#10](https://github.com/dhruv0641/Dolla/issues/10); branch `feature/TASK-005-health-readiness-endpoints`.
- TASK-005 PR: [#11](https://github.com/dhruv0641/Dolla/pull/11), merged to `develop` at `404abb450460c30ccd16507708e7c5f73de26382`; issue #10 closed and PR CI passed.
- TASK-006 issue: [#12](https://github.com/dhruv0641/Dolla/issues/12); branch `feature/TASK-006-review-schema-and-create-migrations`.
- TASK-006 merged to `develop` at `3d61d80fdeb398c96e5cdb0f6b161af4526ff279`; issue [#12](https://github.com/dhruv0641/Dolla/issues/12) closed, PR/push CI passed.
- TASK-007 issue: [#14](https://github.com/dhruv0641/Dolla/issues/14); branch `feature/TASK-007-data-access-and-transactions`.
- TASK-007 merged to `develop` at `4687820978745e4abbd0e8c43c2b4d9388b46a04`; issue [#14](https://github.com/dhruv0641/Dolla/issues/14) closed; PR and push CI passed.
- TASK-008 issue: [#16](https://github.com/dhruv0641/Dolla/issues/16); branch `feature/TASK-008-workflow-event-audit-persistence`.
- TASK-008 PR: [#17](https://github.com/dhruv0641/Dolla/pull/17), merged to `develop` as `5d0845c9ab6afec85e818417af0ffdc6765f7ca8`; issue #16 closed and CI passed.
- TASK-009 issue: [#18](https://github.com/dhruv0641/Dolla/issues/18); branch `feature/TASK-009-transactional-outbox-and-leasing`.
- TASK-009 PR: [#19](https://github.com/dhruv0641/Dolla/pull/19), merged to `develop` as `ff6f521`; CI passed.
- TASK-010 issue: [#20](https://github.com/dhruv0641/Dolla/issues/20); branch `feature/TASK-010-backup-restore-and-retention`.
- TASK-010 PR: [#21](https://github.com/dhruv0641/Dolla/pull/21), targeting `develop`; CI pending.
- TASK-010 merged to `develop` at `426bf84b38cd2da45cd63bf61cceda3878dd7874`; issue #20 closed and PR/push CI passed.
- TASK-011 issue [#22](https://github.com/dhruv0641/Dolla/issues/22) and PR [#23](https://github.com/dhruv0641/Dolla/pull/23) merged to develop; CI passed.
- TASK-012 issues [#24](https://github.com/dhruv0641/Dolla/issues/24) and [#26](https://github.com/dhruv0641/Dolla/issues/26) closed. PR [#25](https://github.com/dhruv0641/Dolla/pull/25) merged to `develop` as `8a8338c`; reviewer follow-up PR [#27](https://github.com/dhruv0641/Dolla/pull/27) merged as `28b5677`. CI passed on both PRs; independent review found no correctness or tenant-isolation defect.
- TASK-012 closeout record PR [#28](https://github.com/dhruv0641/Dolla/pull/28) merged to `develop` as `ce0d2b8`; CI passed.
- TASK-013 issue [#29](https://github.com/dhruv0641/Dolla/issues/29); branch `feature/TASK-013-typed-state-machines-and-validation`; PR [#30](https://github.com/dhruv0641/Dolla/pull/30) targets `develop`; CI and independent review passed, merge pending.
- TASK-013 merged to `develop` as `527586ca034343e4ee72f5a36ea120745dc08218`; issue #29 closed, CI and independent review passed.
- TASK-014 issue [#31](https://github.com/dhruv0641/Dolla/issues/31); branch `feature/TASK-014-idempotent-workflow-processing`; PR [#32](https://github.com/dhruv0641/Dolla/pull/32) targets `develop`; independent review passed, CI pending.
- TASK-008 PR: [#17](https://github.com/dhruv0641/Dolla/pull/17), targeting `develop`; CI pending.
- Integration branch: [`develop`](https://github.com/dhruv0641/Dolla/tree/develop) at seed commit `1da41e47410228b9fe3bdc87dba26a1931fb9d2a`.
- Goal issue: [#1](https://github.com/dhruv0641/Dolla/issues/1). Task-linked issues and PRs are recorded here and in each task specification as created and verified.
