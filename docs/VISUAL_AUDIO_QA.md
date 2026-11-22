# Objective visual and audio evaluation

TASK-047 adds bounded local measurements after TASK-046 has produced an exact
passing integrity report. This stage measures objective signals only. It does
not claim semantic scene quality, brand consistency, speech intelligibility,
subjective mix quality, factual accuracy, policy safety, or human approval.

## Prerequisite and lineage

`AvEvaluationService.evaluate` accepts an immutable `IntegrityReport`, the
matching managed file descriptor, and the matching owner-scoped `AssetRecord`.
The integrity decision must be PASS with no findings, a verified full decode,
and the same observed SHA-256. Asset/content identity, managed URI, hash, size,
MIME type, content-level lineage, and declared duration are rechecked before
analysis. Failed or mismatched prerequisites stop before FFmpeg.

TASK-047 extracts a shared `verified_media_snapshot` boundary used by both the
integrity probe and evaluator. It derives the path from the asset UUID, rejects
symlinks, nonregular files and multiple hard links, snapshots all bytes under a
size cap, compares file identity before/after reading, verifies size/SHA-256,
fsyncs the private copy, and exposes no local path in errors.

## Measurements

`LocalFfmpegAvAnalyzer` runs one fixed no-shell FFmpeg filter graph with closed
stdin, one filter/output thread, an explicit file-only demuxer/protocol policy,
bounded runtime, allocation, input bytes, and diagnostic output. It uses:

- `blackdetect` for black interval duration;
- `freezedetect` for frozen interval duration;
- `silencedetect` for silence duration; and
- `ebur128` for integrated loudness and true peak.

Only allowlisted numeric labels are parsed from bounded diagnostics. Missing,
non-finite, excessive, or inconsistent metrics become
`MEDIA_ANALYSIS_INVALID`; raw tool output is discarded. Duration totals and
ratios are stored together and must agree exactly within rounding tolerance.

The version-1 defaults are an initial product policy, not production
calibration: black ratio <= 2%, frozen ratio <= 15%, silence ratio <= 25%,
integrated loudness -16 LUFS +/- 3 LU, and true peak <= -1 dBTP. Detection
durations, thresholds, resource bounds, and audio limits are strict typed
configuration and are included in the evidence fingerprint.

## Decisions and unavailable signals

Findings use a closed enum and stable order. Threshold breaches or changed
managed bytes produce FAIL. A missing/unavailable/incomplete analysis produces
NEEDS_HUMAN without fabricating measurements. No findings produces PASS for
these objective checks only. Every report explicitly records the following as
not evaluated: semantic visual quality, speech intelligibility, and subjective
mix preference. Those require later evidence and cannot be inferred from PASS.

The report persists the exact policy, measurements, findings, prerequisite
integrity fingerprint, and all unavailable subjective signals. Its canonical
SHA-256 is recomputed during model validation; decision and blocker severity
must match the findings. No numeric quality score is invented.

## Persistence and recovery

`AvReportRepository.create_or_get` stores one immutable `av-v1` report per
active final/export asset. The transaction repeats owner, brand, content,
retention, kind, and scene checks and requires an existing PASS
`integrity-v1` row with the exact prerequisite fingerprint. Migration 0014
enforces this link, partial uniqueness, envelope/decision/blocker consistency,
and immutability without restricting later QA report versions.

Exact replay with the same report UUID and evidence returns the stored row;
rebinding conflicts. A crash before commit leaves no row and is safely retried.
A lost success response is recovered by exact replay. Live PostgreSQL trigger
and locking behavior remains environment-unverified.

## Evidence boundary

Tests exercise parsing, policy bounds, stable finding order, tamper detection,
safe tool failure, prerequisite rejection, owner-scoped persistence, replay,
and conflicts. Real local fixtures cover moving video/audio with no detected
intervals and a black/frozen/silent composition that produces measured failure
ratios. Production threshold calibration, diverse codecs/content, subjective
review, AI vision, and production media-volume behavior remain unverified.
