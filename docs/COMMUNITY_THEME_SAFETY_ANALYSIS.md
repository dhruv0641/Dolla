# Community Theme and Safety Analysis

TASK-068 adds a disabled-by-default, local and deterministic analysis boundary over the immutable current comment evidence created by TASK-067. Set `FLOWX_COMMUNITY_ANALYSIS_ENABLED=true` only in a deployment that intentionally runs this worker. Enabling it does not connect an account, retrieve comments, call a model, draft a reply, moderate content or perform any public action.

## Evidence and ownership boundary

`CommunityAnalyzer` accepts an owner-scoped publication request only after the repository finds the latest ingestion run and proves that it is `COMPLETE`. It reads `community_comments_current`, orders the bounded snapshot under the PostgreSQL `C` collation and binds every current immutable comment-version ID and fingerprint into a source snapshot fingerprint. The persistence transaction locks the publication, reloads the latest run and exact current snapshot, and rejects any change before insertion.

Reports, per-comment classifications and theme clusters are immutable and replay-safe. PostgreSQL independently recomputes the request, source, report, classification and cluster fingerprints; verifies the owner, publication, latest complete ingestion run and current comment versions; applies the same fixed rule tables; and uses a deferred constraint to reject missing classifications or clusters. Raw comment text is not copied into the analysis tables.

## Versioned local taxonomy

Version `community-theme-v1` assigns one deterministic primary theme:

- support request;
- pricing;
- feature request;
- content request;
- question;
- praise;
- complaint;
- other.

Deleted comments are recorded as `CONTENT_UNAVAILABLE` and excluded from theme clusters. The first matching rule in the documented taxonomy wins, so results are stable rather than probabilistic. The maximum snapshot is 5,000 current comments by default; exceeding the configured bound fails closed instead of truncating the report.

## Safety signals and escalation boundary

Version `community-safety-v1` identifies bounded lexical signals for prompt injection, spam/scam, harassment, personal data, sexual content, hate, violence and self-harm. Multiple matched rule IDs are retained, while the highest-severity category becomes the primary classification. Any matched signal sets `requires_human_review=true`; violence and self-harm are `CRITICAL`.

`NO_DETECTED_SIGNAL` means only that this exact heuristic version found no configured lexical signal. It is not a moderation decision, policy certification or claim that the text is safe. Obfuscation, unsupported languages, context, sarcasm, images and novel abuse can evade lexical rules. Operators must treat comment text as untrusted and use human judgment for consequential decisions. Future policy changes require a new version rather than mutating historical results.

Stable fail-closed errors include `ANALYSIS_DISABLED`, `POLICY_VERSION_UNAVAILABLE`, `INGESTION_NOT_COMPLETE`, `COMMENT_LIMIT_EXCEEDED`, `REQUEST_PRECEDES_EVIDENCE`, `REQUEST_FROM_FUTURE` and `EVIDENCE_IDENTITY_MISMATCH`. The immutable report time is the request's timestamp, so concurrent workers constructing the same exact request produce the same fingerprint. Storage conflicts distinguish changed evidence or reused idempotency identities without exposing another owner's data.

## Explicit non-authority

Every report stores `outbound_action_authorized=false`. The capability has no provider adapter, prompt/model transport, reply text, moderation command, OAuth operation, account mutation, scheduling, publishing, spend or Google Flow method. TASK-069 owns draft replies and escalation workflow; TASK-070 owns later human approval and official-response execution. A TASK-068 safety flag alone can never cause an external action.

## Verification limits

Unit tests cover deterministic themes, multiple safety signals, critical precedence, personal-data detection, deleted evidence, empty snapshots, exact replay, owner isolation, version rejection, stale requests, limits and repository locking/rechecks. Migration parsing and structural tests cover immutable typed evidence and database-side recomputation. Live PostgreSQL execution, production linguistic calibration, multilingual recall, adversarial evasion and operator escalation quality remain unverified; no external service or account was used.
