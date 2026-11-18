# TASK-021: Discover actual MCP manifest

- **Parent epic:** EPIC-05 — Google Flow MCP Integration
- **Assigned agent:** Flow MCP Integration Engineer
- **Priority:** P0
- **Dependencies:** TASK-002
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** IN_PROGRESS
- **GitHub:** Issue [#52](https://github.com/dhruv0641/Dolla/issues/52) remains open; discovery record PR [#53](https://github.com/dhruv0641/Dolla/pull/53) merged to `develop` as `a964583`. Live runtime discovery is on `feature/TASK-021-live-flow-capability-discovery`, draft [PR #82](https://github.com/dhruv0641/Dolla/pull/82).
- **Related source documents:** FLOW_MCP_ADAPTER_CONTRACT.json; ARCHITECTURE
- **Blockers:** The signed-in Google account email cannot be verified from connector status; the intended `dobariyadhruvv@gmail.com` identity is unconfirmed. An old image job remains `sent` with unknown completion. The runtime does not report transport/deployment identity, and this repository has no Flow adapter whose fail-closed behavior can be verified. The proposed contract is not server documentation.

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
- [x] Actual runtime tool manifest and exposed schemas have been inspected and recorded; transport/deployment identity limitations are explicit.
- [ ] The signed-in Google identity and its authorization for the intended account have been verified.
- [x] The prior tool/resource inventory absence finding and this later live Flow MCP tool exposure are recorded as separate dated observations.
- [ ] Unsupported or unverified server capabilities are confirmed to fail closed by the implementation; no Flow adapter or generation route currently exists in the repository.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
