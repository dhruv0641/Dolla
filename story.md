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
Official repository: [dhruv0641/Dolla](https://github.com/dhruv0641/Dolla). `main` is production and protected by active GitHub ruleset [27482128](https://github.com/dhruv0641/Dolla/settings/rules/27482128); `develop` is integration, protected by ruleset [27482560](https://github.com/dhruv0641/Dolla/settings/rules/27482560). Work uses `feature/TASK-###-*`, `fix/TASK-###-*`, or `epic/EPIC-##-*` branches and PRs target `develop`. No direct main pushes, shared force-pushes, secrets in commits, or production merges without owner authorization. `docs/IMPLEMENTATION_PLAN.md` is the single chronological development log. Goal tracker: [#1](https://github.com/dhruv0641/Dolla/issues/1). 45 task specs are DONE and merged to `develop`; TASK-023 issue #85 closed through tracker PR #112 (`b13cab9`). TASK-024 implementation merged through PR #114 (`cd2c70f`) and tracker closeout merged in PR #115 (`0525b02`), closing issue #113. TASK-025 implementation merged through PR #117 (`89204d6`) and tracker closeout merged in PR #118 (`d5cf6c8`), closing issue #116. TASK-031 implementation merged through PR [#120](https://github.com/dhruv0641/Dolla/pull/120) as `6b6aa07`, tracker closeout merged through PR [#121](https://github.com/dhruv0641/Dolla/pull/121) as `9e4a34e`, closing issue #119. TASK-032 implementation merged through PR [#123](https://github.com/dhruv0641/Dolla/pull/123) as `1454b2e`, tracker closeout merged through PR [#124](https://github.com/dhruv0641/Dolla/pull/124) as `6a33cef`, closing issue #122. TASK-033 issue #125 is closed; TASK-034 issue [#129](https://github.com/dhruv0641/Dolla/issues/129), implementation PR [#130](https://github.com/dhruv0641/Dolla/pull/130); tracker closeout [#131](https://github.com/dhruv0641/Dolla/pull/131) is implemented and merged as `b45e711`; 314 tests, independent review and required CI passed. TASK-055 merged via PRs [#89](https://github.com/dhruv0641/Dolla/pull/89) and [#90](https://github.com/dhruv0641/Dolla/pull/90); issue #88 closed. TASK-056 merged via PR [#92](https://github.com/dhruv0641/Dolla/pull/92) as `a2d8d85`; issue #91 closed and checks/review passed.

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

TASK-035 asset search and retention began on issue [#132](https://github.com/dhruv0641/Dolla/issues/132) after TASK-034 closed. Owner-scoped search and explicit retention safeguards passed 326 local tests, independent review and required PR checks; implementation PR #133 merged as `31ace2c`.

TASK-036 local TTS evaluation implementation PR #136 and tracker PR #137 are merged; issue #135 is closed and post-merge validation passed. TASK-037 started on issue #138 with dependency TASK-036 satisfied. No local TTS engine, synthesis operation or external service is claimed at kickoff.

TASK-037 implementation PR #139 merged to `develop` as `22ea8e4` after independent review and required/post-merge checks passed. Immutable owner-scoped profiles, license/consent/exact-engine gates, replay-safe claims, bounded PCM WAV validation and narration asset lineage pass 11 focused tests and 331 non-migration backend tests. No concrete local engine or live synthesis is claimed; PostgreSQL runtime remains unverified.

TASK-037 tracker PR #140 merged as `d5ac3aa`, issue #138 closed and post-merge validation passed. TASK-038 started on issue #141 to define zero-millisecond narration timing and bounded local audio normalization; no external provider or paid action is authorized.

TASK-038 implementation PR #142 merged to `develop` as `0aa9826` after independent review and required/post-merge checks passed. Managed narration begins at exactly 0 ms, shorter audio is padded to the content duration, longer audio fails closed, and bounded local FFmpeg produces verified PCM WAV lineage. Three real/local normalization tests and 334 non-migration backend tests pass. Loudness values remain filter targets rather than measured final-render conformance.

TASK-038 tracker PR #143 merged as `781315e`, issue #141 closed and post-merge validation passed. TASK-039 started on issue #144 for deterministic local caption cues and subtitle alignment; external transcription and unsupported word-level timing claims are excluded.

TASK-039 implementation PR #145 merged to `develop` as `015abc4` after independent review and required/post-merge checks passed. Approved storyboard narration is preserved in scene-bounded cues and rendered as safe, bounded UTF-8 SRT bound to the normalized zero-start narration asset. Four focused caption tests and 338 non-migration backend tests pass. Alignment remains an explicit scene estimate with word-level verification false.

TASK-039 tracker PR #146 merged as `310ce04`, issue #144 closed and post-merge validation passed. TASK-040 started on issue #147 for owner-scoped local audio inventory, bounded preview delivery and explicit management controls; raw paths, retired media and external services are excluded.

TASK-040 implementation is independently reviewed with no blocker: authenticated audio inventory omits storage details, previews verify complete managed-file integrity before returning bounded byte ranges, and operator retirement uses recoverable archived-content tombstones. Twenty-three focused API/catalog/preview tests and 342 non-migration backend tests pass. PostgreSQL, production storage races and live browser playback remain unverified.

TASK-040 implementation PR [#148](https://github.com/dhruv0641/Dolla/pull/148) passed both required checks and merged to protected `develop` as `f8a4456`; the post-merge validation also passed. The task is DONE pending this tracker-only closeout PR and issue closure. No external service, paid generation, account connection or publishing action occurred.

TASK-040 tracker PR [#149](https://github.com/dhruv0641/Dolla/pull/149) merged as `00ecd82`, its post-merge check passed and issue #147 closed. TASK-041 began on issue [#150](https://github.com/dhruv0641/Dolla/issues/150) for a local, fail-closed FFmpeg render worker and deterministic manifests; dependencies TASK-032 and TASK-036 are satisfied.

TASK-041 now has a strict single-video baseline worker that verifies complete managed-file integrity, executes a fixed bounded local FFmpeg transform without a shell, ingests an MP4 through the existing owner-scoped boundary and emits normalized/path-free persistence manifests. Five focused, 21 regression and 347 non-migration backend tests pass; independent review is pending. Multi-input composition, cross-build byte determinism and PostgreSQL orchestration are not claimed.

Caveman accepted TASK-041 final head `9f45402` with no blocker after the worker added an FFmpeg output-size ceiling and bounded `ffprobe` validation before ingest. The missing-probe regression confirms fail-closed behavior. Final-head full suite remains 347 passing; compileall, project-plan validation and diff check pass.

TASK-041 implementation PR [#151](https://github.com/dhruv0641/Dolla/pull/151) passed both required checks and merged to protected `develop` as `f23b176`; the post-merge check also passed. TASK-041 is DONE pending tracker-only closeout and issue closure, making TASK-042 dependency-ready.

TASK-041 tracker PR [#152](https://github.com/dhruv0641/Dolla/pull/152) merged as `89e5e77`, post-merge validation passed and issue #150 closed. TASK-042 began on issue [#153](https://github.com/dhruv0641/Dolla/issues/153) to add deterministic codec, frame-rate and aspect normalization on the bounded local worker foundation.

TASK-042 now binds bounded dimensions, pixel count, FPS and `COVER`/`CONTAIN` geometry into the path-free render manifest and fingerprint. The fixed filter produces H.264/AAC/yuv420p square-pixel output, and `ffprobe` verifies exact dimensions/FPS/SAR/codecs before ingest. Six focused, 19 regression and 348 backend tests pass; independent review is pending.

Caveman accepted TASK-042 final head `b267605` with no blocker after explicit scale-stage SAR normalization and an FFmpeg allocation ceiling were added. The real fixture now exercises anamorphic SAR 4:3 input; all 348 final-head non-migration tests, compileall, project-plan validation and diff check pass.

TASK-042 implementation PR [#154](https://github.com/dhruv0641/Dolla/pull/154) passed both required checks and merged to protected `develop` as `fb9b840`; post-merge validation also passed. TASK-042 is DONE pending tracker-only closeout and issue closure, making TASK-043 dependency-ready.

TASK-042 tracker PR [#155](https://github.com/dhruv0641/Dolla/pull/155) merged as `396756d`, post-merge validation passed and issue #153 closed. TASK-043 began on issue [#156](https://github.com/dhruv0641/Dolla/issues/156) for ordered scene, zero-start narration and validated subtitle composition through the local bounded worker.

TASK-043 now verifies complete owner/content/scene/storyboard/audio lineage, concatenates normalized scene intervals in manifest order, pads/trims narration from 0:00 and muxes generated SRT as selectable `mov_text`. Real local evidence confirms red→blue scene order, AAC start time zero, subtitle presence, duration and tamper rejection. Four focused, 17 regression and 352 backend tests pass; independent review is pending.

Caveman accepted TASK-043 final head `cb45c7e` with no blocker. The durable split is replayable: normalized input IDs stay in `inputs_manifest`, while the path-free `command_manifest` records roles, input positions and the complete scene timeline. Final-head 352-test suite, compileall, project-plan validation and diff check pass.

TASK-043 implementation PR [#157](https://github.com/dhruv0641/Dolla/pull/157) passed both required checks and merged to protected `develop` as `4855be4`; post-merge validation also passed. TASK-043 is DONE pending tracker-only closeout and issue closure, making TASK-044 dependency-ready.

TASK-043 tracker PR [#158](https://github.com/dhruv0641/Dolla/pull/158) merged as `652bb64`, post-merge validation passed and issue #156 closed. TASK-044 began on issue [#159](https://github.com/dhruv0641/Dolla/issues/159) for allowlisted local platform export variants; publishing, account connection and uploads are excluded.

TASK-044 now exposes only versioned YouTube Shorts, Instagram Reels and Facebook Reels local product profiles. Each verified composed source is fully hashed, transformed through fixed H.264/AAC/mov_text settings, probed before `EXPORT_VARIANT` ingest and marked `publishing_performed: false`. Real outputs for all three profiles pass; 4 focused, 20 regression and 356 backend tests pass. Independent review is pending.

Caveman accepted TASK-044 final head `824ae4c` with no blocker. The platform-profile mapping is immutable at runtime, source hash/profile settings remain path-free and fingerprinted, and all three real variants retain verified video/audio/subtitle streams without any upload or publication path. Final-head 356-test suite and project gates pass.

TASK-044 implementation PR [#160](https://github.com/dhruv0641/Dolla/pull/160) passed both required checks and merged to protected `develop` as `49e5a4a`; post-merge validation also passed. TASK-044 is DONE pending tracker-only closeout and issue closure, making TASK-045 dependency-ready.

TASK-044 tracker PR [#161](https://github.com/dhruv0641/Dolla/pull/161) merged as `1109877`, post-merge validation passed and issue #159 closed. TASK-045 began on issue [#162](https://github.com/dhruv0641/Dolla/issues/162) for durable owner-scoped render versions, manifests, state transitions and final/export artifact references.

TASK-045 implementation now persists owner-scoped render versions with strict normalized manifests, bounded worker leases and retries, expired-lease recovery, safe failure codes, and database-enforced active same-content final/export artifact lineage. Ten focused tests, 366 non-parser regression tests, compilation, diff hygiene and the project validator pass. The local migration parser is unavailable because Windows Application Control blocks its native DLL, and no live PostgreSQL endpoint is configured; those integration checks remain explicitly unverified.

Independent Caveman review found no blocker on TASK-045 implementation commit `2a97886`; the reviewer reran 10 focused tests and the project validator and confirmed ownership, concurrency, recovery, idempotency and artifact-lineage invariants. Production worker integration and live PostgreSQL migration/locking behavior remain unverified boundaries, not completion claims.

TASK-045 implementation PR [#163](https://github.com/dhruv0641/Dolla/pull/163) passed both required checks on reviewed head `f6f8564`, was marked ready, and merged only to protected `develop` as `e29ac5c`; post-merge validation passed. TASK-045 is DONE pending tracker-only PR and issue closure. With TASK-034 and TASK-045 complete, TASK-046 deterministic integrity checks is dependency-ready.

TASK-045 tracker PR [#164](https://github.com/dhruv0641/Dolla/pull/164) merged as `586a5de`, post-merge validation passed and issue #162 closed. Head Man selected TASK-046 for QA and Security ownership after confirming TASK-034 and TASK-045 are DONE; issue [#165](https://github.com/dhruv0641/Dolla/issues/165) and branch `feature/TASK-046-deterministic-integrity-checks` now scope bounded deterministic local-media checks with typed findings and no external actions.

TASK-046 now evaluates immutable final/export bytes against bound fingerprints and profiles, producing stable PASS/FAIL evidence for hash, decode, container, streams/codecs, H.264 profile, `yuv420p`, dimensions, FPS and duration. Owner-scoped `integrity-v1` reports are immutable and replay-safe in PostgreSQL. Eighteen focused tests, 38 combined regressions, 377 application tests and 13 migration tests pass; compileall, diff hygiene and the project validator pass. Live PostgreSQL trigger/lock execution remains unverified.

Independent Caveman review found no blocker on TASK-046 implementation commit `f770788`; 18 focused tests, 13 migration tests and the project validator independently passed. The review confirmed bounded/sanitized probe evidence, deterministic findings/fingerprint, owner isolation, partial uniqueness and immutable exact replay. Subtitle presence/codec is structural rather than decode-tested, and production PostgreSQL/media-volume behavior remains unverified.

TASK-046 implementation PR [#166](https://github.com/dhruv0641/Dolla/pull/166) passed both required checks on reviewed head `bc88281`, was marked ready, and merged only to protected `develop` as `1fed3c8`; post-merge validation passed. TASK-046 is DONE pending tracker-only PR and issue closure, making TASK-047 visual and audio evaluation dependency-ready.

TASK-046 tracker PR [#167](https://github.com/dhruv0641/Dolla/pull/167) merged as `a8e3d81`, post-merge validation passed and issue #165 closed. Head Man selected TASK-047 for QA and Security ownership, opened issue [#168](https://github.com/dhruv0641/Dolla/issues/168), and created `feature/TASK-047-visual-audio-evaluation`. Scope is bounded local black/freeze/silence/peak/loudness evidence on top of passing integrity, with semantic and subjective judgments explicitly unavailable rather than fabricated.

TASK-047 now derives stable PASS/FAIL/NEEDS_HUMAN visual/audio evidence from verified private media snapshots and exact passing integrity evidence. It measures black, freeze, silence, integrated loudness and true peak with bounded fixed FFmpeg filters, persists immutable owner-scoped `av-v1` reports, and explicitly leaves semantic visual quality, speech intelligibility and mix preference unevaluated. Twelve task-specific tests, 34 focused regressions and the 404-test full suite pass; every migration parses, and compileall, diff hygiene and the dependency validator pass. Live PostgreSQL execution, production threshold calibration, diverse production media and human subjective review remain unverified. Exact-commit independent review is next.

Independent Caveman review found no blocker on TASK-047 implementation commit `3be9d7c`. The reviewer confirmed owner/lineage isolation, verified-snapshot race defenses, fixed bounded local analysis, finite and consistent measurements, canonical decisions and fingerprints, exact passing-integrity binding, immutable replay-safe persistence and non-AV report preservation. Twenty AV/probe tests, 13 migration/parser tests and the project validator independently pass. Live PostgreSQL behavior, production media diversity/calibration, human subjective judgments and FFmpeg descendant-process containment remain residual boundaries.

TASK-047 implementation PR [#169](https://github.com/dhruv0641/Dolla/pull/169) passed both required checks on reviewed head `6ae5c08`, was marked ready, and merged only to protected `develop` as `d76343c`; post-merge validation passed. TASK-047 is DONE pending tracker/issue closeout, and TASK-048 policy, factuality and copyright signals is dependency-ready.

TASK-047 tracker PR [#170](https://github.com/dhruv0641/Dolla/pull/170) merged as `89c58ba`, post-merge validation passed and issue #168 closed. Head Man selected TASK-048 after confirming TASK-047 is DONE, opened issue [#171](https://github.com/dhruv0641/Dolla/issues/171), and created `feature/TASK-048-policy-factuality-copyright-signals`. Scope is evidence-backed typed signals that fail closed when evidence or authority is unavailable; it will not invent legal, factuality or platform-policy determinations.

TASK-048 now derives fixed policy, factuality and copyright signals from validated review evidence only after exact PASS AV evidence. It distinguishes no automated flag, flagged and unavailable states; binds the assessment, source-snapshot digests, versions, rights references and upstream evidence in an immutable owner-scoped `signals-v1` report; and retains required human approval even on automated PASS. Fourteen task-specific tests, 39 focused regressions and the 419-test full suite pass; all migrations parse, and compilation, diff hygiene and dependency validation pass. No live provider, legal conclusion, rights authenticity or PostgreSQL runtime behavior is claimed. Exact correction-commit independent review is next.

Initial Caveman review of TASK-048 commit `6eb2454` found two blockers: review results lacked an origin-context fingerprint and migration 0015 could accept PASS while copyright authority was unavailable. The correction now binds the review result at the source workflow to the exact raw-text-free context fingerprint, rejects cross-context reuse, and makes database state/authority/findings/disposition/severity/order mutually consistent. Fourteen task-specific, 39 focused and 419 full-suite tests pass after the correction; exact correction-commit re-review is pending.

Re-review of TASK-048 correction commit `f429d94` confirmed both original blockers closed and found one final strict-model mismatch between nested and top-level context fingerprints. The report model now rejects that contradictory provenance envelope directly, with a tamper regression. Fifteen task-specific, 40 focused and 420 full-suite tests pass; final exact-head re-review is pending.
