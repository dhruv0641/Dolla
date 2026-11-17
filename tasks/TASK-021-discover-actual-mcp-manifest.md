# TASK-021: Discover actual MCP manifest

- **Parent epic:** EPIC-05 — Google Flow MCP Integration
- **Assigned agent:** Flow MCP Integration Engineer
- **Priority:** P0
- **Dependencies:** TASK-002
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** BLOCKED
- **GitHub:** Issue [#52](https://github.com/dhruv0641/Dolla/issues/52) remains open; tracking branch `feature/TASK-021-discover-actual-mcp-manifest` targets `develop`.
- **Related source documents:** FLOW_MCP_ADAPTER_CONTRACT.json; ARCHITECTURE
- **Blockers:** No authorized Google Flow MCP server or manifest is available to this Codex session. The actual server tool schema cannot be inspected until the server is configured/exposed. The proposed contract and unrelated video providers are not substitutes.

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
Discovery evidence and capability status are recorded in `docs/MCP_CAPABILITY_MATRIX.md`, this task specification and the timestamped project log. No adapter/tool names are inferred and no external calls or credentials are used.

## Acceptance Criteria
- [ ] Actual authorized server identity and manifest have been inspected and recorded.
- [x] Current tool/resource inventories were inspected; absence of an authorized Flow MCP server and actual manifest is documented without claiming support.
- [ ] Unsupported or unverified server capabilities are confirmed to fail closed by the implementation.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
