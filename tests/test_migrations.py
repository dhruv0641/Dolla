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

    def test_render_versions_have_leases_retries_and_same_content_artifacts(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0012_render_versions_and_artifacts.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("plan_fingerprint char(64)", sql)
        self.assertIn("render_jobs_lease_shape", sql)
        self.assertIn("CREATE TABLE render_job_artifacts", sql)
        self.assertIn("CREATE UNIQUE INDEX idx_render_job_one_final", sql)
        self.assertIn("require_render_artifact_lineage", sql)
        self.assertIn("asset_content <> job_content", sql)
        self.assertIn("require_render_final_same_content", sql)
        self.assertIn("render final asset is not registered for this job", sql)

    def test_integrity_qa_reports_are_owner_visible_immutable_evidence(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0013_integrity_qa_reports.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE UNIQUE INDEX idx_qa_reports_asset_version", sql)
        self.assertIn("WHERE version = 'integrity-v1'", sql)
        self.assertIn("require_qa_report_asset_lineage", sql)
        self.assertIn("asset_kind NOT IN ('FINAL_VIDEO', 'EXPORT_VARIANT')", sql)
        self.assertIn("NEW.version <> 'integrity-v1'", sql)
        self.assertIn("prevent_integrity_qa_report_mutation", sql)
        self.assertIn("IF TG_OP = 'UPDATE' AND NEW.version = 'integrity-v1'", sql)

    def test_visual_audio_reports_require_passing_integrity_and_are_immutable(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0014_visual_audio_qa_reports.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE UNIQUE INDEX idx_qa_reports_asset_av_version", sql)
        self.assertIn("WHERE version = 'av-v1'", sql)
        self.assertIn("require_av_report_lineage", sql)
        self.assertIn("integrity.version = 'integrity-v1'", sql)
        self.assertIn("integrity.decision = 'PASS'", sql)
        self.assertIn("visual/audio QA blocker envelope is invalid", sql)
        self.assertIn("visual/audio QA finding envelope is invalid", sql)
        self.assertIn("visual/audio QA decision does not match findings", sql)
        self.assertIn("prevent_av_report_mutation", sql)

    def test_policy_signal_reports_require_passing_av_and_are_immutable(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0015_policy_factuality_copyright_signals.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE UNIQUE INDEX idx_qa_reports_asset_signals_version", sql)
        self.assertIn("WHERE version = 'signals-v1'", sql)
        self.assertIn("require_policy_signal_lineage", sql)
        self.assertIn("av.version = 'av-v1'", sql)
        self.assertIn("av.decision = 'PASS'", sql)
        self.assertIn("policy signal QA blocker envelope is invalid", sql)
        self.assertIn("policy signal QA decision does not match findings", sql)
        self.assertIn("policy signal QA copyright availability is invalid", sql)
        self.assertIn("policy signal QA state does not match findings", sql)
        self.assertIn("policy signal QA review disposition is invalid", sql)
        self.assertIn("prevent_policy_signal_report_mutation", sql)

    def test_scene_retry_decisions_require_immutable_spend_gate_evidence(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0016_scene_retry_spend_gate.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("retry_gate_decision", sql)
        self.assertIn("retry_credit_reservation_id", sql)
        self.assertIn("idx_generation_jobs_retry_reservation", sql)
        self.assertIn("require_scene_retry_spend_gate", sql)
        self.assertIn("reservation_state IS DISTINCT FROM 'RESERVED'", sql)
        self.assertIn("reservation_owner IS DISTINCT FROM scene_owner", sql)
        self.assertIn("prevent_scene_retry_gate_mutation", sql)
        self.assertIn("attempt_index < retry_max_attempts", sql)
        self.assertIn("IF TG_OP = 'DELETE' AND OLD.retry_gate_decision IS NOT NULL", sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON generation_jobs", sql)
        self.assertIn("require_scene_retry_claim_gate", sql)
        self.assertIn("prior_reservation IS DISTINCT FROM NEW.credit_reservation_id", sql)
        self.assertIn("reservation_account IS DISTINCT FROM claimed_account", sql)
        self.assertIn("NEW.attempt_index > prior_max_attempts", sql)
        self.assertIn("IF TG_OP = 'UPDATE' AND OLD.retry_gate_decision IS NOT NULL", sql)
        self.assertLess(sql.index("SELECT id INTO claimed_account"), sql.index("SELECT status, retry_scheduled"))
        self.assertLess(sql.index("SELECT flow_account_id INTO reservation_account"),
                        sql.index("SELECT status, retry_scheduled"))

    def test_human_review_decisions_bind_evidence_transition_and_immutability(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0017_human_review_decisions.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("idx_review_decisions_request_v1", sql)
        self.assertIn("idx_review_decisions_qa_report_v1", sql)
        self.assertIn("require_human_review_evidence", sql)
        self.assertIn("q.id = NEW.qa_report_id", sql)
        self.assertIn("qa_decision = 'FAIL' OR jsonb_array_length(qa_blockers) > 0", sql)
        self.assertIn("NEW.approval_scope, COALESCE(NEW.revision_target, ''), NEW.reason", sql)
        self.assertIn("content_owner IS DISTINCT FROM NEW.reviewer_user_id", sql)
        self.assertIn("NEW.reason IS DISTINCT FROM btrim(NEW.reason)", sql)
        self.assertIn("UPDATE content_items SET status = next_status", sql)
        self.assertIn("prevent_human_review_mutation", sql)
        self.assertIn("RAISE EXCEPTION 'human review decisions are immutable'", sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON review_decisions", sql)

    def test_youtube_publications_require_approved_artifact_and_remote_verification(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0018_youtube_publication_verification.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("idx_publication_jobs_request_v1", sql)
        self.assertIn("channel_external_id_snapshot", sql)
        self.assertIn("credentials_ref_snapshot", sql)
        self.assertIn("YouTube destination fingerprint is invalid", sql)
        self.assertIn("approval_decision_id uuid REFERENCES review_decisions(id)", sql)
        self.assertIn("require_youtube_publication_claim", sql)
        self.assertIn("rja.profile_id", sql)
        self.assertIn("YOUTUBE_SHORTS_V1", sql)
        self.assertIn("rd.decision", sql)
        self.assertIn("guard_youtube_publication_transition", sql)
        self.assertIn("remote_upload_status IS DISTINCT FROM 'processed'", sql)
        self.assertIn("remote_processing_status IS DISTINCT FROM 'succeeded'", sql)
        self.assertIn("remote_privacy_status IS DISTINCT FROM NEW.intended_privacy_status", sql)
        self.assertIn("remote_channel_id IS DISTINCT FROM NEW.channel_external_id_snapshot", sql)
        self.assertNotIn("ch.external_channel_id = remote_channel_id", sql)
        self.assertIn("terminal YouTube publication state is immutable", sql)
        self.assertIn("YouTube remote identities are immutable once observed", sql)
        self.assertIn("OLD.status = 'DRAFT' AND NEW.status = 'PUBLISH_REQUESTED'", sql)
        self.assertIn("YouTube upload start reservation must be pristine", sql)
        self.assertIn("NEW.last_remote_status <> '{}'::jsonb", sql)
        self.assertIn("YouTube verification pending cannot introduce remote identity", sql)
        self.assertIn("failed YouTube publication requires an error code", sql)
        self.assertIn("YouTube publication evidence is immutable", sql)


if __name__ == "__main__":
    unittest.main()
