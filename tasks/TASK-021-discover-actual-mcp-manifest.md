# TASK-021: Discover actual MCP manifest

- **Parent epic:** EPIC-05 — Google Flow MCP Integration
- **Assigned agent:** Flow MCP Integration Engineer
- **Priority:** P0
- **Dependencies:** TASK-002
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub:** Issue [#52](https://github.com/dhruv0641/Dolla/issues/52) closed by PR [#82](https://github.com/dhruv0641/Dolla/pull/82), merged to `develop` as `36864b1`. Both required CI checks passed; independent technical review passed.
- **Related source documents:** FLOW_MCP_ADAPTER_CONTRACT.json; ARCHITECTURE
- **Blockers:** Runtime transport/deployment identity is not reported and is documented as unknown. Exact signed-in account verification is assigned to TASK-023; reconciliation of the old `sent` image job is assigned to TASK-024. The repository has no Flow adapter yet; this task verifies that unconfigured or unavailable Flow operations remain inaccessible in the current API shell. The proposed contract is not server documentation.

## User Story
As a FLOW AI Content OS operator, I want discover actual mcp manifest, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver discover actual mcp manifest as an independently verifiable capability within google flow mcp integration.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Discovery evidence and capability status are recorded in `docs/MCP_CAPABILITY_MATRIX.md`, this task specification and the timestamped project log. Tool names/schemas were read from the actual runtime manifest; no generation, credentials, or paid operation were used.

## Acceptance Criteria
- [x] Actual runtime tool identity (`mcp__google_flow`) and exposed schemas have been inspected and recorded; transport/deployment identity limitations are explicit.
- [x] The prior tool/resource inventory absence finding and this later live Flow MCP tool exposure are recorded as separate dated observations.
- [x] Current application behavior fails closed: no Flow operation route is exposed, and readiness returns unavailable when the Flow probe is absent or false; verified by focused API tests. A real adapter remains a follow-on task.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.
- Focused verification: `python -m unittest tests.test_api.ApiShellTests.test_readiness_reports_configured_probe_results tests.test_api.ApiShellTests.test_readiness_is_not_ready_when_dependencies_are_unconfigured tests.test_api.ApiShellTests.test_openapi_exposes_service_auth_and_content_routes -v` — 3 tests passed. Project-plan validator: 15 epics, 76 task specs, 76 dependency nodes, no cycles.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
