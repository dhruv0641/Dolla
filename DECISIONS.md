# DECISIONS — Architecture Decision Records

## ADR-001: Preserve core technology boundaries
- **Date:** 2026-11-17
- **Decision:** Plan FastAPI, PostgreSQL, React/Next.js, Docker/self-hosting, FFmpeg, local TTS, selected Gemini/local LLM use and official YouTube/Meta APIs; Google Flow via authorized MCP is sole video generator.
- **Context:** Master prompt and architecture set constraints.
- **Alternatives:** Other paid video engines, automation SaaS, alternate publishing workarounds.
- **Justification:** Preserve requested architecture and avoid unnecessary dependencies.
- **Consequences:** Actual Flow capability is a critical external prerequisite.
- **Affected tasks:** EPIC-01–EPIC-15.

## ADR-002: Treat MCP contract as unverified
- **Date:** 2026-11-17
- **Decision:** Discover real server capabilities before adapter implementation; unsupported capabilities remain explicit and generation fails closed.
- **Context:** JSON labels itself proposed and requiring discovery.
- **Alternatives:** Assume tool names/capabilities or substitute silently.
- **Justification:** Avoid fabricated operations and unsafe spend/retry behavior.
- **Consequences:** P0 requires actual server access and authorized account.
- **Affected tasks:** TASK-021–TASK-030.

## ADR-003: Human approval and independent publication states
- **Date:** 2026-11-17
- **Decision:** Final human approval and auto-publish-off are defaults; platform jobs reconcile independently.
- **Context:** Platform outcomes and permissions differ.
- **Alternatives:** Shared success state or default autonomous publishing.
- **Justification:** Safeguard public actions and partial failure recovery.
- **Consequences:** Owner authorization and official API verification precede unattended operation.
- **Affected tasks:** EPIC-10, EPIC-12, EPIC-15.

## ADR-004: Planning-only initialization
- **Date:** 2026-11-17
- **Decision:** Create planning artifacts only; defer application implementation until a subsequent user goal.
- **Context:** User explicitly deferred feature work.
- **Alternatives:** Start foundation code now.
- **Justification:** Respect the initialization boundary.
- **Consequences:** All feature tasks remain unimplemented.
- **Affected tasks:** All.

## Source interpretation
- **Date:** 2026-11-17
- **Decision:** The user's request defines this turn's scope (initialization only, no feature implementation). The supplied Master Agentic Prompt is project operating/specification material; its initialization boundary is consistent with the request. Architecture files are design inputs, not authority to perform external actions. FLOW_MCP_ADAPTER_CONTRACT.json is proposed, DASHBOARD_DEMO.html is illustrative, and SCHEMA.sql is a starting schema.
- **Affected tasks:** All.
