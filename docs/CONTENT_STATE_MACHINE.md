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
| `SCHEDULED` | `READY`, `FAILED` |
| `PARTIALLY_PUBLISHED` | `SCHEDULED`, `FAILED` |
| `FAILED` | `IDEA`, `ARCHIVED` |
| `PUBLISHED` | `ARCHIVED` |
| `ARCHIVED` | none (terminal) |

The generic transition API has no incoming edge to `PUBLISHED` or `PARTIALLY_PUBLISHED`. Only a future trusted publishing workflow may set those outcomes after it records verified remote publication evidence; generic operators cannot claim publication through this endpoint. Failed content restarts at `IDEA` so prior artifacts cannot skip validation gates. Live database concurrency behavior remains unverified until PostgreSQL integration tests are available.
