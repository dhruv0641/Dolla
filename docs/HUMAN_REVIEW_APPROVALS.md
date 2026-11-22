# Human review and approvals

TASK-050 provides the only application boundary that can convert exact final-media QA evidence into a human lifecycle decision. It does not schedule, upload or publish media and does not connect any external account.

## Required evidence and authorization

- Only an authenticated `reviewer` or `admin` role can use the API. The authenticated subject must own the brand/content because the current data model has no delegated reviewer-membership table.
- The content must be in `NEEDS_REVIEW` and the asset must be an active, content-level `FINAL_VIDEO` or `EXPORT_VARIANT`.
- The decision names the exact immutable `signals-v1` report for that asset. The report must be automated QA evidence with `human_approval_required=true` and `content_approved=false`.
- `APPROVE` is rejected when the automated report is `FAIL` or contains any hard blocker. A human may resolve non-blocking `NEEDS_HUMAN` findings after inspecting the underlying evidence and recording a bounded reason.
- Reasons reject control/bidirectional characters and credential-like assignments. They remain human-authored audit text and must not contain secrets or unnecessary personal data.

## Decisions and state transitions

| Decision | Required target | Atomic content transition |
|---|---|---|
| `APPROVE` | none | `NEEDS_REVIEW` → `READY` |
| `CHANGES_REQUIRED` | `SCRIPT_READY` or `STORYBOARD_READY` | returns to the selected revision stage |
| `REJECT` | none | `NEEDS_REVIEW` → `ARCHIVED` |

The database trigger validates evidence, ownership and current state and applies the transition in the same transaction as the decision insert. One `request_id` and one signal report can identify at most one human decision. Exact request replays return the stored record; changed payloads conflict. The SHA-256 request fingerprint binds request/content/asset/report/reviewer/decision/scope/revision target and the normalized reason. Review-decision history is immutable and cannot be deleted, including any pre-migration audit rows.

`READY` means human QA approval only. It is not a schedule, publication approval for a particular platform, OAuth authorization, upload result or proof that remote content exists. TASK-057 through TASK-061 retain those official-interface and reconciliation responsibilities. Auto-publish remains off.

## API

`POST /api/v1/brands/{brand_id}/content/{content_id}/human-reviews`

The body contains `request_id`, `asset_id`, `qa_report_id`, `decision`, `reason`, and an optional `revision_target`. Foreign content is returned as not found; stale/ineligible evidence and conflicts use stable, value-free errors.

## Unverified boundaries

Tests use deterministic repository/API fakes and parse migration SQL. Live PostgreSQL trigger execution, concurrent reviewer contention, production identity delegation and human judgment quality remain unverified. No external service, paid action, Flow generation, account connection, scheduling or publishing was invoked for TASK-050.
