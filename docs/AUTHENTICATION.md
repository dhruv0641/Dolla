# Authentication and role model

The API accepts signed HS256 bearer JWTs only when a `TokenVerifier` has been explicitly injected into the FastAPI app. Verification requires a key of at least 256 bits resolved by deployment code from the configured secret store, exact issuer and audience, subject, expiration, optional not-before, and one or more supported roles (`admin`, `operator`, `reviewer`). Algorithm confusion, missing expiration, unknown roles, bad signatures, and expired/future tokens are rejected. Error responses never echo token data.

`current_principal` and `require_roles` are FastAPI dependencies. The sample identity route requires authentication; the admin access check requires the admin role. Liveness and readiness remain public for deployment probes. When no verifier is configured, protected routes fail with HTTP 503 rather than accepting unauthenticated access.

This work verifies tokens; it does not issue them, authenticate passwords, connect an identity provider, manage refresh tokens, or configure TLS. A deployment must obtain tokens from a trusted issuer, resolve the key reference without exposing key material, enforce HTTPS, configure issuer/audience, and protect the signing key. Do not use a shared HS256 key across untrusted token issuers. Use a vetted asymmetric identity-provider integration before multiple services or issuers are introduced.
