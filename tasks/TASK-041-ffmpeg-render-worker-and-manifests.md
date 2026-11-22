# TASK-041: FFmpeg render worker and manifests

- **Parent epic:** EPIC-09 — Automated Video Editing
- **Assigned agent:** Media Pipeline Engineer
- **Priority:** P1
- **Dependencies:** TASK-032, TASK-036
- **Estimated complexity:** 4 engineering hours (planning estimate)
- **Status:** DONE
- **Related source documents:** ARCHITECTURE
- **GitHub issue:** [#150](https://github.com/dhruv0641/Dolla/issues/150)
- **Branch:** `feature/TASK-041-ffmpeg-render-worker`
- **Implementation PR:** [#151](https://github.com/dhruv0641/Dolla/pull/151), merged to `develop` as `f23b176d62875d0b7b7e98c783a3597da7addd00`
- **Blockers:** None. Local FFmpeg availability is runtime-dependent and must fail closed without claiming a render.

## User Story
As a FLOW AI Content OS operator, I want ffmpeg render worker and manifests, so the platform can progress safely through a traceable production lifecycle.

## Objective
Deliver ffmpeg render worker and manifests as an independently verifiable capability within automated video editing.

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
- `flowx_os.rendering.FfmpegRenderWorker` accepts a strict owner/content render request, verified managed input metadata and a fixed operator policy; it does not accept raw FFmpeg arguments.
- Full-file hash, size, inode, link and path checks precede execution. FFmpeg uses no shell/stdin, fixed local protocols/demuxers/codecs, one thread, bounded runtime and bounded diagnostics; safe error codes hide stderr and paths.
- `RenderManifest` produces migration-0010-compatible `inputs_manifest` JSON and a path-free declarative `command_manifest`; its SHA-256 fingerprint binds ordered input evidence, request/version/output identity and codec policy.
- Five focused worker tests include real FFmpeg output and tamper rejection; 21 render/asset/probe/audio regression tests and the full 347-test non-migration backend suite pass.
- Independent Technical Reviewer accepted final head `9f45402` with no blocker after checking security, ownership, manifests, FFmpeg/probe constraints, idempotency, failure handling and task boundaries; the missing-probe regression proves ingest is not called after output validation failure.
- Both required checks and the post-merge `develop` check passed for [PR #151](https://github.com/dhruv0641/Dolla/pull/151); no direct protected-branch push occurred.
- Compileall, project-plan validation and diff check pass. Cross-build byte determinism, production volumes and PostgreSQL render-job orchestration remain unverified and are not claimed; multi-input composition belongs to TASK-043.

## Tests and Verification
- Unit tests for domain rules and failure cases.
- Integration tests for persistence and adapter boundaries where relevant.
- Record actual commands/results; live integration evidence is required for production-readiness claims.

## Definition of Done
Implementation exists, criteria are verified, relevant tests pass, no critical regression is found, docs/status are updated, and Technical Reviewer records evidence.
