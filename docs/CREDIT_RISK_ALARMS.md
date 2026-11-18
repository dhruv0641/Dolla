# Credit-risk alarms and fail-closed controls

## Unknown-spend transition

When an operator determines that a reservation's spend outcome is uncertain, call `POST /api/v1/flow-accounts/{account_id}/credit-reservations/{request_id}/unknown-spend` with one of the allowlisted reason codes. The API derives the audit actor from the authenticated principal; callers cannot supply or override it. Trusted internal workflows must pass an explicit actor identifier to the service (use `system:credit-risk` for the system actor). The alarm row and workflow event persist the same actor. The handler locks the owner-scoped account first and then the reservation, preserving the same account-before-reservation order as credit reservation writes.

In one transaction, the repository sets the reservation to `RECONCILE_PENDING`, pauses the account, inserts one `UNKNOWN_SPEND` alarm, and appends a sanitized `credit.unknown_spend_detected` workflow event. The alarm key is unique per account/reservation. Exact repeats return the existing alarm; a changed reason or a closed reservation conflicts. Foreign accounts return the same generic 404 as absent accounts. The route accepts no free-form detail text and its response omits owner, credential, provider-payload and external-receipt fields.

`RECONCILE_PENDING` continues to count against both wallet limits and `max_inflight`. Account pause blocks new reservations. Existing reservations are not released or settled. Only a later, separately verified per-operation result may justify resolution; a timeout, aggregate balance change, or operator acknowledgement alone does not prove spend or non-spend. This task intentionally provides no resolve/unpause route.

## Operator visibility and alert delivery

`GET /api/v1/flow-accounts/{account_id}/credit-alarms?limit=100` lists the most recent open alarms for an owned account. The limit is 1–200 and the route permits admin, operator and reviewer roles. Alarm rows remain open until a verified resolution workflow is implemented. Review the referenced reservation and external job evidence before taking any recovery action; do not retry an external generation while job/spend state is unknown.

The durable alarm and workflow event are local application records. No email, Slack, pager, webhook, collector or other alert delivery is configured. Operators must inspect this endpoint or the database-backed workflow event records. No live Flow job state or PostgreSQL execution is claimed; tests use database fakes and parse migration SQL only.
