-- Make Flow account aliases owner-scoped to prevent cross-owner collision oracles.
-- The supplied baseline used a globally unique alias; move uniqueness to owner+alias.
ALTER TABLE flow_accounts DROP CONSTRAINT flow_accounts_alias_key;
ALTER TABLE flow_accounts
  ADD CONSTRAINT flow_accounts_owner_alias_key UNIQUE (owner_user_id, alias);
