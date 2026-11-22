# TASK-042: Normalize codecs, fps and aspect ratios

- **Parent epic:** EPIC-09 — Automated Video Editing
- **Assigned agent:** Media Pipeline Engineer
- **Priority:** P1
- **Dependencies:** TASK-041
- **Estimated complexity:** 6 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** ARCHITECTURE
- **GitHub issue:** [#153](https://github.com/dhruv0641/Dolla/issues/153)
- **Branch:** `feature/TASK-042-normalize-video-profile`
- **Blockers:** None. Runtime FFmpeg/ffprobe availability remains fail-closed and must not be inferred from planning state.

## User Story
As a FLOW AI Content OS operator, I want normalize codecs, fps and aspect ratios, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver normalize codecs, fps and aspect ratios as an independently verifiable capability within automated video editing.

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
- `RenderPolicy` now declares bounded even output dimensions, a pixel-count ceiling, integer 1–60 FPS and explicit `COVER`/`CONTAIN` geometry while keeping fixed H.264/AAC/yuv420p codecs.
- The fixed FFmpeg filter scales without distortion, center-crops or pads, sets square pixels, enforces constant FPS and rebases video timestamps. Callers cannot inject filters or codec names.
- Profile fields are included in the path-free manifest and fingerprint and copied to final asset metadata. Bounded `ffprobe` requires one H.264 stream with exact dimensions/FPS/SAR and AAC for any audio before ingest.
- Six focused tests include real local normalization from 160×90 landscape to 180×320 portrait at 10 FPS and prove missing probe fails before ingest; 19 rendering/media/asset regressions and all 348 non-migration backend tests pass.
- Compileall, project-plan validation and diff check pass. Crop semantics, cross-build byte equality, production load isolation and downstream scene/audio/subtitle composition remain unverified and are not claimed.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
