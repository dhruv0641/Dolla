# Credit quotes and reservations

## Current boundary

The reservation service is an injected application capability. It first verifies that the requested account belongs to the authenticated owner, before disclosing its reference to a quote or approval provider. It requires all of the following before it writes a reservation:

1. A typed quote provider returns a quote bound to the requested account, request ID, model, and duration.
2. The quote is positive, current, not expired, and under the configured per-request credit ceiling.
3. A trusted `SpendAuthorizationVerifier` confirms an explicit approval reference for the same account and `VIDEO_GENERATE` operation with a ceiling at least as large as the quote.
4. The account is owner-scoped, healthy, unpaused, compliance-approved, and has fresh observed daily and monthly credit balances.
5. The account's active reservation count and both observed wallet limits permit the reservation under a row lock.

The API has no quote provider, spend verifier, or credit ceiling wired by default. The endpoint therefore fails closed with `credit_quote_unavailable`. The inspected Google Flow MCP capability manifest exposes no stable credit quote, balance, or reconciliation operation. The proposed adapter contract is not runtime evidence. Do not configure a made-up quote, price, balance, or rate card.

## Transaction and idempotency behavior

`POST /api/v1/flow-accounts/{account_id}/credit-reservations` accepts an idempotency `request_id`, model, duration, and secret-wrapped approval reference. After owner preflight, persistence locks the owner-scoped account row and repeats the ownership check, counts `RESERVED` and `RECONCILE_PENDING` allocations, subtracts those allocations from both observed limits, and inserts at most one row per `(flow_account_id, request_id)`. A repeated ID returns the same active reservation only when its quote fingerprint matches; changed quotes and closed reservations conflict.

The repository rechecks quote age, expiry, and observed-balance freshness immediately before insertion while holding the account lock. Unknown or uncertain spend remains allocated as `RECONCILE_PENDING` until an explicit reconciliation path resolves it. This task does not add automatic expiry, release, settlement, balance refresh, or generation calls; those require later ledger/reconciliation work and verified provider evidence.

## Data and security handling

Approval references are accepted as `SecretStr` request fields and are never included in the response. Responses omit owner identifiers and credential references. Provider exceptions and database failures are mapped to stable API error codes. Quote references are bounded and reject control characters. No Flow cookies, credentials, or tokens are accepted by this API.

## Operational verification limits

Unit tests use in-memory provider, verifier, and database fakes. Migration syntax checks do not prove execution against PostgreSQL. No live Flow quote/balance, database migration, account activation, paid generation, or production integration is claimed. Configure a provider only after its capability and response semantics are independently verified; retain manual approval and fail-closed behavior until then.
