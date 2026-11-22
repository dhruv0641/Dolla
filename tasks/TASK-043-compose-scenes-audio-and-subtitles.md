# TASK-043: Compose scenes, audio and subtitles

- **Parent epic:** EPIC-09 — Automated Video Editing
- **Assigned agent:** Media Pipeline Engineer
- **Priority:** P1
- **Dependencies:** TASK-042
- **Estimated complexity:** 8 engineering hours (planning estimate)
- **Status:** DONE
- **Related source documents:** ARCHITECTURE
- **GitHub issue:** [#156](https://github.com/dhruv0641/Dolla/issues/156)
- **Branch:** `feature/TASK-043-compose-scenes-media`
- **Implementation PR:** [#157](https://github.com/dhruv0641/Dolla/pull/157), merged to `develop` as `4855be4eb32b2f82a458888ab020dae6e39b0f07`
- **Blockers:** None. Composition remains local and fails closed if any scene, narration or subtitle asset is unavailable or outside authorized lineage.

## User Story
As a FLOW AI Content OS operator, I want compose scenes, audio and subtitles, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver compose scenes, audio and subtitles as an independently verifiable capability within automated video editing.

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
- [x] Acceptance evidence and operator documentation are recorded; external integration is not claimed without live verification.

## Acceptance Evidence
- `MediaCompositionService` accepts a strict contiguous 1–30-scene timeline, normalized narration and generated captions with exact content/scene/storyboard/audio lineage and valid upstream fingerprints.
- All distinct managed inputs are completely snapshot-hashed under an aggregate byte limit. The fixed graph normalizes/pads/trims each scene, concatenates manifest order, anchors narration at 0:00, and muxes SRT through a separate restricted input as selectable `mov_text` rather than interpolating paths/text into filters.
- The path-free manifest and fingerprint bind ordered roles, UUIDs, hashes, scene timing, storyboard/render versions and output policy. Bounded `ffprobe` requires exact H.264 profile, one AAC track, one `mov_text` track and duration within 250 ms before ingest.
- The normalized `inputs_manifest` stores ordered asset IDs, while `command_manifest` stores roles/positions and the complete scene timeline so the database split is replayable without filesystem paths.
- Four focused composition tests include real red→blue scene-order evidence, zero-start AAC, subtitle-stream verification and tamper-before-ingest rejection; 17 render/caption/audio regressions and all 352 non-migration backend tests pass.
- Independent Technical Reviewer accepted final head `cb45c7e` with no blocker after checking lineage, exact-set/order, filter construction, subtitle isolation, resource limits, output validation, tamper cleanup, idempotency and split-manifest replayability.
- Both required checks and the post-merge `develop` check passed for [PR #157](https://github.com/dhruv0641/Dolla/pull/157); no direct protected-branch push occurred.
- Compileall, project-plan validation and diff check pass. Editorial transitions, music mixing, burned-in styling, PostgreSQL orchestration and production isolation remain unverified or downstream and are not claimed.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
