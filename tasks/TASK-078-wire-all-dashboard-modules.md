# TASK-078: Wire all nine dashboard modules to authenticated local APIs

- **Parent epic:** EPIC-17 — Authenticated Dashboard Operations
- **Assigned agent:** Frontend Engineer
- **Supporting agent:** Backend Engineer
- **Priority:** P0
- **Dependencies:** TASK-077
- **Estimated complexity:** 24 engineering hours
- **Status:** IN_REVIEW
- **Branch:** `feature/TASK-078-wire-dashboard-pages`
- **Issue:** [#231](https://github.com/dhruv0641/Dolla/issues/231)
- **Blockers:** None. External mutations and paid operations are excluded.

## User Story
As a local FlowX operator, I want every audited dashboard module to display verified owner-scoped application records so the workspace is useful without inventing data or enabling unsafe external actions.

## Objective
Add a server-to-server authenticated dashboard snapshot, sanitized database read models and frontend rendering for overview, pipeline, Flow/credits, quality/voice, publishing, agents, analytics, community and settings.

## Implementation Steps
1. Add a separate local dashboard service credential and fail-closed API authorization.
2. Add sanitized owner-scoped read views and a bounded dashboard repository.
3. Expose one typed dashboard snapshot and proxy it through the Next.js server without sending credentials to the browser.
4. Replace all hard-coded unavailable page states with verified records, counts or truthful zero/empty states.
5. Keep every provider mutation, generation, publishing, response and account action disabled.
6. Run focused tests, live PostgreSQL migration/API checks, frontend build, browser verification, full gates and Caveman review.

## Files and Components
Migration and dashboard persistence under `migrations/` and `src/flowx_os/db`, FastAPI/local-runtime wiring, Compose secret mounts, Next.js API proxy and all dashboard components.

## Acceptance Criteria
- [x] Dashboard reads require a separate server-only credential and fail closed when absent or invalid.
- [x] Every returned record is scoped to the configured local owner and omits credential references, raw secrets and unsafe provider payloads.
- [x] All nine pages render live values or verified zero/empty states from the snapshot.
- [x] The healthy `flow-main` account appears without implying a known credit balance or authorizing generation.
- [x] Content lifecycle counts and cards reflect live PostgreSQL records.
- [x] External mutations remain disabled and no credit, publishing, response or provider action occurs.
- [x] Backend/frontend tests, type-check, build, audit, live migration, browser checks, full suite and reviewer validation pass.

## Tests and Verification
Run dashboard repository/API/secret tests first, then live Compose migration and snapshot checks, frontend type/build, browser inspection and the full project gates.

## Verification Evidence
- 26 focused dashboard/API/secret tests and 734 full backend tests passed.
- Next.js production build and TypeScript passed; `npm audit --omit=dev` found zero vulnerabilities.
- Project validator passed with 17 epics, 78 task specs and no dependency cycles; Compose validates and all local services are healthy.
- Thirty-five migrations applied/replayed; the live endpoint returned `owner-dhruv`, one sanitized brand, one healthy `flow-main` account, zero content/jobs, and no dashboard error.
- Browser review visited all nine modules and confirmed verified zero states, Flow readiness, read-only settings evidence and disabled mutation controls.
- Caveman review closed the final base-table read by adding the sanitized brand view. No external, provider, publishing, response, paid or Flow operation occurred.

## Definition of Done
Implementation and evidence are merged through a reviewed PR to protected `develop`, required CI and post-merge validation pass, and no external or paid action occurred.
