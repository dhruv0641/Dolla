# FLOW AI CONTENT OS — Master Project Story

## Vision and mission
A self-hosted, auditable AI content production system that turns evidence-backed ideas into reviewed, multi-scene videos and independently verified posts for YouTube, Instagram and Facebook. Google Flow through an authorized MCP server is the sole generative video engine.

## Business objectives and users
Reduce production coordination effort, improve repeatable content quality, and learn from channel-specific outcomes. Users: owner/content director, editor/producer, reviewer, analyst and publisher/operator.

## Product requirements and journeys
Research and strategy → idea approval → script/storyboard → scene-level Flow jobs → local narration/subtitles → FFmpeg assembly → deterministic and assisted QC → human approval → platform-specific schedule/publish → remote verification → analytics and community insights → evidence-backed next ideas. Dashboard areas: command center, calendar, research board, production pipeline, Flow control, QA/voice studio, publishing, analytics, community, agent activity and settings.

## Content lifecycle
Represent canonical content, scenes, generation attempts, assets, QA, render versions, reviews and per-platform publications independently. Persist events transactionally through an outbox; workers lease jobs, recover expired leases and use idempotent handlers. Retry only affected scenes within bounded limits.

## AI agent responsibilities
Project Director owns scope and goal completion; Solution Architect owns boundaries and decisions; Task Planning Agent manages dependencies; Backend Engineer owns APIs/persistence; Flow MCP Integration Engineer owns verified adapter behavior; AI Workflow Engineer owns research/content agents; Media Pipeline Engineer owns TTS/FFmpeg; Frontend Engineer owns dashboard; Publishing Integration Engineer owns official APIs; QA and Security Engineer owns checks/gates; DevOps Engineer owns deployment/observability; Technical Reviewer independently reviews evidence. Roles are virtual ownership assignments, not claims that native agents are provisioned.

## Flow MCP architecture
Use a normalized adapter and discover capabilities against the actual connected server. The JSON is a proposed interface, not actual tool names or proof of support. On 2026-11-18 the Codex runtime exposed a Google Flow MCP tool manifest and a connected/logged-in Flow browser. The Flow account details identity was directly inspected and the user explicitly accepted it; exact address is omitted from repository docs. An older image job remains in `sent` state with unknown outcome. The application repository still has no configured live Flow transport. Treat remote content as untrusted. Fail closed if auth, capability, job state or credit consumption is uncertain; never rotate accounts to bypass limits. Store secret references only. See `docs/MCP_CAPABILITY_MATRIX.md`.

## Video and audio architecture
Generate scene prompts from versioned script/storyboard and a visual bible; track each Flow attempt and credit entry. Store media with hashes and metadata. Use local TTS and FFmpeg; narration may begin at 0:00. Normalize heterogeneous media before concat; preserve render manifests and versions. Validate duration, codecs, dimensions, aspect ratio, decode, captions and audio. Initial policy caps regeneration at two attempts per scene.

## Publishing and analytics
Use official YouTube Data API and authorized Instagram professional/Facebook Page publishing paths. Track independent per-platform statuses, remote IDs and reconciliation. Human approval stays enabled; autonomous publishing remains off until owner authorization. Retain platform-native metric definitions, windows and missing values; derive versioned metrics and feed cautious experiments. Community replies remain reviewable drafts; no spam or fake engagement.

## Security and operations
PostgreSQL, Python/FastAPI, React/Next.js, Docker/self-hosting, FFmpeg, local TTS, Gemini for selected reasoning and local LLMs where practical. Separate Google AI Pro entitlement from Gemini API billing. Use least privilege, encrypted/OS secret storage, audit, TLS/auth for remote access, backups, rate limits, outbound restrictions and recovery runbooks.

## GitHub delivery workflow
Official repository: [dhruv0641/Dolla](https://github.com/dhruv0641/Dolla). `main` is production and protected by active GitHub ruleset [27482128](https://github.com/dhruv0641/Dolla/settings/rules/27482128); `develop` is integration, protected by ruleset [27482560](https://github.com/dhruv0641/Dolla/settings/rules/27482560). Work uses `feature/TASK-###-*`, `fix/TASK-###-*`, or `epic/EPIC-##-*` branches and PRs target `develop`. No direct main pushes, shared force-pushes, secrets in commits, or production merges without owner authorization. `docs/IMPLEMENTATION_PLAN.md` is the single chronological development log. Goal tracker: [#1](https://github.com/dhruv0641/Dolla/issues/1). 43 task specs are DONE and merged to `develop`; TASK-023 issue #85 closed through tracker PR #112 (`b13cab9`). TASK-024 implementation merged through PR #114 (`cd2c70f`) and tracker closeout merged in PR #115 (`0525b02`), closing issue #113. TASK-025 implementation merged through PR #117 (`89204d6`) and tracker closeout merged in PR #118 (`d5cf6c8`), closing issue #116. TASK-031 implementation merged through PR [#120](https://github.com/dhruv0641/Dolla/pull/120) as `6b6aa07`, tracker closeout merged through PR [#121](https://github.com/dhruv0641/Dolla/pull/121) as `9e4a34e`, closing issue #119. TASK-032 implementation merged through PR [#123](https://github.com/dhruv0641/Dolla/pull/123) as `1454b2e`, tracker closeout merged through PR [#124](https://github.com/dhruv0641/Dolla/pull/124) as `6a33cef`, closing issue #122. TASK-033 issue #125 and branch are active. TASK-055 merged via PRs [#89](https://github.com/dhruv0641/Dolla/pull/89) and [#90](https://github.com/dhruv0641/Dolla/pull/90); issue #88 closed. TASK-056 merged via PR [#92](https://github.com/dhruv0641/Dolla/pull/92) as `a2d8d85`; issue #91 closed and checks/review passed.

## Decisions and unresolved assumptions
- PostgreSQL schema is a design starting point; migration review must resolve constraints, tenant isolation/RLS, credential references, retention and event semantics.
- Runtime Flow tool manifest and schemas are documented in `docs/MCP_CAPABILITY_MATRIX.md`; the user accepted the identity directly inspected in the Flow UI (exact address omitted). Host transport/deployment identity, stale job outcome, credit balance/quote and live application adapter behavior remain unverified.
- Exact Gemini/local models, TTS, media storage, deployment host, user authentication, OAuth scopes/quotas and licensing remain for goal-specific decisions.
- Validate current external API capabilities and policies before integrations.
- External integrations remain unconfigured; code delivered so far is a backend foundation and is not evidence of live Flow or publishing capabilities.

## Milestones
P0 Flow proof; P1 single-video vertical slice; P2 production management; P3 official publishing; P4 automated schedules; P5 intelligence loop; P6 multi-account operations. See `docs/IMPLEMENTATION_PLAN.md`.

## Definition of Done
A user can inspect an approved scheduled idea, original playable Flow scenes, narration from zero, QC-approved MP4, verified per-platform publication links, reconciled per-account credit costs and analytics feeding the next schedule. Tasks require acceptance evidence, passing relevant tests, review and documentation; architecture or mocks alone never imply production readiness.

## Current implementation status
**Implementation is underway.** The plan contains 15 epics and 76 dependency-linked tasks. TASK-030 is DONE through PR [#108](https://github.com/dhruv0641/Dolla/pull/108), merged to `develop` as `2b621be`; issue #107 is closed. Its implementation holds ambiguous reservations, pauses the account, persists an owner-visible alarm and workflow event with the authenticated actor, and lists alarms through a sanitized route. The full suite (241 tests), focused alarm/migration suite (17 tests), plan validation, compileall, diff check, independent review, PR checks and post-merge validation pass. TASK-028 and TASK-029 are DONE through PRs [#102](https://github.com/dhruv0641/Dolla/pull/102) and [#105](https://github.com/dhruv0641/Dolla/pull/105), merged as `707310f` and `d91e400`. TASK-023 identity acceptance and tracker closeout are complete through PR #112 (`b13cab9`), and issue #85 is closed. TASK-024 implementation is DONE through PR #114 (`cd2c70f`) and issue #113 closed by tracker PR #115 (`0525b02`). TASK-025 is complete through PR #117 (`89204d6`) and tracker PR #118 (`d5cf6c8`), closing issue #116. TASK-031 is DONE through implementation PR #120 (`6b6aa07`) and tracker PR #121 (`9e4a34e`), closing issue #119. TASK-032 is DONE through implementation PR #123 (`1454b2e`) and tracker PR #124 (`6a33cef`), closing issue #122. 297 tests, independent review and both required implementation PR checks passed. Its service stores bounded media under a managed root, computes SHA-256, validates asset identity, and enforces owner/content/scene/job lineage. TASK-033 scene jobs and bounded retries is implemented and merged via PR #126 (`c034303`) with 307 tests, independent review, required checks and post-merge validation passing; tracker PR #127 (`ab9f400`) closed issue #125 after required and post-merge checks passed. The policy permits two regenerations after an initial attempt, while ambiguous Flow submissions stay blocked and no retries submit automatically. The user said the separately named Flow identity is acceptable if it opens; no account change or Flow operation occurred. PostgreSQL migration/locking, production volume behavior, backup/restore of assets, live retrieval and Flow generation remain unverified. The prior Flow job remains unknown and must be reconciled safely before any retry.

## Outstanding work and blockers
Remaining gates include reconciliation of the old `sent` image job, a verified app-side MCP transport, and paid generation only after explicit spend authorization and a verifiable cost ceiling. Publishing still requires eligible channels, OAuth grants and current API validation. Never paste credentials into chat.

## Next recommended goal
`GOAL: Establish the Flow MCP integration proof (P0) by discovering actual authorized server capabilities and, only after explicit spend authorization, verifying one low-cost generation, download, ffprobe inspection and credit reconciliation.`

## Progress and decision history
- 2026-11-17: Read Master Agentic Prompt, architecture blueprint, SQL reference schema, proposed MCP contract and dashboard prototype. Generated planning files only.
- 2026-11-17: Began GOAL-002. GitHub repository access verified for `dhruv0641`; active main protection ruleset 27482128 created. TASK-001 delivery in progress.
- 2026-11-18: TASK-011 merged to `develop`; TASK-012 brand/content API work began. See `docs/IMPLEMENTATION_PLAN.md` for the single timestamped development log.
- 2026-11-18: TASK-012 and its reviewer-requested API test follow-up merged to `develop`; CI and independent technical review passed. See the development log for exact evidence and remaining integration limit.
- 2026-11-18: TASK-013 typed content lifecycle state machine began; see `docs/IMPLEMENTATION_PLAN.md` for the timestamped work record.
- 2026-11-18: TASK-013 merged after safety revisions, green CI and independent review; TASK-014 idempotent workflow dispatch began.
- 2026-11-18: TASK-014 merged to `develop` after CI and independent review; TASK-015 scheduling, bounded retries and dead-letter handling began.
- 2026-11-18: TASK-015 implementation pushed on its feature branch as commit `3e46e50`; PR #34 targets `develop`. Unit tests and plan validation pass; an independent review's lease-fencing finding was fixed and re-reviewed without remaining blockers. GitHub CI pending.
- 2026-11-18: TASK-015 PR #34 merged to `develop` as `61c5ae93264db56bb257bcca8df4d92f1721274c`; both GitHub Actions checks passed, issue #33 closed, and independent review found no remaining blocker. Local PostgreSQL integration was not run.
- 2026-11-18: TASK-016 agent schemas and validation began on `feature/TASK-016-agent-schemas-and-validation`; see the unified development log for issue and verification evidence.
- 2026-11-18: TASK-016 implementation commit `c54014d` is in PR #38 to `develop`, linked to issue #37. Independent schema/security review passed; local checks are green and GitHub CI is pending.
- 2026-11-18: TASK-016 PR #38 merged to `develop` as `cf902897986fe5e04d03ae44b7da0c968c863223`; both GitHub Actions checks passed, issue #37 closed, and independent review found no remaining blocker.
- 2026-11-18: TASK-017 research with source evidence began on `feature/TASK-017-research-with-source-evidence`; issue #40 opened. The design will bind generated citations to exact retrieved source snapshots while leaving provider-specific fetch behavior injectable and unverified.
- 2026-11-18: TASK-017 commit `e8afb2b` is in PR #41 to `develop`, linked to issue #40. Source/summarizer interfaces and citation evidence checks passed independent review; all 113 Python tests pass locally. Live retrieval/model provider remains unverified.
- 2026-11-18: TASK-017 PR #41 merged to `develop` as `105280040caf0da10132e7bab1a4071fb130d11c`; both GitHub Actions checks passed, issue #40 closed, and independent review found no remaining blocker. No live source/model request was made.
- 2026-11-18: TASK-018 strategy and idea scoring began on `feature/TASK-018-strategy-and-idea-scoring`; issue #43 opened. Scoring will use explicit weighted inputs and report evidence/readiness separately from human approval.
- 2026-11-18: TASK-018 commit `f16d7da` is in PR #44 to `develop`, linked to issue #43. Deterministic weighted scoring passed independent review; local suite has 123 passing tests. A zero-source profile override is documented and tested; CI is pending.
- 2026-11-18: TASK-018 merged to `develop` as `ef36c14ee506e8c85bd41e1019ccb202b5cb3e94` through PR #44; CI passed, issue #43 closed, and independent review passed. No live model or provider integration is claimed.
- 2026-11-18: TASK-019 script and storyboard workflow began on `feature/TASK-019-script-and-storyboard-generation`; issue #46 opened. Planned boundary is injected and provider-neutral; external generation remains unverified.
- 2026-11-18: TASK-019 implementation commit `6ecc43a` is in PR #47 to `develop`, linked to issue #46. All 134 Python tests and plan validation pass; independent review passed after mutation and impossible-timing fixes. GitHub CI is pending; no live model/provider integration is claimed.
- 2026-11-18: TASK-019 merged to `develop` as `10fa7c5fa0af193b7472e53e5475115a903f05b0` through PR #47; both GitHub Actions checks passed, issue #46 closed, and independent review passed. Live model/provider integration remains unverified.
- 2026-11-18: TASK-020 prompt, review and analyst agents began on `feature/TASK-020-prompt-review-and-analyst-agents`; issue #49 opened. Scope is provider-neutral; no implicit model calls or automatic approval/publishing are intended.
- 2026-11-18: TASK-020 merged to `develop` as `f25e3d17a2bd61ab0720265eb95b00c7cc2338f9` through PR #50; both GitHub Actions checks passed, issue #49 closed, and independent review passed. No live model or analytics platform is configured.
- 2026-11-18: TASK-020 completion merged to `develop` via PR #50 as `f25e3d17a2bd61ab0720265eb95b00c7cc2338f9`; issue #49 closed.
- 2026-11-18: TASK-021 discovery checked current tool inventory, MCP resources and plugin search. No authorized Google Flow MCP server or manifest was exposed; documentation merged through PR #53 as `a964583`; task issue #52 remains open and blocked. See `docs/MCP_CAPABILITY_MATRIX.md`; all server capabilities remain unverified.
- 2026-11-18: TASK-051 responsive dashboard shell started on `feature/TASK-051-responsive-design-system-and-shell`; issue #55 opened. TASK-051 is the next unblocked P1 task (dependencies TASK-003 and TASK-012 complete); operational values remain unavailable until verified data is connected.

- 2026-11-18: TASK-051 responsive shell implementation and styles complete; typecheck/build pass. Independent review found no P1 blocker and prompted a text contrast improvement. Browser viewport rendering remains visually unverified because no browser provider was available.

- 2026-11-18: TASK-051 merged through PR #56 as 2f74e90; both CI checks passed, issue #55 closed, and independent review found no P1 blocker. No visual browser review was available; backend and Flow MCP remain unconnected.

- 2026-11-18: TASK-052 live executive command center selected as the next unblocked P1 task after TASK-051; issue #58 opened. Existing readiness APIs are unauthenticated, while content endpoints require bearer auth and no frontend token flow is configured; discovery is in progress.

- 2026-11-18: TASK-052 merged through PR #59 as a8ce250; CI and independent review passed, issue #58 closed. Missing API configuration behavior was verified; successful upstream connection, visual browser review and authenticated operational data remain unverified.

- 2026-11-18: TASK-053 production board selected as the next P1 task after TASK-052; issue #61 opened. The backend exposes no scene/asset API, and content requires bearer auth with no frontend token flow; implementation will keep unsupported records explicitly unavailable.

- 2026-11-18: TASK-053 merged through PR #62 as 970369; both CI checks and independent review passed, issue #61 closed. All content lifecycle states are represented; scene/asset endpoints and authenticated content data remain unavailable and are not simulated.

- 2026-11-18: TASK-054 Flow controls/ledger/jobs blocked on missing authorized Flow MCP server and actual manifest (TASK-021); issue #64 opened. No provider alternatives or simulated credits/jobs are used.

- 2026-11-18: TASK-072 threat model/access/audit selected as next eligible P2 after P1 backlog became blocked by TASK-021/054; issue #66 opened. Repository security controls and production gaps are being documented from source evidence.

- 2026-11-18: TASK-072 threat model and access/audit review completed with independent review; documented public health/readiness probes, token/role controls, tenant isolation and audit gaps, and release gates. No production security certification is claimed.

- 2026-11-18: TASK-072 merged via PR #67 as c070ea7; CI and independent review passed, issue #66 closed. Threat model records actual controls and production gaps, without claiming certification or penetration testing.

- 2026-11-18: TASK-073 observability selected after TASK-072; issue #69 opened. Current API has health/readiness but no request logging, process metrics, distributed tracing or configured alert delivery; implementation scope and limitations are documented.

- 2026-11-18: TASK-073 observability implementation passed independent review; 152 tests, compileall and project-plan validation pass. Request correlation is local only; external metrics, tracing and alerting are not configured.

- 2026-11-18: TASK-073 merged through PR #70 as 2a7faa8; CI, 152 tests and independent review passed, issue #69 closed. External observability collection and alerting remain unconfigured.

- 2026-11-18: TASK-074 local Compose profile selected after TASK-073; issue #72 opened. Docker and Compose are available in the environment. API/database/auth startup wiring is absent, so this work is scoped to a local shell and must not imply persistence or protected-route readiness.

- 2026-11-18: TASK-074 Compose profile passed configuration validation and independent review. Docker Engine is unavailable, so images and runtime health were not verified; the local shell is not a production deployment.

- 2026-11-18: TASK-074 merged through PR #73 as 789e14; CI and independent review passed, issue #72 closed. Compose config is valid; image build/runtime checks remain unverified because Docker Engine was unavailable.

- 2026-11-18: TASK-075 encrypted backups selected after TASK-074; issue #75 opened. Existing PostgreSQL backups were checksum-verified but plaintext; extending them with streaming age encryption and external identity paths to avoid plaintext disk files.
- 2026-11-18: TASK-075 encrypted PostgreSQL backup/restore implementation passed 157 tests, plan validation and independent security review; PR preparation in progress. Live age/PostgreSQL recovery remains unverified. See `docs/IMPLEMENTATION_PLAN.md` for the timestamped development log.
- 2026-11-18: TASK-075 merged to `develop` through PR #76 as `b1b9e8d`; GitHub checks and independent review passed, issue #75 closed. Live PostgreSQL/age recovery remains unverified. See `docs/IMPLEMENTATION_PLAN.md` for the timestamped development log.
- 2026-11-18: TASK-076 started after TASK-075; issue #78 opened. Scope is a backend dependency audit in the required CI check plus a documented release readiness checklist.
- 2026-11-18: TASK-076 audit gate and release checklist passed local validation and independent review; PR preparation in progress. The Python audit found no known vulnerabilities after updating installer tooling; `npm audit` found none. See `docs/IMPLEMENTATION_PLAN.md` for the timestamped development log.
- 2026-11-18: TASK-076 merged to `develop` via PR #79 as `996f7ea`; required CI checks and independent review passed, issue #78 closed. Release readiness checklist is documented; deployment automation and production readiness are not claimed.
- 2026-11-18: Dependency readiness sweep after TASK-076 found 28 tasks done, 2 blocked, and 46 backlog tasks with unfinished prerequisites; none are currently dependency-ready. TASK-021 and TASK-054 await an authorized Flow MCP server/manifest. GOAL-002 remains active; see `docs/IMPLEMENTATION_PLAN.md` for the timestamped record.
