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
Use a normalized adapter and discover capabilities against the actual connected server. The JSON is a proposed interface, not actual tool names or proof of support. Treat remote content as untrusted. Fail closed if auth, capability, job state or credit consumption is uncertain; never rotate accounts to bypass limits. Store secret references only.

## Video and audio architecture
Generate scene prompts from versioned script/storyboard and a visual bible; track each Flow attempt and credit entry. Store media with hashes and metadata. Use local TTS and FFmpeg; narration may begin at 0:00. Normalize heterogeneous media before concat; preserve render manifests and versions. Validate duration, codecs, dimensions, aspect ratio, decode, captions and audio. Initial policy caps regeneration at two attempts per scene.

## Publishing and analytics
Use official YouTube Data API and authorized Instagram professional/Facebook Page publishing paths. Track independent per-platform statuses, remote IDs and reconciliation. Human approval stays enabled; autonomous publishing remains off until owner authorization. Retain platform-native metric definitions, windows and missing values; derive versioned metrics and feed cautious experiments. Community replies remain reviewable drafts; no spam or fake engagement.

## Security and operations
PostgreSQL, Python/FastAPI, React/Next.js, Docker/self-hosting, FFmpeg, local TTS, Gemini for selected reasoning and local LLMs where practical. Separate Google AI Pro entitlement from Gemini API billing. Use least privilege, encrypted/OS secret storage, audit, TLS/auth for remote access, backups, rate limits, outbound restrictions and recovery runbooks.

## GitHub delivery workflow
Official repository: [dhruv0641/Dolla](https://github.com/dhruv0641/Dolla). `main` is production and protected by active GitHub ruleset [27482128](https://github.com/dhruv0641/Dolla/settings/rules/27482128); `develop` is integration, protected by ruleset [27482560](https://github.com/dhruv0641/Dolla/settings/rules/27482560). Work uses `feature/TASK-###-*`, `fix/TASK-###-*`, or `epic/EPIC-##-*` branches and PRs target `develop`. No direct main pushes, shared force-pushes, secrets in commits, or production merges without owner authorization. `docs/IMPLEMENTATION_PLAN.md` is the single chronological development log. Goal tracker: [#1](https://github.com/dhruv0641/Dolla/issues/1). TASK-001 through TASK-011 are complete and merged to `develop` with PR checks passed. TASK-012 issue [#24](https://github.com/dhruv0641/Dolla/issues/24) is in progress on `feature/TASK-012-brand-and-content-lifecycle-apis`.

## Decisions and unresolved assumptions
- PostgreSQL schema is a design starting point; migration review must resolve constraints, tenant isolation/RLS, credential references, retention and event semantics.
- MCP server identity, transport, auth, manifest, generation/status/download/credit capabilities and schemas are unverified. See `docs/MCP_CAPABILITY_MATRIX.md`.
- Exact Gemini/local models, TTS, media storage, deployment host, user authentication, OAuth scopes/quotas and licensing remain for goal-specific decisions.
- Validate current external API capabilities and policies before integrations.
- External integrations remain unconfigured; code delivered so far is a backend foundation and is not evidence of live Flow or publishing capabilities.

## Milestones
P0 Flow proof; P1 single-video vertical slice; P2 production management; P3 official publishing; P4 automated schedules; P5 intelligence loop; P6 multi-account operations. See `docs/IMPLEMENTATION_PLAN.md`.

## Definition of Done
A user can inspect an approved scheduled idea, original playable Flow scenes, narration from zero, QC-approved MP4, verified per-platform publication links, reconciled per-account credit costs and analytics feeding the next schedule. Tasks require acceptance evidence, passing relevant tests, review and documentation; architecture or mocks alone never imply production readiness.

## Current implementation status
**Implementation is underway.** 15 epics and 76 dependency-linked tasks are planned; TASK-001 through TASK-020 are merged to `develop`; TASK-021 is blocked on access to an authorized Google Flow MCP server/manifest. MCP capabilities and external credentials are unverified/unconfigured.

## Outstanding work and blockers
No planning blocker. Flow proof requires actual authorized server/tool manifest, supported auth mode, generation/status/download/credit capabilities and authorized account. Publishing requires eligible channels, OAuth grants and current API validation. Never paste credentials into chat.

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
- 2026-11-18: TASK-021 discovery checked current tool inventory, MCP resources and plugin search. No authorized Google Flow MCP server or manifest was exposed; documentation is in PR #53 and task issue #52 remains open and blocked. See `docs/MCP_CAPABILITY_MATRIX.md`; all server capabilities remain unverified.
