# TASK-025: Media retrieval and metadata

- **Parent epic:** EPIC-05 — Google Flow MCP Integration
- **Assigned agent:** Flow MCP Integration Engineer
- **Priority:** P0
- **Dependencies:** TASK-024
- **Estimated complexity:** 4 engineering hours (planning estimate)
- **Status:** IN_PROGRESS
- **GitHub:** Issue [#116](https://github.com/dhruv0641/Dolla/issues/116); branch `feature/TASK-025-media-retrieval-and-metadata`.
- **Related source documents:** FLOW_MCP_ADAPTER_CONTRACT.json; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want media retrieval and metadata, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver media retrieval and metadata as an independently verifiable capability within google flow mcp integration.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
Relevant application service, tests, migration (if needed), configuration and documentation. Select exact paths after repository inspection during execution.

## Acceptance Criteria
- [x] Capability is implemented behind documented interfaces and configuration.
- [x] Errors, state transitions and security boundaries are explicit and observable.
- [ ] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.
- [x] Unsupported or unverified server capabilities fail closed.

## Implementation checkpoint — 2026-11-19
- Added `flow_mcp.media.FlowMediaService` to read Flow project grid metadata, retain only unique UUID-backed media, and retrieve media under a configured local root. Retrieval requires the exact item discovered by this service; it validates the returned path stays within an isolated temporary directory, rejects symlinks/non-regular files, enforces size limits, checks MIME type and file signatures, computes SHA-256, and atomically places an idempotently named asset in the managed root.
- Added unit tests for malformed/duplicate metadata, URL validation, discovered-ID enforcement, path escape, MIME/signature mismatch, size limits, unknown IDs and repeat downloads. Focused service/adapter suite: 25 passed; full repository suite: 269 passed after the reviewer correction; plan validation, compileall and diff check passed.
- Actual Flow retrieval is not claimed: no media was downloaded from the live account. Flow video UUIDs are not guaranteed in project listings, though generation results already return file paths. Asset database lineage/retention and media probing/QC remain in downstream TASK-032/TASK-034.
- The Flow account panel was directly inspected through the authenticated browser and showed the identity the user approved. Exact address is omitted from repository docs. No account change was made.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
