# Flow account registry

The account registry stores an owner-scoped alias, a syntax-validated secret-store reference, and the adapter identifier for later operations. Reference existence and authorization are not verified. It never stores or returns a password, OAuth token, browser cookie, or credential reference value through the API response.

## API

- `POST /api/v1/flow-accounts` registers an account reference. Admin and operator roles are required.
- `GET /api/v1/flow-accounts` lists only the authenticated owner's accounts. Admin and operator roles are required.
- `POST /api/v1/flow-accounts/{account_id}/pause` idempotently pauses an owned account. The API has no unpause operation.
- The create body accepts a display alias, a `secretref://provider/path` reference, and the proposed contract's `google_flow_via_user_authorized_mcp` adapter identifier. Raw credential values and unknown adapter identifiers are rejected.
- Duplicate aliases for the same owner return the generic `flow_account_alias_unavailable` response. Migration `0002_flow_account_owner_alias.sql` scopes uniqueness to `(owner_user_id, alias)`, so owners cannot probe one another's aliases.
- Missing database configuration returns `database_not_configured`; storage failures return `database_unavailable` without driver details.

## Authorization and state

Every new record is persisted as `UNVERIFIED`, `paused=true`, and `compliance_approved=false`. Credit observations and plan limits remain unknown until reconciled. The API does not let a caller set health, compliance approval, or unpause an account by asserting a boolean. There is no activation endpoint until a verified health provider can prove the expected account identity and an authorized approval path is configured. `logged_in` alone is insufficient, and accounts remain unusable by the adapter while identity is unverified or the account is paused.

The list and create responses omit both `owner_user_id` and `credentials_ref`. Validation responses omit submitted input values so accidental token or personal-data submissions are not echoed. Request logs contain route metadata only, not request bodies.

## Limits

This registry is a persistence/API boundary, not a live Flow integration. The repository has no configured application transport, identity email evidence for the intended Flow account, or verified credit quote/balance interface. Registering a reference does not connect an account, authorize generation, change account posture, or consume credits. See `docs/FLOW_MCP_ADAPTER.md` and `docs/MCP_CAPABILITY_MATRIX.md` before implementing activation or spend paths.
