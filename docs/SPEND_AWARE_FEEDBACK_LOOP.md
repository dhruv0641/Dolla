# Spend-aware approved feedback loop

TASK-066 records two immutable boundaries: an approval/spend gate for one exact
TASK-065 experiment proposal, and a post-gate descriptive cohort outcome. It
does not call Google Flow or any publisher and does not execute an experiment.

## Approval and spend gate

The gate requires all of the following at one owner-scoped identity:

- the exact immutable experiment proposal and fingerprint;
- immutable, expiring experiment and spend attestations returned by configured
  trusted verifiers, with verifier version and evidence fingerprints;
- an owned `RESERVED` credit reservation whose request ID, quote, expiry and
  account match the request and whose credits do not exceed the explicit cap;
- a healthy, unpaused, compliance-approved Flow account; and
- a fresh observed daily/monthly balance, current reset/cycle, available active
  credits and concurrency capacity; and no open unknown-spend alarm.

The database locks the account, reservation and both attestations, repeats these
checks against database time, rejects expired or revoked attestations, derives
the record fingerprints, rejects non-canonical JSON, and stores an immutable
insert-or-read decision. Ordinary roles cannot directly insert or mutate gate,
attestation, revocation or outcome rows. Approval references are references
only; credentials, cookies and tokens are forbidden. Spend attestations bind
the exact `video_generate` operation. Trusted approval ingestion and revocation
use security-definer procedures callable only by a dedicated no-login writer
role. The ordinary gate runtime role cannot insert attestations.

The decision is `APPROVED_PENDING_FRESH_EXECUTOR_REVALIDATION`, not execution
authority. It explicitly sets execution, automatic execution, account
connection, scheduling, upload and publishing authority to false. A separate
future executor must atomically revalidate the exact reservation, account,
approval, alarm, job and capability state immediately before any paid action.

## Descriptive feedback

An outcome can reference only a new immutable TASK-064 report created after the
gate. The actual publication time, metric window and observation—not merely the
metadata/report creation time—must all be post-gate. Owner, creative factor,
platform, raw metric, window, registry, control
and treatment labels must equal the proposal. Both arms must be eligible and
meet their fixed target sizes, and all included creative metadata must be
post-gate evidence.

The outcome is labelled `DESCRIPTIVE_FEEDBACK_ONLY_NOT_CAUSAL`. It authorizes no
automatic execution or causal claim. Reusing the report in a new TASK-065
recommendation cycle requires a separate recommendation and human review.

## Failure and operational limits

- Missing or mismatched owner/proposal/reservation evidence, stale quotes,
  exceeded caps, unhealthy or paused accounts, open unknown-spend alarms, and
  unavailable/rejected approvals fail closed with stable error codes.
- Reported associations may reflect confounding, selection effects or metric
  drift. Meeting target sample sizes does not establish statistical power or
  causality.
- Source IDs and metrics remain owner-scoped operational data and must not be
  copied into prompts, public logs or cross-tenant exports.
- Unit and repository tests use local fakes. Live PostgreSQL trigger execution,
  live approval stores, Flow account state and paid execution require separate
  verification and authorization; none is claimed by TASK-066.
