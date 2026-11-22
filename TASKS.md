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
- **TASK-014 Idempotent workflow processing** — DONE · Backend Engineer · 8h · deps: TASK-013 · Issue: [#31](https://github.com/dhruv0641/Dolla/issues/31) · PR: [#32](https://github.com/dhruv0641/Dolla/pull/32) · merged to develop as `d8baa38`; CI and independent review passed
- **TASK-015 Scheduling, retries and dead letters** — DONE · Backend Engineer · 12h · deps: TASK-014 · Issue: [#33](https://github.com/dhruv0641/Dolla/issues/33) · PR: [#34](https://github.com/dhruv0641/Dolla/pull/34) · merged to develop as `61c5ae9`; CI and independent review passed

## EPIC-04: AI Agent System

- **TASK-016 Agent schemas and validation** — DONE · AI Workflow Engineer · 4h · deps: TASK-011, TASK-013 · Issue: [#37](https://github.com/dhruv0641/Dolla/issues/37) · PR: [#38](https://github.com/dhruv0641/Dolla/pull/38) · merged to develop as `cf90289`; CI and independent review passed
- **TASK-017 Research with source evidence** — DONE · AI Workflow Engineer · 6h · deps: TASK-016 · Issue: [#40](https://github.com/dhruv0641/Dolla/issues/40) · PR: [#41](https://github.com/dhruv0641/Dolla/pull/41) · merged to develop as `1052800`; CI and independent review passed
- **TASK-018 Strategy and idea scoring** — DONE · AI Workflow Engineer · 8h · deps: TASK-017 · Issue: [#43](https://github.com/dhruv0641/Dolla/issues/43) · PR: [#44](https://github.com/dhruv0641/Dolla/pull/44) · merged to develop as `ef36c14`; CI and independent review passed
- **TASK-019 Script and storyboard generation** — DONE · AI Workflow Engineer · 12h · deps: TASK-018 · Issue: [#46](https://github.com/dhruv0641/Dolla/issues/46) · PR: [#47](https://github.com/dhruv0641/Dolla/pull/47) · merged to develop as `10fa7c5`; CI and independent review passed
- **TASK-020 Prompt, review and analyst agents** — DONE · AI Workflow Engineer · 16h · deps: TASK-019 · Issue: [#49](https://github.com/dhruv0641/Dolla/issues/49) · PR: [#50](https://github.com/dhruv0641/Dolla/pull/50) · merged to develop as `f25e3d1`; CI and independent review passed

## EPIC-05: Google Flow MCP Integration

- **TASK-021 Discover actual MCP manifest** — DONE · Flow MCP Integration Engineer · 6h · deps: TASK-002 · Issue: [#52](https://github.com/dhruv0641/Dolla/issues/52) · PR: [#82](https://github.com/dhruv0641/Dolla/pull/82) · merged to develop as `36864b1`; CI and independent review passed
- **TASK-022 Capability-gated adapter interface** — DONE · Flow MCP Integration Engineer · 8h · deps: TASK-021 · Issue: [#83](https://github.com/dhruv0641/Dolla/issues/83) · PR: [#84](https://github.com/dhruv0641/Dolla/pull/84) · merged to develop as `8d429b9`; pre-merge and post-merge CI/independent review passed
- **TASK-023 Auth and account health** — DONE · Flow MCP Integration Engineer · 12h · deps: TASK-022 · Issue [#85](https://github.com/dhruv0641/Dolla/issues/85) closed by tracker PR [#112](https://github.com/dhruv0641/Dolla/pull/112) (`b13cab9`) · code PR [#86](https://github.com/dhruv0641/Dolla/pull/86) merged as `3520bed`; CI and independent review passed; Flow identity directly inspected and explicitly accepted by user
- **TASK-024 Safe submit, polling and recovery** — DONE · Flow MCP Integration Engineer · 16h · deps: TASK-023 · Issue [#113](https://github.com/dhruv0641/Dolla/issues/113) closed by tracker PR [#115](https://github.com/dhruv0641/Dolla/pull/115), merged as `0525b02`; implementation PR [#114](https://github.com/dhruv0641/Dolla/pull/114) merged to `develop` as `cd2c70f`; 262 tests, independent review, PR/post-merge checks passed; existing external job remains unknown and cannot be retried
- **TASK-025 Media retrieval and metadata** — DONE · Flow MCP Integration Engineer · 4h · deps: TASK-024 · Issue [#116](https://github.com/dhruv0641/Dolla/issues/116) closed by tracker PR [#118](https://github.com/dhruv0641/Dolla/pull/118), merged as `d5cf6c8` · implementation PR [#117](https://github.com/dhruv0641/Dolla/pull/117) merged as `89204d6`; independent review, 269 tests and required checks passed; live Flow retrieval not claimed

## EPIC-06: Credit and Account Management

- **TASK-026 Authorized account registry** — DONE · Credit and Account Engineer · 8h · deps: TASK-006, TASK-021 · Issue: [#94](https://github.com/dhruv0641/Dolla/issues/94) closed by PR [#95](https://github.com/dhruv0641/Dolla/pull/95), merged to `develop` as `dd64b96`; required checks and post-merge validation passed
- **TASK-027 Credit quote, reservation and limits** — DONE · Credit and Account Engineer · 12h · deps: TASK-026 · Issue [#97](https://github.com/dhruv0641/Dolla/issues/97) closed by PR [#99](https://github.com/dhruv0641/Dolla/pull/99), merged as `73eb39f`; PR and post-merge checks and independent review passed
- **TASK-028 Observed credit ledger and reconciliation** — DONE · Credit and Account Engineer · 16h · deps: TASK-027 · Issue [#101](https://github.com/dhruv0641/Dolla/issues/101) closed by PR [#102](https://github.com/dhruv0641/Dolla/pull/102), merged to `develop` as `707310f`; 227 tests, independent review, PR and post-merge checks passed
- **TASK-029 Concurrency, pause and reset tracking** — DONE · Credit and Account Engineer · 4h · deps: TASK-028 · Issue [#104](https://github.com/dhruv0641/Dolla/issues/104) closed by PR [#105](https://github.com/dhruv0641/Dolla/pull/105), merged to `develop` as `d91e400`; 229 tests, independent review, PR and post-merge checks passed
- **TASK-030 Unknown-spend alarms and fail-closed controls** — DONE · Credit and Account Engineer · 6h · deps: TASK-029 · Issue [#107](https://github.com/dhruv0641/Dolla/issues/107) · Branch `feature/TASK-030-unknown-spend-alarms-fail-closed-controls` · PR [#108](https://github.com/dhruv0641/Dolla/pull/108) merged to `develop` as `2b621be`; 241 tests, independent review, PR checks and post-merge validation passed; issue #107 closed

## EPIC-07: Scene and Media Management

- **TASK-031 Versioned storyboard and scene timeline** — DONE · Media Pipeline Engineer · 12h · deps: TASK-006, TASK-019, TASK-025, TASK-030 · Issue [#119](https://github.com/dhruv0641/Dolla/issues/119) closed by tracker PR [#121](https://github.com/dhruv0641/Dolla/pull/121); implementation PR [#120](https://github.com/dhruv0641/Dolla/pull/120) merged as `6b6aa07`; 281 tests and required CI passed; independent review passed; live PostgreSQL unverified
- **TASK-032 Asset storage, hashes and lineage** — DONE · Media Pipeline Engineer · 16h · deps: TASK-031 · Issue [#135](https://github.com/dhruv0641/Dolla/issues/135) · Issue [#122](https://github.com/dhruv0641/Dolla/issues/122) closed by tracker PR [#124](https://github.com/dhruv0641/Dolla/pull/124); implementation PR [#123](https://github.com/dhruv0641/Dolla/pull/123) merged as `1454b2e`; 297 tests, independent review and required CI passed; live PostgreSQL unverified
- **TASK-033 Scene jobs and bounded retries** — DONE · Media Pipeline Engineer · 4h · deps: TASK-032 · Issue [#125](https://github.com/dhruv0641/Dolla/issues/125) · implementation PR [#126](https://github.com/dhruv0641/Dolla/pull/126) merged to `develop` as `c034303`; tracker PR [#127](https://github.com/dhruv0641/Dolla/pull/127) merged as `ab9f400` and closed issue #125; 307 tests, independent review, required checks and post-merge validations passed
- **TASK-034 Media probing and validation** — DONE · Media Pipeline Engineer · 6h · deps: TASK-033 · Issue [#129](https://github.com/dhruv0641/Dolla/issues/129), implementation PR [#130](https://github.com/dhruv0641/Dolla/pull/130); tracker closeout [#131](https://github.com/dhruv0641/Dolla/pull/131)
- **TASK-035 Asset search and retention** — DONE · Media Pipeline Engineer · 8h · deps: TASK-034 · Issue [#132](https://github.com/dhruv0641/Dolla/issues/132); PR [#133](https://github.com/dhruv0641/Dolla/pull/133); tracker PR [#134](https://github.com/dhruv0641/Dolla/pull/134)

## EPIC-08: Local Audio and Voiceover

- **TASK-036 Evaluate local TTS** — DONE · Media Pipeline Engineer · 16h · deps: TASK-031 · Issue [#135](https://github.com/dhruv0641/Dolla/issues/135) closed · implementation PR [#136](https://github.com/dhruv0641/Dolla/pull/136) merged as `1b79dd5`; tracker closeout PR [#137](https://github.com/dhruv0641/Dolla/pull/137) merged as `586f170`; 330 tests, independent review and post-merge validation passed
- **TASK-037 Voice profiles and synthesis** — DONE · Media Pipeline Engineer · 4h · deps: TASK-036 · Issue [#138](https://github.com/dhruv0641/Dolla/issues/138) · implementation PR [#139](https://github.com/dhruv0641/Dolla/pull/139) merged as `22ea8e4`; 11 focused and 331 non-migration backend tests, independent review and required/post-merge CI passed
- **TASK-038 Timing, normalization and zero-second narration** — DONE · Media Pipeline Engineer · 6h · deps: TASK-037 · Issue [#141](https://github.com/dhruv0641/Dolla/issues/141) · implementation PR [#142](https://github.com/dhruv0641/Dolla/pull/142) merged as `0aa9826`; 3 real normalization and 334 backend tests, independent review and required/post-merge CI passed
- **TASK-039 Captions and subtitle alignment** — DONE · Media Pipeline Engineer · 8h · deps: TASK-038 · Issue [#144](https://github.com/dhruv0641/Dolla/issues/144) · implementation PR [#145](https://github.com/dhruv0641/Dolla/pull/145) merged as `015abc4`; 4 focused and 338 backend tests, independent review and required/post-merge CI passed
- **TASK-040 Audio preview and management** — DONE · Media Pipeline Engineer · 12h · deps: TASK-039 · Issue [#147](https://github.com/dhruv0641/Dolla/issues/147) · implementation PR [#148](https://github.com/dhruv0641/Dolla/pull/148) merged as `f8a4456`; 23 focused and 342 backend tests, independent review and required/post-merge CI passed

## EPIC-09: Automated Video Editing

- **TASK-041 FFmpeg render worker and manifests** — DONE · Media Pipeline Engineer · 4h · deps: TASK-032, TASK-036 · Issue [#150](https://github.com/dhruv0641/Dolla/issues/150) · implementation PR [#151](https://github.com/dhruv0641/Dolla/pull/151) merged as `f23b176`; 5 focused, 21 regression and 347 backend tests, independent review and required/post-merge CI passed
- **TASK-042 Normalize codecs, fps and aspect ratios** — DONE · Media Pipeline Engineer · 6h · deps: TASK-041 · Issue [#153](https://github.com/dhruv0641/Dolla/issues/153) · implementation PR [#154](https://github.com/dhruv0641/Dolla/pull/154) merged as `fb9b840`; 6 focused, 19 regression and 348 backend tests, independent review and required/post-merge CI passed
- **TASK-043 Compose scenes, audio and subtitles** — DONE · Media Pipeline Engineer · 8h · deps: TASK-042 · Issue [#156](https://github.com/dhruv0641/Dolla/issues/156) · implementation PR [#157](https://github.com/dhruv0641/Dolla/pull/157) merged as `4855be4`; 4 focused, 17 regression and 352 backend tests, independent review and required/post-merge CI passed
- **TASK-044 Platform export variants** — IN_PROGRESS · Media Pipeline Engineer · 12h · deps: TASK-043 · Issue [#159](https://github.com/dhruv0641/Dolla/issues/159) · Branch `feature/TASK-044-platform-export-variants`
- **TASK-045 Render versions and artifacts** — BACKLOG · Media Pipeline Engineer · 16h · deps: TASK-044

## EPIC-10: Video Quality Assurance

- **TASK-046 Deterministic integrity checks** — BACKLOG · QA and Security Engineer · 6h · deps: TASK-034, TASK-045
- **TASK-047 Visual and audio evaluation** — BACKLOG · QA and Security Engineer · 8h · deps: TASK-046
- **TASK-048 Policy, factuality and copyright signals** — BACKLOG · QA and Security Engineer · 12h · deps: TASK-047
- **TASK-049 Scene retry limits and spend gate** — BACKLOG · QA and Security Engineer · 16h · deps: TASK-048
- **TASK-050 Human review and approvals** — BACKLOG · QA and Security Engineer · 4h · deps: TASK-049

## EPIC-11: Frontend Dashboard

- **TASK-051 Responsive design system and shell** — DONE · Frontend Engineer · 8h · deps: TASK-003, TASK-012 · Issue: [#55](https://github.com/dhruv0641/Dolla/issues/55) · PR: [#56](https://github.com/dhruv0641/Dolla/pull/56) · merged to develop as `2f74e90`; CI passed; reviewer passed
- **TASK-052 Live executive command center** — DONE · Frontend Engineer · 12h · deps: TASK-051 · Issue: [#58](https://github.com/dhruv0641/Dolla/issues/58) · PR: [#59](https://github.com/dhruv0641/Dolla/pull/59) · merged to develop as `a8ce250`; CI passed; reviewer passed
- **TASK-053 Production board, scenes and assets** — DONE · Frontend Engineer · 16h · deps: TASK-052 · Issue: [#61](https://github.com/dhruv0641/Dolla/issues/61) · PR: [#62](https://github.com/dhruv0641/Dolla/pull/62) · merged to develop as `e970369`; CI passed; reviewer passed
- **TASK-054 Flow control, ledger and jobs** — DONE · Frontend Engineer · 4h · deps: TASK-021, TASK-022, TASK-053 · Issue: [#64](https://github.com/dhruv0641/Dolla/issues/64) · PR: [#87](https://github.com/dhruv0641/Dolla/pull/87) merged to `develop` as `6476cbd`; CI/review passed; no live Flow data claimed
- **TASK-055 QA, voice, calendar and publishing screens** — DONE · Frontend Engineer · 6h · deps: TASK-054 · Issue: [#88](https://github.com/dhruv0641/Dolla/issues/88) · PR: [#89](https://github.com/dhruv0641/Dolla/pull/89) merged to `develop` as `fd134c7`; CI, independent review and post-merge validation passed
- **TASK-056 Agent, analytics, community and settings screens** — DONE · Frontend Engineer · 8h · deps: TASK-055 · Issue: [#91](https://github.com/dhruv0641/Dolla/issues/91) · PR: [#92](https://github.com/dhruv0641/Dolla/pull/92) merged to `develop` as `a2d8d85`; required checks, post-merge validation and independent review passed

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

- **TASK-072 Threat model, access and audit** — DONE · DevOps Engineer · 6h · deps: none · Issue: [#66](https://github.com/dhruv0641/Dolla/issues/66) · PR: [#67](https://github.com/dhruv0641/Dolla/pull/67) · merged to develop as `c070ea7`; CI passed; reviewer passed
- **TASK-073 Logs, metrics, traces and alerts** — DONE · DevOps Engineer · 8h · deps: TASK-072 · Issue: [#69](https://github.com/dhruv0641/Dolla/issues/69) · PR: [#70](https://github.com/dhruv0641/Dolla/pull/70) · merged to develop as `2a7faa8`; CI passed; reviewer passed
- **TASK-074 Docker Compose and environment profiles** — DONE · DevOps Engineer · 12h · deps: TASK-073 · Issue: [#72](https://github.com/dhruv0641/Dolla/issues/72) · PR: [#73](https://github.com/dhruv0641/Dolla/pull/73) · merged to develop as `e789e14`; CI passed; reviewer passed
- **TASK-075 Encrypted backups and runbooks** — DONE · DevOps Engineer · 16h · deps: TASK-074 · Issue: [#75](https://github.com/dhruv0641/Dolla/issues/75) · PR: [#76](https://github.com/dhruv0641/Dolla/pull/76) · Commit: `b1b9e8d`
- **TASK-076 Security and release gates** — DONE · DevOps Engineer · 4h · deps: TASK-075 · Issue: [#78](https://github.com/dhruv0641/Dolla/issues/78) · PR: [#79](https://github.com/dhruv0641/Dolla/pull/79) · Commit: `996f7ea`

## Totals

- Epics: 15
- Tasks: 76
- Estimated effort: 698 engineering hours
- DONE: 47 (TASK-001 through TASK-025, TASK-026 through TASK-036, TASK-051 through TASK-056, and TASK-072 through TASK-076).
- TESTING: 0.
- IN_PROGRESS: 0.
- IN_REVIEW: 0.
- READY: 0.
- BLOCKED: 0.
- BACKLOG: 29.

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
- TASK-013 merged to `develop` as `527586ca034343e4ee72f5a36ea120745dc08218`; issue #29 closed, CI and independent review passed.
- TASK-014 merged to `develop` as `d8baa38b904ef98a6d955d179ff176414823708c`; issue #31 closed, CI and independent review passed.
- TASK-015 issue [#33](https://github.com/dhruv0641/Dolla/issues/33), implementation PR [#34](https://github.com/dhruv0641/Dolla/pull/34), and completion record PR [#35](https://github.com/dhruv0641/Dolla/pull/35) merged to `develop`; issue closed, checks and independent review passed.
- TASK-016 issue [#37](https://github.com/dhruv0641/Dolla/issues/37) and PR [#38](https://github.com/dhruv0641/Dolla/pull/38) merged to `develop` as `cf90289`; checks and independent review passed.
- TASK-017 issue [#40](https://github.com/dhruv0641/Dolla/issues/40) and PR [#41](https://github.com/dhruv0641/Dolla/pull/41) merged to `develop` as `1052800`; checks and independent review passed.
- TASK-008 PR: [#17](https://github.com/dhruv0641/Dolla/pull/17), targeting `develop`; CI pending.
- Integration branch: [`develop`](https://github.com/dhruv0641/Dolla/tree/develop) at seed commit `1da41e47410228b9fe3bdc87dba26a1931fb9d2a`.
- Goal issue: [#1](https://github.com/dhruv0641/Dolla/issues/1). Task-linked issues and PRs are recorded here and in each task specification as created and verified.

- TASK-018 issue [#43](https://github.com/dhruv0641/Dolla/issues/43) and PR [#44](https://github.com/dhruv0641/Dolla/pull/44) merged to `develop` as `ef36c14`; checks and independent review passed.

- TASK-019 issue [#46](https://github.com/dhruv0641/Dolla/issues/46) opened; branch `feature/TASK-019-script-and-storyboard-generation` targets `develop`.
- TASK-019 implementation commit `6ecc43a` is in PR [#47](https://github.com/dhruv0641/Dolla/pull/47) to `develop`; independent review passed and CI is pending.

- TASK-019 issue [#46](https://github.com/dhruv0641/Dolla/issues/46) and PR [#47](https://github.com/dhruv0641/Dolla/pull/47) merged to `develop` as `10fa7c5`; checks and independent review passed.
- TASK-020 issue [#49](https://github.com/dhruv0641/Dolla/issues/49) opened; branch `feature/TASK-020-prompt-review-and-analyst-agents` targets `develop`.
- TASK-020 implementation commit `1fbbffd` is in PR [#50](https://github.com/dhruv0641/Dolla/pull/50) to `develop`; independent review passed and CI is pending.

- TASK-020 issue [#49](https://github.com/dhruv0641/Dolla/issues/49) and PR [#50](https://github.com/dhruv0641/Dolla/pull/50) merged to `develop` as `f25e3d1`; checks and independent review passed.

- TASK-021 issue [#52](https://github.com/dhruv0641/Dolla/issues/52) closed by PR [#82](https://github.com/dhruv0641/Dolla/pull/82), merged to develop as `36864b1`; live manifest discovery, current API fail-closed tests, CI and independent review passed. Account verification is assigned to TASK-023; old job reconciliation to TASK-024.
- TASK-024 issue [#113](https://github.com/dhruv0641/Dolla/issues/113) closed by PR [#115](https://github.com/dhruv0641/Dolla/pull/115), merged as `0525b02`; TASK-025 issue [#116](https://github.com/dhruv0641/Dolla/issues/116) closed by tracker PR [#118](https://github.com/dhruv0641/Dolla/pull/118), merged as `d5cf6c8`; TASK-031 issue [#119](https://github.com/dhruv0641/Dolla/issues/119) closed by tracker PR [#121](https://github.com/dhruv0641/Dolla/pull/121); TASK-032 issue [#122](https://github.com/dhruv0641/Dolla/issues/122) closed by tracker PR [#124](https://github.com/dhruv0641/Dolla/pull/124); TASK-033 issue [#125](https://github.com/dhruv0641/Dolla/issues/125) is open and its branch is active.
- TASK-022 issue [#83](https://github.com/dhruv0641/Dolla/issues/83) opened; capability-gated Flow MCP adapter interface is now in progress on `feature/TASK-022-capability-gated-adapter-interface`.
- TASK-022 implementation commit `62b9a2b` and tracker commit `4600339` were pushed to PR [#84](https://github.com/dhruv0641/Dolla/pull/84); local suite 170 passed and independent technical review passed.
- TASK-022 PR [#84](https://github.com/dhruv0641/Dolla/pull/84) merged to `develop` as `8d429b9`; required PR and post-merge CI passed; issue #83 closed.
- TASK-023 issue [#85](https://github.com/dhruv0641/Dolla/issues/85) opened after TASK-022 merge; app-side account health gate started on `feature/TASK-023-auth-and-account-health`. Live email identity remains unverified.
- TASK-021 live discovery checkpoint PR [#82](https://github.com/dhruv0641/Dolla/pull/82) is open as draft from `feature/TASK-021-live-flow-capability-discovery`; project-plan CI passes on the branch.
- TASK-051 issue [#55](https://github.com/dhruv0641/Dolla/issues/55) opened; selected as the next unblocked P1 task because dependencies TASK-003 and TASK-012 are done. Branch `feature/TASK-051-responsive-design-system-and-shell` targets `develop`.

- TASK-021 discovery record PR [#53](https://github.com/dhruv0641/Dolla/pull/53) merged to `develop` as `a964583`; issue #52 remains open. The prior absence finding was superseded by live MCP tool exposure on 2026-11-18; account and app-boundary verification continue.

- TASK-051 issue [#55](https://github.com/dhruv0641/Dolla/issues/55) closed by implementation PR [#56](https://github.com/dhruv0641/Dolla/pull/56), merged to develop as 2f74e90; both CI checks and independent review passed. Visual browser preview was unavailable; backend/Flow data remains unconnected.

- TASK-052 issue [#58](https://github.com/dhruv0641/Dolla/issues/58) opened; implementation started on `feature/TASK-052-live-executive-command-center` after TASK-051 completion.

- TASK-052 issue [#58](https://github.com/dhruv0641/Dolla/issues/58) closed by PR [#59](https://github.com/dhruv0641/Dolla/pull/59), merged to develop as a8ce250; CI and independent review passed. Live upstream connectivity, visual preview, and authenticated operational data remain unverified.

- TASK-053 issue [#61](https://github.com/dhruv0641/Dolla/issues/61) opened; started the next unblocked P1 task on `feature/TASK-053-production-board-scenes-and-assets`. Existing APIs do not expose scenes/assets and require bearer authentication for content; UI will preserve unavailable states.

- TASK-053 issue [#61](https://github.com/dhruv0641/Dolla/issues/61) closed by PR [#62](https://github.com/dhruv0641/Dolla/pull/62), merged to develop as 970369; both CI checks and independent review passed. Scene/assets APIs and authenticated content data remain unavailable, so corresponding panels show no loaded records.

- TASK-054 issue [#64](https://github.com/dhruv0641/Dolla/issues/64) opened; marked blocked on missing authorized Flow MCP server/manifest (TASK-021). No simulated generation, jobs, balances, or alternate provider controls will be presented.
- TASK-054 issue [#64](https://github.com/dhruv0641/Dolla/issues/64) closed by PR [#87](https://github.com/dhruv0641/Dolla/pull/87), merged to `develop` as `6476cbd`; PR and post-merge plan CI passed, independent review found no blocker. The merge satisfies TASK-055's dependency.
- TASK-055 issue [#88](https://github.com/dhruv0641/Dolla/issues/88) opened; selected as the next dependency-ready P1 task. Started `feature/TASK-055-qa-voice-calendar-and-publishing` against `develop`; QA, voice, publishing and calendar panels keep external data/actions gated. Draft PR [#89](https://github.com/dhruv0641/Dolla/pull/89) opened against `develop`; CI pending.
- TASK-055 PR [#89](https://github.com/dhruv0641/Dolla/pull/89) merged to `develop` as `fd134c7`; both PR checks, independent review and post-merge plan validation passed. Issue #88 closed. Documentation and completion records are in follow-up PR [#90](https://github.com/dhruv0641/Dolla/pull/90); its CI is pending.
- TASK-055 documentation closeout PR [#90](https://github.com/dhruv0641/Dolla/pull/90) merged to `develop` as `b6bd00d`; independent review and post-merge plan validation passed. TASK-056 issue [#91](https://github.com/dhruv0641/Dolla/issues/91) opened and its only dependency, TASK-055, is now DONE.
- TASK-056 selected as the next dependency-ready P1 task; branch `feature/TASK-056-agent-analytics-community-settings` started from `develop`.
- TASK-056 implementation committed as `be512f5` and pushed; draft PR [#92](https://github.com/dhruv0641/Dolla/pull/92) targets `develop`. Local checks and independent review pass; required GitHub checks are running.
- TASK-056 PR [#92](https://github.com/dhruv0641/Dolla/pull/92) merged to `develop` as `a2d8d85`; both PR checks and post-merge project-plan validation passed, and issue #91 closed. TASK-056 is DONE; no live operations data is claimed.
- TASK-026 selected as the next dependency-ready P0 task because TASK-006 and TASK-021 are DONE. Issue [#94](https://github.com/dhruv0641/Dolla/issues/94) opened; branch `feature/TASK-026-authorized-account-registry` started from `develop`.
- TASK-026 implementation and independent review pass locally; issue #94 is in review preparation. Owner-scoped aliases, syntax-only secret references, unverified/paused defaults, and no-unpause behavior are documented. Full suite: 193 passed; migration parse test passed; live PostgreSQL/Flow integration unverified.
- TASK-026 implementation committed as `b60dce1`, pushed, and opened as draft PR [#95](https://github.com/dhruv0641/Dolla/pull/95) to `develop`; local tests and independent review pass, GitHub checks are running.
- TASK-026 PR [#95](https://github.com/dhruv0641/Dolla/pull/95) merged to `develop` as `dd64b96`; PR CI and post-merge plan validation passed, issue #94 closed. Task DONE; no live PostgreSQL or Flow provider integration is claimed.
- TASK-026 tracker closeout PR [#96](https://github.com/dhruv0641/Dolla/pull/96) merged to `develop` as `eefbbfc`; checks passed. TASK-027 selected as the next dependency-ready P0 task; issue [#97](https://github.com/dhruv0641/Dolla/issues/97) opened and branch `feature/TASK-027-credit-quote-reservation-limits` started.
- TASK-027 implementation PR [#98](https://github.com/dhruv0641/Dolla/pull/98) merged to `develop` as `8c4849e`. Final review reopened issue #97 to add owner preflight before provider calls; correction PR [#99](https://github.com/dhruv0641/Dolla/pull/99) merged as `73eb39f` after independent review and required/post-merge checks, closing issue #97. TASK-027 is DONE; TASK-028 is READY because its sole dependency is satisfied.

- TASK-072 issue [#66](https://github.com/dhruv0641/Dolla/issues/66) opened; selected as the next eligible P2 task because no P1 tasks have fully satisfied dependencies while TASK-021/054 remain blocked.

- TASK-072 issue [#66](https://github.com/dhruv0641/Dolla/issues/66) closed by PR [#67](https://github.com/dhruv0641/Dolla/pull/67), merged to develop as c070ea7; CI and independent review passed. Threat model is evidence-based and does not claim production security certification.

- TASK-073 issue [#69](https://github.com/dhruv0641/Dolla/issues/69) opened after TASK-072 completion; P2 observability implementation started on eature/TASK-073-observability.

- TASK-073 issue [#69](https://github.com/dhruv0641/Dolla/issues/69) closed by PR [#70](https://github.com/dhruv0641/Dolla/pull/70), merged to develop as 2a7faa8; both CI checks, 152 tests and independent review passed. External log/metrics collection, distributed tracing and alert delivery remain unconfigured.

- TASK-074 issue [#72](https://github.com/dhruv0641/Dolla/issues/72) opened after TASK-073; local application-shell container work started. PostgreSQL/auth are not wired and will not be represented as ready.

- TASK-074 issue [#72](https://github.com/dhruv0641/Dolla/issues/72) closed by PR [#73](https://github.com/dhruv0641/Dolla/pull/73), merged to develop as 789e14; CI and independent review passed. Compose config validates, but Docker Engine was unavailable for image/runtime verification.

- TASK-075 issue [#75](https://github.com/dhruv0641/Dolla/issues/75) closed via PR [#76](https://github.com/dhruv0641/Dolla/pull/76), merged to `develop` as `b1b9e8d` after CI and independent review. All 157 tests pass; live PostgreSQL/age recovery remains unverified.
- TASK-076 issue [#78](https://github.com/dhruv0641/Dolla/issues/78) closed via PR [#79](https://github.com/dhruv0641/Dolla/pull/79), merged to `develop` as `996f7ea` after CI and independent review. Python audit and `npm audit` passed; production release readiness remains environment-specific and unverified.
