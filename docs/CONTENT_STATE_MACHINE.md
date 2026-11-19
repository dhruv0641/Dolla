# Content lifecycle state machine

`ContentStatus` is the typed representation of the `content_items.status` PostgreSQL constraint. A transition request must target a known enum value and a permitted edge. The repository selects the content row through its owned brand under `FOR UPDATE`, validates its current state, then updates using both owner scope and the expected current state in the `WHERE` clause. The lock serializes concurrent transitions; a missing or foreign row is returned as not found. Invalid edges return `409`; unknown state values return `422`.

| Current state | Allowed next states |
|---|---|
| `IDEA` | `RESEARCHED`, `ARCHIVED` |
| `RESEARCHED` | `BRIEF_READY`, `ARCHIVED` |
| `BRIEF_READY` | `SCRIPT_READY`, `ARCHIVED` |
| `SCRIPT_READY` | `STORYBOARD_READY`, `ARCHIVED` |
| `STORYBOARD_READY` | `GENERATING`, `ARCHIVED` |
| `GENERATING` | `ASSEMBLING`, `FAILED` |
| `ASSEMBLING` | `QA_PENDING`, `FAILED` |
| `QA_PENDING` | `NEEDS_REVIEW`, `FAILED` |
| `NEEDS_REVIEW` | `READY`, `SCRIPT_READY`, `STORYBOARD_READY`, `ARCHIVED` |
| `READY` | `NEEDS_REVIEW`, `ARCHIVED` |
| `SCHEDULED` | none (workflow-managed) |
| `PARTIALLY_PUBLISHED` | none (workflow-managed) |
| `FAILED` | `ARCHIVED` |
| `PUBLISHED` | none (workflow-managed) |
| `ARCHIVED` | none (terminal) |

The generic transition API cannot enter or leave `SCHEDULED`, `PARTIALLY_PUBLISHED` or `PUBLISHED`. Scheduling and publishing states have separate job records and require a future workflow that updates both records atomically and verifies remote publication before recording its outcome. Operators cannot use this generic endpoint to mark content scheduled or published. `FAILED` can only be archived until a versioned artifact reset/retry workflow exists, so stale scripts, scenes or assets cannot be reused accidentally. Live database concurrency behavior remains unverified until PostgreSQL integration tests are available.

The storyboard write endpoint has its own guarded lifecycle behavior: the first version can be saved only from `SCRIPT_READY` or `NEEDS_REVIEW`, transitioning content to `STORYBOARD_READY`; later versions of `STORYBOARD_READY` content preserve that state. Every version is an immutable snapshot, and scene rows are keyed by storyboard version so prior generations and asset lineage remain attached to the scene version they used. Writes require the caller's expected version and reject stale concurrent edits.

Scene generation attempts use `SceneRetryPolicy`: with the default two regenerations, attempt indexes 1–3 are possible. Initial generation requires a `PENDING` scene; retries require `RETRY_WAIT` plus a matching persisted retry counter. Only a definitive failure can schedule a retry, in the same transaction that marks the failed attempt. Unknown remote submission outcomes block the scene and never qualify for retry. Each new attempt requires its own existing credit reservation and idempotency fingerprint; the application does not automatically submit another paid generation.
