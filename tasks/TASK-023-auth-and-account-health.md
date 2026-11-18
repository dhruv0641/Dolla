# TASK-023: Auth and account health

- **Parent epic:** EPIC-05 — Google Flow MCP Integration
- **Assigned agent:** Flow MCP Integration Engineer
- **Priority:** P0
- **Dependencies:** TASK-022
- **Estimated complexity:** 12 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub:** Issue [#85](https://github.com/dhruv0641/Dolla/issues/85); draft PR [#86](https://github.com/dhruv0641/Dolla/pull/86) targets `develop`; branch `feature/TASK-023-auth-and-account-health`.
- **Related source documents:** FLOW_MCP_ADAPTER_CONTRACT.json; ARCHITECTURE
- **External prerequisite:** Verify the Google account shown in the authorized Flow browser matches the intended account `dobariyadhruvv@gmail.com`. The current connector status reports `logged_in: true` but does not expose the email; do not treat that as account verification.
- **Blockers:** The live connector does not expose the signed-in email. The latest `flow_status` reports connected/logged-in, while the Flow page screenshot shows no account email. Do not claim intended-account verification until direct identity evidence is available. App-side health state and fail-closed verification can proceed independently.

## User Story
As a FLOW AI Content OS operator, I want auth and account health, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver auth and account health as an independently verifiable capability within google flow mcp integration.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [ ] Capability is implemented behind documented interfaces and configuration.
- [ ] Errors, state transitions and security boundaries are explicit and observable.
- [ ] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.
- [ ] Unsupported or unverified server capabilities fail closed.

## Implementation checkpoint — 2026-11-18
- Added `src/flowx_os/flow_mcp/account_health.py`: non-secret health snapshots, explicit health states and an injected provider/service boundary.
- Authorization is minted only by `FlowAccountHealthService` after it reads and type-checks its injected provider evidence. The proof includes check/expiry timestamps, and the adapter rejects future/expired proof on every call. It requires fresh, connected, logged-in, explicitly identity-verified evidence matching the configured opaque account reference. Missing/throwing/malformed providers, stale evidence, logged-out state, unknown identity and mismatches deny authorization with sanitized stable errors.
- No email, cookie, token or browser storage is accepted in health snapshots or status payloads.
- Authorization is short-lived and rechecked immediately before the adapter transport call, after asynchronous manifest/approval gates complete.
- Verification so far: `python -m unittest tests.test_flow_account_health tests.test_flow_mcp_adapter -v` — 24 passed; full suite — 181 passed; project-plan validation — 15 epics/76 tasks/no cycles; `git diff --check` — clean.
- Independent Technical Reviewer re-review passed with no remaining code blockers. Draft PR #86 is open and GitHub CI is pending. The live connector still does not expose an email, so the explicit external prerequisite to verify `dobariyadhruvv@gmail.com` remains incomplete; keep this task IN_REVIEW until direct identity evidence is available.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
