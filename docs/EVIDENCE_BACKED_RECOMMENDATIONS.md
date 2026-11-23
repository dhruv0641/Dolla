# Evidence-backed recommendations and experiments

TASK-065 converts one immutable TASK-064 descriptive cohort report into a
review-only association hypothesis and, optionally, an inert experiment
proposal. It does not select a winner or infer causality.

## Evidence requirements

- The cohort report must have status `DESCRIPTIVE` and at least two eligible
  cohorts. Small groups remain disclosed but cannot be selected as an arm.
- Owner, report request ID, report fingerprint, source fingerprints, platform,
  raw metric definition, registry, collection window, minimum group size,
  exclusions, sample sizes, medians and interquartile ranges are copied from
  the immutable report. Missing or mismatched evidence fails closed.
- A recommendation is always `HYPOTHESIS_ONLY` and is labelled
  `DESCRIPTIVE_ASSOCIATION_ONLY_NOT_CAUSAL_NO_GUARANTEED_WINNER`.
- Reports and proposals use owner-scoped insert-or-read persistence. Reusing an
  ID with different evidence is a conflict. Database triggers recalculate the
  fingerprints and reject substituted lineage or non-canonical JSON.

## Experiment boundary

An experiment proposal pins exactly one creative factor plus its control and
treatment labels, platform, metric, collection window, balanced 1:1 allocation,
minimum and target sample per arm, a fixed-sample stop rule with no early
efficacy stop, and two fail-closed safety pauses. Its only status is
`DRAFT_REQUIRES_HUMAN_APPROVAL`.

The proposal explicitly grants no authority to execute, generate media, spend
credits, connect an account, schedule, upload or publish. There is no execution
method or provider adapter in this capability. Human approval and any
spend-aware execution feedback loop belong to TASK-066.

## Operational limits

- Results are descriptive and can be affected by confounding, selection bias,
  metric drift and small samples. The median and IQR do not prove an effect.
- Source payloads may contain platform identifiers and performance data. Apply
  existing owner authorization and retention controls; do not export them as
  prompt context or logs.
- The checked-in tests verify domain, repository and migration boundaries.
  Live PostgreSQL trigger execution must be recorded separately before any
  production-readiness claim.
- No provider call, account connection, paid generation, scheduling, upload or
  public action is part of TASK-065.
