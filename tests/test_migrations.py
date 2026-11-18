import unittest
from pathlib import Path

from pglast import parse_sql


class MigrationSyntaxTests(unittest.TestCase):
    def test_initial_migration_parses_as_postgresql(self):
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        statements = [
            statement
            for migration in sorted(migrations.glob("*.sql"))
            for statement in parse_sql(migration.read_text(encoding="utf-8"))
        ]
        self.assertGreaterEqual(len(statements), 35)

    def test_initial_migration_contains_lineage_foreign_key(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0001_initial_schema.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("assets_source_job_fk", sql)

    def test_flow_account_alias_uniqueness_is_scoped_to_owner(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0002_flow_account_owner_alias.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("DROP CONSTRAINT flow_accounts_alias_key", sql)
        self.assertIn("UNIQUE (owner_user_id, alias)", sql)

    def test_credit_reservations_are_idempotent_and_hold_unknown_spend(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0003_flow_credit_reservations.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("UNIQUE (flow_account_id, request_id)", sql)
        self.assertIn("'RECONCILE_PENDING'", sql)
        self.assertIn("'RESERVED','RECONCILE_PENDING'", sql)

    def test_observed_credit_ledger_keys_entries_for_replay_safe_reconciliation(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0004_observed_credit_ledger.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("UPDATE flow_credit_entries", sql)
        self.assertIn("'legacy:' || id::text", sql)
        self.assertIn("UNIQUE INDEX idx_credit_entry_account_idempotency", sql)
        self.assertIn("flow_account_id, idempotency_key", sql)

    def test_unknown_spend_alarm_is_unique_and_bound_to_reservation(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0005_credit_risk_alarms.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE flow_credit_alarms", sql)
        self.assertIn("FOREIGN KEY (flow_account_id, request_id)", sql)
        self.assertIn("UNIQUE (flow_account_id, request_id, alarm_type)", sql)
        self.assertIn("created_by text NOT NULL", sql)
        self.assertIn("'OPEN'", sql)


if __name__ == "__main__":
    unittest.main()
