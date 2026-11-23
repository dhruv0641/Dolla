# Human-approved official community responses

TASK-070 adds a separate approval and provider boundary after the inert TASK-069 draft. `FLOWX_COMMUNITY_OFFICIAL_RESPONSES_ENABLED=false` is the default. The repository contains no HTTP client, OAuth flow, credential resolver or configured account; a deployment must inject a transport for an official YouTube or Meta interface.

## Safety contract

- Only an authenticated principal whose signed role is `reviewer` or `admin` may decide a draft. The persisted decision binds the reviewer identity and role, owner, exact draft record, text hash, classification lineage and a maximum 24-hour validity window.
- Safety escalations, deleted comments and records without a fixed clean draft cannot be approved. Rejection remains available for audit purposes and can never create a response claim.
- Approval grants no provider authority. Before the single mutation reservation, the database rechecks the owner, latest analysis, current comment version, published object, enabled destination, credential reference and unexpired approval. The transport must independently return fresh exact-destination scopes: `youtube.force-ssl`, `instagram_business_manage_comments`, or `pages_manage_engagement`.
- `DRAFT -> MUTATION_RESERVED` is the only mutation gate. A concurrent worker cannot reserve the same request. Once reserved, any timeout or malformed receipt is treated as an unknown outcome and is never automatically retried.
- An unknown outcome requires an operator-supplied response identity plus a read-only recovery evidence ID. Recovery does not create another response.
- A receipt is not completion. `RESPONDED` requires a separate official read proving the exact platform, destination, object, response ID, parent comment, approved text fingerprint and visibility. PostgreSQL recomputes and verifies the proof fingerprint.
- Approvals and terminal evidence are immutable. Secret values are prohibited; only `secretref://...` references are persisted.

## Operator states

| State | Meaning | Safe next action |
|---|---|---|
| `DRAFT` | Exact approved local claim; no provider mutation reserved | Revalidate authorization and reserve once |
| `MUTATION_RESERVED` | One worker owns the mutation; outcome not yet recorded | Do not retry; wait for receipt or record ambiguity |
| `VERIFY_PENDING` | Receipt or unknown outcome requires read-only proof | Recover identity if necessary, then reconcile by official read |
| `RESPONDED` | Exact remote response was independently proven | Terminal, replay-only |
| `FAILED` | Definite pre-response failure | Terminal; create new reviewed work instead of mutating history |

## Deployment limits

Unit and repository boundary tests use injected fakes. Migration parsing proves PostgreSQL syntax but not live trigger, locking, provider, OAuth, revocation or concurrency behavior. No account was connected and no reply, moderation, publication, paid service or Google Flow action was invoked during implementation. Production readiness requires live PostgreSQL integration, an audited official provider adapter, real scope/revocation tests and operator-approved account configuration.
