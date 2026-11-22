# Policy, factuality and copyright signals

TASK-048 adds a deterministic QA envelope around the validated automated content-review contract. It does not call a model, fetch a source, interpret platform policy, grant rights, provide legal advice or approve content.

## Prerequisites and trust boundary

- The exact asset must already have a PASS `av-v1` report. `signals-v1` binds the AV evidence fingerprint and refuses a failed, incomplete or different AV report.
- `ReviewContext` must already contain the version-pinned prompt/policy IDs, draft and citation-bound source snapshots validated by the existing review workflow.
- `HumanReviewResult` is untrusted until its strict schema, source IDs and content binding are rechecked at the signal boundary.
- Rights-authority references are opaque identifiers supplied by trusted orchestration. This capability validates only their shape and binding; it does not fetch or prove the underlying licence, ownership or public-domain claim. If none is supplied, copyright authority is explicitly `UNAVAILABLE`.

Raw source snapshot text is not persisted in the QA report. The report fingerprint binds a SHA-256 digest of each snapshot plus its evidence metadata, retrieval time, draft, review assessment, pinned versions, three signals, findings and upstream AV fingerprint.

## Signal meaning

Every report contains POLICY, FACTUALITY and COPYRIGHT in a fixed order. Each signal is one of:

- `NO_AUTOMATED_FLAG`: the supplied automated review produced no finding in that domain. This is not affirmative clearance.
- `FLAGGED`: the validated automated review produced at least one finding in that domain.
- `UNAVAILABLE`: required authority is absent. In v1 this applies to missing copyright/rights authority.

Critical domain findings and a blocked automated-review disposition are blockers. Non-critical findings, revision requests and absent copyright authority require human review. The derived report decision is:

- `FAIL` when a blocker exists;
- `NEEDS_HUMAN` when a review finding exists without a blocker;
- `PASS` only when no automated finding exists and a rights-authority reference was supplied.

All three outcomes retain `human_approval_required=true` and `content_approved=false`. PASS is an automated-stage result only. TASK-050 remains responsible for human approval; no report from this capability authorizes generation, scheduling or publishing.

## Persistence and recovery

Migration 0015 and `PolicySignalReportRepository` store one immutable owner-scoped `signals-v1` report per active final/export asset. The database trigger requires exact PASS `av-v1` evidence, content-level active asset lineage, canonical signal/findings envelopes, derived blockers and derived decision. Exact replay is idempotent. A different report ID or evidence for the same asset/version fails closed.

If source snapshots, draft, automated assessment, pinned prompt/policy versions, rights references, asset or AV evidence change, create a new asset/versioned workflow result rather than mutating stored evidence.

## Explicitly unverified

- The supplied sources may be incomplete, stale, biased or wrong despite citation binding.
- A policy version/reference does not prove that every current platform rule was represented or interpreted correctly.
- A rights reference does not prove ownership, licence scope, territory, duration, attribution compliance or fair-use/fair-dealing status.
- No live policy provider, fact-checking provider, rights registry or legal-review service is connected.
- PostgreSQL trigger and locking behavior is not production-verified until run against the deployment database.

Human reviewers must inspect authoritative sources, current platform rules and underlying rights records before approval.
