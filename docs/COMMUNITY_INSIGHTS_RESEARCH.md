# Community insights to research

TASK-071 adds a disabled-by-default handoff from the latest immutable TASK-068 community-analysis report to bounded research proposals. Set `FLOWX_COMMUNITY_INSIGHTS_ENABLED=true` only for a local worker that intentionally records these proposals.

Each proposal is derived from one exact theme cluster and contains only a fixed versioned question key, aggregate member/review counts, priority, and source fingerprints. Raw comment text is never copied into a proposal. A safety-review count makes priority `HIGH`; otherwise clusters with at least three members are `MEDIUM`, and smaller clusters are `LOW`. Every proposal requires human review and has `research_execution_authorized=false`.

The parent record binds the owner, publication, latest analysis request/report, source snapshot, ordered cluster set, policy version and request time. PostgreSQL locks the owned publication before rechecking the latest analysis, recomputes proposal decisions and fingerprints, verifies deferred completeness, and makes both parent and child evidence immutable. Exact replay returns the same record; a changed source fails closed.

This capability only proposes future research. It contains no browser, model, retrieval-provider, account, moderation, response, publishing, spend, or Google Flow adapter. All seven corresponding authority fields are permanently false. Enabling the flag does not authorize any of those actions. External research still requires a separate reviewed request, approved provider boundary and appropriate authorization.

Operational evidence is currently limited to domain/repository tests and PostgreSQL migration parsing. Until migration triggers and concurrent locking are verified against a live PostgreSQL deployment, this capability is implemented and test-covered but not production-ready.
