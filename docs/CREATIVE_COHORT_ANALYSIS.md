# Creative metadata and cohort analysis

TASK-064 provides an offline, owner-scoped analytics boundary. It records immutable creative-factor evidence for an already published artifact and summarizes one declared factor against one raw metric for one platform and publish-relative window. It does not collect provider data, recommend a winner, infer causality, change content, spend credits, or publish anything.

## Creative evidence contract

`CreativeMetadataSnapshot` binds a publication to its owner, brand, content item, artifact version, script version, storyboard version, platform, publication time and schema version. Every snapshot contains exactly one entry for each supported factor:

- niche, hook type, script word count and CTA type;
- scene count, duration, narrator voice and posting time;
- platform, language and visual motif;
- Flow model and quoted Flow cost, only when durable evidence exists.

Every factor is explicitly `OBSERVED`, `UNAVAILABLE` with a reason, or `NOT_APPLICABLE`. An observed value requires a bounded evidence reference. The contract never converts absence to zero, an empty string or a guessed category. PostgreSQL derives a source fingerprint from the authoritative brand, script, storyboard, selected scene assets, voice profiles and credit reservations; it rejects mismatched factor values and derives both persisted fingerprints. Hook type, CTA type and visual motif remain unavailable until those categories have explicit versioned source fields—they are never inferred from prose.

Posting time uses the declared `creative-metadata-v1` projection `D<ISO weekday>-H<UTC hour>Z`, such as `D1-H14Z`. This lets different publication dates share a comparable UTC weekday/hour cohort without pretending absolute timestamps are categories. Platform and this projection must exactly match the publication record.

Factor evidence may reveal creative strategy, voice choices and operating patterns. API/UI exposure must therefore remain owner-scoped, omit raw prompts and credentials, and avoid cross-owner aggregation. This task intentionally introduces no public endpoint.

## Cohort contract

`CreativeCohortAnalyzer` accepts a versioned request containing one factor, one raw scalar metric, one fixed window, one metric-registry identity and a minimum group size of at least three. Candidates must have unique publication IDs and exact owner, platform, window and registry lineage. Numeric factors may use up to 20 explicit, non-overlapping bands; text factors use their observed value.

The report discloses:

- total candidates and included samples;
- counts for missing metadata, missing metric snapshots, unavailable factors, unavailable metrics and values outside declared bands;
- per-cohort sample size and eligibility;
- median and interquartile range only for eligible cohorts;
- immutable metadata and metric source fingerprints; and
- the fixed interpretation `DESCRIPTIVE_ASSOCIATION_ONLY_NOT_CAUSAL`.

A descriptive report requires at least two eligible cohorts. Otherwise its status is `INSUFFICIENT_COHORTS`. Medians and interquartile ranges reduce sensitivity to a single viral outlier, but they do not remove confounding, selection bias or platform-definition differences.

## Persistence and replay

`CreativeCohortRepository` performs owner-scoped source checks and uses insert-or-read replay. Reusing a snapshot or request identity with different evidence fails with `CreativeCohortConflict`. Voice, Flow model and quoted-cost factors follow the exact final render's immutable input asset IDs, not the content item's current voice or currently approved scenes. Every included publication is stored as one typed metadata/metric pair. Deferred database validation requires those pairs to match the report exactly, recomputes group sizes, eligibility, medians and quartiles, and rejects a report with missing or substituted metric evidence. Database triggers also derive request/report fingerprints; updates and deletes are rejected.

## Operational limits

- No live analytics provider or PostgreSQL runtime was exercised by this implementation unless separately recorded in the task evidence.
- Cohorts cannot mix platforms, metrics, windows, registry versions or owners.
- Derived ratios and structured metrics are rejected; only raw scalar count/time metrics are comparable.
- Unavailable samples are excluded and counted, never imputed.
- Exclusion counts are application-declared because an absent source has no immutable source row to reference. PostgreSQL strictly requires the complete five-reason schema, unique allowed reasons, nonnegative integer counts and exact candidate arithmetic; it does not claim to independently prove why an absent candidate was unavailable.
- Results are descriptive inputs for human review. TASK-065 owns recommendations and experiments; TASK-066 owns any spend-aware approved feedback loop.
