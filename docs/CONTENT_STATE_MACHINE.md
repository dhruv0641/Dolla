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
| `READY` | `SCHEDULED`, `NEEDS_REVIEW`, `ARCHIVED` |
| `SCHEDULED` | `PUBLISHED`, `PARTIALLY_PUBLISHED`, `READY`, `FAILED` |
| `PARTIALLY_PUBLISHED` | `PUBLISHED`, `SCHEDULED`, `FAILED` |
| `FAILED` | `IDEA`, `ARCHIVED` |
| `PUBLISHED` | `ARCHIVED` |
| `ARCHIVED` | none (terminal) |

Failed content restarts at `IDEA` so prior artifacts cannot skip validation gates. Publishing integrations are not implemented by this transition endpoint; callers must only request `PUBLISHED` or `PARTIALLY_PUBLISHED` after an authorized platform workflow verifies remote publication. This state machine is a domain guard, not evidence of a live publish. Live database concurrency behavior remains unverified until PostgreSQL integration tests are available.
