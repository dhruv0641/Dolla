# Observed credit ledger and reconciliation

## Application boundary

`CreditBalanceObservationProvider` is an injected provider contract. The repository does not infer balances from a quote, a generated asset, a logged-in browser, model prices, or user-submitted values. No credit balance or reconciliation operation is currently exposed by the observed Google Flow MCP manifest. The API starts with no provider configured; reconciliation returns `credit_observation_unavailable` after verifying account ownership. The ledger read route is available when a database is configured.

The provider receives an opaque local account reference and a caller-generated request UUID only after an owner-scoped preflight. Evidence must echo both values and contain nonnegative integer daily/monthly availability, an aware observation timestamp, and optional reset/cycle timestamps. The service rejects future, stale, mismatched, partial, and malformed evidence. The repository repeats owner scoping while locking the account row and rechecks freshness after any lock wait, immediately before writes.

## Ledger semantics and idempotency

- `credit_delta` is `available_after - available_before`: positive means more available credits, negative means fewer.
- The first observation is a baseline because the prior balance is unknown; its delta is zero and the absolute observed balance is stored in `details.available_after`.
- Every reconciliation writes one `DAILY` and one `MONTHLY` `RECONCILE` entry with source `FLOW_OBSERVED` and updates both account snapshots in the same transaction.
- `details` retain before/after balances, observation time and the previous/new reset or cycle boundaries. Reset-related balance changes remain visible as observed differences; they are not treated as generation spend.
- Keys are account-scoped and deterministic: `reconcile:{request_id}:{wallet}`. A fingerprint binds the key to the returned observation. Exact retries return the original pair; reuse with changed or partial evidence conflicts.
- Migration `0004_observed_credit_ledger.sql` assigns unique `legacy:{entry_uuid}` keys to existing entries before adding account-scoped uniqueness.

Reconciliation updates observed wallet values only. It does not settle, release, or expire reservations. Aggregate wallet deltas cannot prove which generation job consumed credits or whether an unknown job spent anything; uncertain reservations remain held until a future path receives per-operation evidence.

## Operations and verification limits

Use `POST /api/v1/flow-accounts/{account_id}/credit-reconciliations` with a fresh UUID request ID to trigger the configured trusted provider. The response contains the two ledger entries. `GET /api/v1/flow-accounts/{account_id}/credit-entries?limit=100` lists the latest owner-scoped entries; the limit is 1–200. Foreign and missing account IDs share a generic 404. Provider data and exceptions are never echoed to callers.

The default deployment has no observation provider. Unit tests use synthetic provider evidence and database fakes; PostgreSQL execution and live Flow credit reconciliation have not been verified. Do not configure a provider until the capability, identity binding, timestamp semantics and wallet meanings have been independently verified. Reconciliation never spends credits, connects accounts, or calls media generation.
