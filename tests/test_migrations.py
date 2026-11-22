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

    def test_generation_attempt_is_uniquely_bound_to_credit_reservation(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0006_generation_job_credit_reservation.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("REFERENCES flow_credit_reservations(id)", sql)
        self.assertIn("CREATE UNIQUE INDEX idx_generation_job_credit_reservation", sql)

    def test_storyboard_version_storage_and_scene_version_scoping(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0007_versioned_storyboard_timeline.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE storyboard_versions", sql)
        self.assertIn("UNIQUE (content_id, version)", sql)
        self.assertIn("storyboard_version", sql)
        self.assertIn("UNIQUE (content_id, storyboard_version, scene_index)", sql)

    def test_assets_require_consistent_content_scene_and_job_lineage(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0008_asset_lineage_integrity.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("assets_scene_content_fk", sql)
        self.assertIn("assets_job_scene_fk", sql)
        self.assertIn("assets_scene_requires_content", sql)
        self.assertIn("assets_sha256_hex_format", sql)

    def test_generation_attempts_persist_retry_decisions(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0009_scene_retry_decisions.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("retry_scheduled boolean NOT NULL DEFAULT false", sql)
        self.assertIn("CHECK (NOT retry_scheduled OR status = 'FAILED')", sql)

    def test_voice_profiles_and_synthesis_are_evidence_gated_and_idempotent(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0011_voice_profiles_and_synthesis.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE voice_profiles", sql)
        self.assertIn("source = 'LOCAL_BUILTIN'", sql)
        self.assertIn("license_status <> 'VERIFIED' OR license_reference IS NOT NULL", sql)
        self.assertIn("request_fingerprint char(64) NOT NULL UNIQUE", sql)
        self.assertIn("completed_asset_id = asset_id", sql)
        self.assertIn("CREATE TRIGGER voice_profile_immutable", sql)
        self.assertIn("OLD.active = false AND NEW.active = true", sql)


if __name__ == "__main__":
    unittest.main()
