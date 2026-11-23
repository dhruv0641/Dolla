# Community Reply Drafts and Escalation

TASK-069 adds an inert, disabled-by-default drafting boundary over exact TASK-068 classification evidence. `FLOWX_COMMUNITY_REPLY_DRAFTING_ENABLED=false` is the default. Enabling it creates only local review records; it cannot send a reply, moderate a comment, connect an account, call a provider, publish, spend or invoke Google Flow.

## Evidence boundary

Every `ReplyDraftRequest` binds one owner, publication, latest analysis report, current immutable comment version, classification fingerprint, policy version and request time. The repository requires the classified version to remain the current comment and the analysis report to remain latest for that publication. Persistence locks the publication, reloads the target and rejects changes before insert.

Migration 0030 independently locks and verifies the same owner and evidence, recomputes the request, target and record fingerprints, repeats the versioned decision, and rejects direct writes that differ. Records are immutable and unique per exact classification/policy. Raw comment text is not copied into reply records.

## Deterministic drafts

`community-reply-v1` uses fixed, non-personalized templates for clean TASK-068 themes. It never interpolates untrusted comment text, follows instructions in comments, claims an issue was solved or invents facts. Every draft has disposition `DRAFT_REQUIRES_HUMAN_APPROVAL`, `human_approval_required=true` and `outbound_action_authorized=false`.

This is deliberately not generative AI. A future model-backed drafting version would require a separately reviewed policy version, strict typed output, authorization and cost controls; no paid or external model is configured here.

## Mandatory escalation

Any TASK-068 safety category other than `NO_DETECTED_SIGNAL`, or any `requires_human_review` flag, produces `ESCALATED_NO_DRAFT`. No reply text is created. `CRITICAL` signals such as detected self-harm or violence receive `URGENT`; other detected signals receive `HUMAN_REVIEW`. Deleted/unavailable content receives `CONTENT_UNAVAILABLE_NO_DRAFT`. These are workflow signals, not medical, legal, moderation or emergency determinations.

Stable fail-closed errors cover disabled policy, unavailable policy version, future requests, changed evidence, missing owner-scoped evidence, store identity mismatch and persistence conflict. Exact replay revalidates the current target before returning the immutable record.

## Explicit non-authority and limits

TASK-070 owns later human approval and official responses. TASK-069 has no provider transport or mutation method. Human reviewers must inspect the source comment, classification limitations, platform policy and proposed text before any later response.

Unit tests cover clean drafts, every escalation boundary, critical priority, deleted content, exact replay, identity/version/time failures, latest-report/current-comment checks and publication-lock revalidation. PostgreSQL syntax and structural controls are verified, but Docker Engine and `psql` are unavailable, so live trigger, locking and concurrency behavior remains unverified. No external, account, paid, public or Flow action occurred.
