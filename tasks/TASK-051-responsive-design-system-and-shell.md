# TASK-051: Responsive design system and shell

- **Parent epic:** EPIC-11 — Frontend Dashboard
- **Assigned agent:** Frontend Engineer
- **Priority:** P1
- **Dependencies:** TASK-003, TASK-012
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **GitHub:** Issue [#55](https://github.com/dhruv0641/Dolla/issues/55); branch `feature/TASK-051-responsive-design-system-and-shell` targets `develop`.
- **Related source documents:** DASHBOARD_DEMO.html; ARCHITECTURE
- **Blockers:** None recorded at initialization; external prerequisites are in the capability matrix.

## User Story
As a FLOW AI Content OS operator, I want responsive design system and shell, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver responsive design system and shell as an independently verifiable capability within frontend dashboard.

## Implementation Steps
1. Inspect project state and confirm upstream contracts.
2. Design the smallest modular implementation consistent with architecture.
3. Implement with typed interfaces, configuration separation, idempotency and structured errors where applicable.
4. Document operational limits and update project memory.
5. Verify acceptance criteria and request independent review.

## Files and Components
`web/src/app/globals.css` defines responsive design tokens and layouts. `web/src/components/dashboard-shell.tsx` provides accessible navigation, the workspace shell, truthful empty/unavailable states and Flow verification status; `web/src/app/page.tsx` mounts it. No backend data or illustrative operational metrics are included.

## Acceptance Criteria
- [x] Responsive shell and visual tokens are implemented with accessible section navigation.
- [x] Data availability and Flow MCP verification states are stated accurately; empty states do not imply connected services.
- [x] Operational figures use unavailable placeholders until verified backend data exists; no demo counts, balances, posts, or performance values are presented.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
## Tests and Verification
- `cd web; npm run typecheck` — passed.
- `cd web; npm run build` — passed; Next.js statically prerendered `/`.
- `git diff --check` — passed (Git reports expected LF-to-CRLF working-copy notices for edited frontend files).
- No backend integration or live Flow MCP data was available; no visual browser review was completed.
- Independent Technical Reviewer: passed with no P1 blocker. Adjusted muted text color after review; contrast is 5.50:1 on cards and 5.76:1 on sidebar. Visual viewport review remains unverified because no browser provider was available.
