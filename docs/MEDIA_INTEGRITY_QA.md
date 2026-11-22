# Deterministic media integrity QA

TASK-046 adds a local, deterministic gate for `FINAL_VIDEO` and
`EXPORT_VARIANT` assets. It does not perform visual-quality judgment, factual
or policy review, human approval, publication, account access, or any paid
operation.

## Inputs and trust boundary

`MediaIntegrityService.evaluate` requires a strict `IntegrityExpectation`, the
managed file descriptor, and the matching `AssetRecord` obtained through an
owner-scoped repository. Identity, content, kind, URI, MIME type, size, digest,
and content-level lineage must agree before the probe runs. A structural
lineage mismatch raises only `ASSET_LINEAGE_MISMATCH` and exposes no path.

The existing `MediaProbeService` makes a private bounded snapshot, hashes every
byte, runs allowlisted local FFprobe/FFmpeg commands without a shell, and fully
decodes audio/video. TASK-046 extends its typed report with sanitized container,
frame-rate, H.264 profile, pixel-format, and subtitle evidence. Untrusted tool
text and local paths never enter findings or persistence.

## Deterministic checks

The expectation binds the asset and content UUIDs, final/export role, render or
export fingerprint, optional export profile, dimensions, frame rate, duration,
and audio/subtitle requirements. The default output contract checks:

- stored render metadata and profile match the expectation;
- immutable managed bytes match their SHA-256 and size;
- full decode completes without probe violations;
- the demuxer identifies an MP4-family container;
- exactly one H.264 video stream uses the configured profile, `yuv420p`,
  dimensions, and constant expected frame rate;
- required audio is exactly one AAC stream;
- required subtitles are exactly one `mov_text` stream; and
- probed duration is within the bounded tolerance (250 ms by default).

Every failure uses the closed `IntegrityFindingCode` enum in a stable evaluation
order. No weighted or invented numeric score is produced: PASS means there are
zero deterministic findings, otherwise the decision is FAIL. The evidence
fingerprint is SHA-256 over the canonical expectation, sanitized observation,
and ordered findings, so an exact rerun is reproducible.

## Persistence and recovery

`IntegrityReportRepository.create_or_get` stores one immutable `integrity-v1`
report per active final/export asset. It repeats owner/brand/content/kind checks
inside the transaction. Exact replay with the same report UUID and evidence is
idempotent; any attempt to rebind the asset/version fails closed. Migration
0013 enforces active same-content render lineage, the AUTO PASS/FAIL envelope,
one report per asset/version, and prevents mutation or deletion of integrity
evidence.

A process failure before commit leaves no report and can be retried with the
same UUID. A retry after a successful but unobserved commit returns the exact
stored report. Later visual/audio, policy, and human-review tasks remain
separate evidence rather than silently changing this deterministic report.

## Verification boundary

Focused tests cover exact pass, stable multi-failure ordering, unsafe lineage,
metadata disagreement, safe probe failure, redaction, real local muxed
H.264/AAC/mov_text media, owner-scoped persistence, idempotent replay, and
rebind refusal. The workstation has FFmpeg/FFprobe and exercises a real local
fixture. All migrations, including 0013, parse successfully with `pglast` on
this workstation. Live PostgreSQL migration, trigger, and lock behavior is not
configured, so that integration boundary remains unverified and production
readiness is not claimed.
