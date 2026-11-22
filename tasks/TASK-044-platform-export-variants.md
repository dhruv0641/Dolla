# TASK-044: Platform export variants

- **Parent epic:** EPIC-09 — Automated Video Editing
- **Assigned agent:** Media Pipeline Engineer
- **Priority:** P1
- **Dependencies:** TASK-043
- **Estimated complexity:** 12 engineering hours (planning estimate)
- **Status:** IN_REVIEW
- **Related source documents:** ARCHITECTURE
- **GitHub issue:** [#159](https://github.com/dhruv0641/Dolla/issues/159)
- **Branch:** `feature/TASK-044-platform-export-variants`
- **Blockers:** None. Export is local-only; publishing, channel connections and upload APIs remain explicitly out of scope.

## User Story
As a FLOW AI Content OS operator, I want platform export variants, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver platform export variants as an independently verifiable capability within automated video editing.

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
- `PlatformExportService` accepts only the `YOUTUBE_SHORTS_V1`, `INSTAGRAM_REELS_V1` and `FACEBOOK_REELS_V1` product profile enum. Platform, geometry, FPS, H.264/AAC/mov_text codecs and bitrate targets are fixed and versioned; callers cannot supply raw transforms.
- The source must be an owner-scoped content-level `FINAL_VIDEO` with valid composition-v1 fingerprint, zero timeline, bounded duration and muxed subtitles. Complete managed bytes are snapshot-hashed before fixed no-shell FFmpeg execution.
- Path-free manifests and final metadata bind source UUID/hash, profile/platform/settings and deterministic fingerprint. Bounded probe verifies exact geometry/FPS/SAR, one H.264/AAC/mov_text stream set and duration before ingest as `EXPORT_VARIANT`; metadata always records `publishing_performed: false`.
- Four focused tests generate and verify real local YouTube, Instagram and Facebook variants at 1080×1920/30 FPS and reject tampered input before ingest; 20 render/composition/asset regressions and all 356 non-migration backend tests pass.
- Compileall, project-plan validation and diff check pass. Product profiles are not permanent platform-limit certification; OAuth, upload, remote processing, public availability and production isolation are unverified/out of scope.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
