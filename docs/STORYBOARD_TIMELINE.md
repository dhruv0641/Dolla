# Versioned storyboard and scene timeline

## Contract

`StoryboardTimeline` is a strict, immutable request contract with a bounded title and 1–30 scenes. Every scene has a sequential number, start/end milliseconds, beat, narration, visual prompt and prompt version. Timelines start at zero, have positive scene durations, contain no gaps or overlaps, and stay within the 180-second content limit. The repository also requires the last scene end to equal the owning content item's target duration exactly.

## Persistence and concurrency

Migration `0007_versioned_storyboard_timeline.sql` stores immutable JSON snapshots in `storyboard_versions` and adds `storyboard_version` to scene rows. Uniqueness is scoped by content, storyboard version and scene number. Each save locks the owner-scoped content row, checks the caller's `expected_version`, verifies the timeline duration and lifecycle state, inserts the snapshot and all scene projections, then updates the current content version and state in the same transaction. Any failure rolls back the whole write. Existing scene IDs and their job/asset references remain untouched as new versions are added.

Stale writes return a conflict with the current version; malformed timelines return validation errors; versions can only be created from `SCRIPT_READY`, `NEEDS_REVIEW`, or an existing `STORYBOARD_READY` state. The first two transition to `STORYBOARD_READY`. Reads return only records scoped to the authenticated owner and brand.

## Routes

- `PUT /api/v1/brands/{brand_id}/content/{content_id}/storyboard` appends a version and requires `{ "expected_version": 0, "storyboard": ... }` for the initial version.
- `GET /api/v1/brands/{brand_id}/content/{content_id}/storyboard` returns the current snapshot.
- `GET /api/v1/brands/{brand_id}/content/{content_id}/storyboard/versions` returns the retained history in ascending version order.

The save route is restricted to admin/operator roles. Read routes permit admin, operator and reviewer roles. This capability persists supplied timelines; it does not call an AI provider, submit Flow jobs, or approve content. Fake-pool and schema tests cover repository behavior. Live PostgreSQL locking, migration execution and concurrent-request behavior have not been verified.
