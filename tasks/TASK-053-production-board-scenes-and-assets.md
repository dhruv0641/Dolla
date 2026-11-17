# TASK-053: Production board, scenes and assets

- **Parent epic:** EPIC-11 — Frontend Dashboard
- **Assigned agent:** Frontend Engineer
- **Priority:** P1
- **Dependencies:** TASK-052
- **Estimated complexity:** 16 engineering hours (planning estimate)
- **Status:** DONE
- **GitHub:** Issue [#61](https://github.com/dhruv0641/Dolla/issues/61) closed; PR [#62](https://github.com/dhruv0641/Dolla/pull/62) merged to `develop` as `e970369`; CI passed.
- **Related source documents:** DASHBOARD_DEMO.html; ARCHITECTURE
- **Blockers:** Live records require an authenticated frontend session; scene and asset endpoints are not implemented. This task delivers truthful workspace presentation and leaves live rows unavailable until those dependencies exist.

## User Story
As a FLOW AI Content OS operator, I want production board, scenes and assets, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver production board, scenes and assets as an independently verifiable capability within frontend dashboard.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`web/src/components/production-board.tsx` will render lifecycle-stage empty states and scene/asset detail panels without implying records exist. Current FastAPI exposes authenticated brand/content listing only; no browser bearer-token flow or scene/asset endpoints are implemented. The dashboard will make these integration gaps explicit rather than bypassing auth.

## Acceptance Criteria
- [x] Board columns represent every current content lifecycle state exactly once, including scheduled, published, failed and archived records.
- [x] Scene breakdown and asset lineage are distinct panels with clear unavailable states while APIs/auth are missing.
- [x] No sample content, counts, media links or state transitions imply live records; access boundaries are stated.
- [x] Responsive layout and integration limitations are documented; no live integration is claimed without verification.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.

## Tests and Verification
- `cd web; npm run typecheck` — passed.
- `cd web; npm run build` — passed.
- `git diff --check` — passed.
- Independent Technical Reviewer confirmed every backend `ContentStatus` is represented exactly once and found no blocker.
- No browser preview was available; rendered responsive overflow remains visually unverified.
- No live content, scene or asset API is available/configured; authenticated content data was not accessed.
