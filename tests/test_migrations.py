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

    def test_platform_reconciliation_is_versioned_idempotent_and_immutable(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0021_platform_publication_reconciliation.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("publication_state_version bigint NOT NULL DEFAULT 0", sql)
        self.assertIn("NEW.publication_state_version := OLD.publication_state_version + 1", sql)
        self.assertIn("CREATE TABLE publication_reconciliations", sql)
        self.assertIn("CREATE TABLE publication_reconciliation_attempts", sql)
        self.assertIn("UNIQUE (publication_id, attempt_index)", sql)
        self.assertIn("request_id uuid NOT NULL UNIQUE", sql)
        self.assertIn("CHECK (requires_human_review = (verdict <> 'IN_SYNC'))", sql)
        self.assertIn("expected_publication_reconciliation_verdict", sql)
        self.assertIn("publication_reconciliations_require_evidence", sql)
        self.assertIn("attempt_status IS DISTINCT FROM 'RESERVED'", sql)
        self.assertIn("ch.external_channel_id = p.channel_external_id_snapshot", sql)
        self.assertIn("ch.credentials_ref = p.credentials_ref_snapshot", sql)
        self.assertIn("publication reconciliation history is immutable", sql)
        self.assertIn("publication_reconciliations_prevent_update", sql)
        self.assertIn("publication_reconciliations_prevent_delete", sql)

    def test_publication_delivery_requires_exact_approval_and_atomic_reservation(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0022_publication_approval_schedule_duplicate_prevention.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE publication_delivery_approvals", sql)
        self.assertIn("owner_user_id = approver_user_id", sql)
        self.assertIn("publication delivery approvals are immutable", sql)
        self.assertIn("CREATE TABLE publication_delivery_reservations", sql)
        self.assertIn("UNIQUE (content_id, platform, channel_id, artifact_version)", sql)
        self.assertIn("FOR UPDATE OF p, ch", sql)
        self.assertIn("date_trunc('day', NEW.local_scheduled_at)", sql)
        self.assertIn("current_remote_upload IS NOT NULL", sql)
        self.assertIn("pr.requires_human_review = true", sql)
        self.assertIn("reserve_due_publication_delivery", sql)
        self.assertIn("state = 'DISPATCH_RESERVED', dispatch_reserved_at = now()", sql)
        self.assertIn("publication_jobs_require_due_delivery", sql)

    def test_metric_observations_are_owner_scoped_idempotent_and_immutable(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0023_platform_metric_observations.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE analytics_metric_collection_attempts", sql)
        self.assertIn("CREATE TABLE analytics_metric_observations", sql)
        self.assertIn("CREATE TABLE analytics_metric_registries", sql)
        self.assertIn("CREATE TABLE analytics_metric_definitions", sql)
        self.assertIn("BEFORE INSERT OR UPDATE OR DELETE ON analytics_metric_definitions", sql)
        self.assertIn("platform = 'YOUTUBE' AND metric_id LIKE 'youtube.%'", sql)
        self.assertIn("definition.metric_unit = 'COUNT'", sql)
        self.assertIn("NEW.observation_fingerprint := encode(digest", sql)
        self.assertIn("pg_column_size(metric_data) <= 65536", sql)
        self.assertIn("request_id uuid NOT NULL UNIQUE", sql)
        self.assertIn("p.status", sql)
        self.assertIn("channel_credentials_match", sql)
        self.assertIn("window_started_at = published_at", sql)
        self.assertIn("observed_at >= window_ended_at", sql)
        self.assertIn("FIELD_NOT_RETURNED", sql)
        self.assertIn("analytics metric observations are immutable", sql)
        self.assertIn("analytics_metric_observations_prevent_update", sql)
        self.assertIn("analytics_metric_observations_prevent_delete", sql)

    def test_windowed_snapshots_have_one_persisted_identity(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0024_windowed_snapshot_identity.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE UNIQUE INDEX analytics_metric_snapshot_identity", sql)
        self.assertIn("publication_id, window_name, registry_version, metric_ids", sql)

    def test_creative_cohorts_are_owner_scoped_versioned_and_immutable(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0025_creative_metadata_cohort_analysis.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE creative_metadata_snapshots", sql)
        self.assertIn("CREATE FUNCTION creative_metadata_source_fingerprint", sql)
        self.assertIn("c.script_version", sql)
        self.assertIn("rja.asset_id = p.asset_id", sql)
        self.assertIn("rj.render_version = p.artifact_version", sql)
        self.assertIn("tts.asset_id::text IN", sql)
        self.assertIn("asset.id::text IN", sql)
        self.assertIn("NEW.source_fingerprint IS DISTINCT FROM expected_source_fingerprint", sql)
        self.assertIn("creative metadata snapshot fingerprint is invalid", sql)
        self.assertIn("UNIQUE (publication_id, schema_version)", sql)
        self.assertIn("jsonb_array_length(factors) = 13", sql)
        self.assertIn("FOR SHARE OF p, c, b, ch, sv", sql)
        self.assertIn("creative metadata snapshot evidence is invalid", sql)
        self.assertIn("CREATE TABLE cohort_analysis_reports", sql)
        self.assertIn("CREATE TABLE cohort_analysis_sources", sql)
        self.assertIn("cohort_analysis_sources_require_evidence", sql)
        self.assertIn("cohort_analysis_reports_complete_sources", sql)
        self.assertIn("cohort analysis typed sources are incomplete", sql)
        self.assertIn("cohort analysis summary does not match typed sources", sql)
        self.assertIn("NEW.request_fingerprint IS DISTINCT FROM expected_request_fingerprint", sql)
        self.assertIn("NEW.report_fingerprint IS DISTINCT FROM expected_report_fingerprint", sql)
        self.assertIn("WITH ORDINALITY", sql)
        self.assertIn("current_published_at AT TIME ZONE 'UTC'", sql)
        self.assertIn("jsonb_array_length(NEW.report_data->'exclusions') <> 5", sql)
        self.assertIn("DESCRIPTIVE_ASSOCIATION_ONLY_NOT_CAUSAL", sql)
        self.assertIn("analytics_metric_definitions", sql)
        self.assertIn("cohort analysis source lineage is invalid", sql)
        self.assertIn("creative cohort evidence is immutable", sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON creative_metadata_snapshots", sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON cohort_analysis_reports", sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON cohort_analysis_sources", sql)

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

    def test_instagram_reels_have_two_mutation_barriers_and_remote_proof(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0019_instagram_reels_publication_verification.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("publication_contract = 'INSTAGRAM_REELS_V1'", sql)
        self.assertIn("media_source_ref_snapshot", sql)
        self.assertIn("INSTAGRAM_REELS_V1", sql)
        self.assertIn("require_instagram_publication_claim", sql)
        self.assertIn("rd.decision", sql)
        self.assertIn("CONTAINER_RESERVED", sql)
        self.assertIn("PUBLISH_RESERVED", sql)
        self.assertIn("MEDIA_ID_UNKNOWN", sql)
        self.assertIn("Instagram remote identities are immutable once observed", sql)
        self.assertIn("Instagram publishable container evidence is invalid", sql)
        self.assertIn("Instagram unknown media evidence is invalid", sql)
        self.assertIn("'EXPIRED','ERROR','FINISHED','IN_PROGRESS','PUBLISHED'", sql)
        self.assertIn("container_state IS DISTINCT FROM 'PUBLISHED'", sql)
        self.assertIn("owner_id IS DISTINCT FROM NEW.channel_external_id_snapshot", sql)
        self.assertIn("media_type_value IS DISTINCT FROM 'VIDEO'", sql)
        self.assertIn("terminal Instagram publication state is immutable", sql)
        self.assertIn("Instagram publication evidence is immutable", sql)

    def test_facebook_reels_have_three_mutation_barriers_and_remote_proof(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0020_facebook_reels_publication_verification.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("publication_contract = 'FACEBOOK_REELS_V1'", sql)
        self.assertIn("require_facebook_publication_claim", sql)
        self.assertIn("FACEBOOK_REELS_V1", sql)
        self.assertIn("rd.decision", sql)
        self.assertIn("START_RESERVED", sql)
        self.assertIn("UPLOAD_RESERVED", sql)
        self.assertIn("PUBLISH_RESERVED", sql)
        self.assertIn("UNEXPECTED_SCHEDULED_REEL", sql)
        self.assertIn("PUBLISH_RECEIPT_UNKNOWN", sql)
        self.assertIn("Facebook start reservation must be pristine", sql)
        self.assertIn("Facebook remote identities are immutable once observed", sql)
        self.assertIn("Facebook publishable video evidence is invalid", sql)
        self.assertIn("video_status' IS DISTINCT FROM 'ready'", sql)
        self.assertIn("publish_status' IS DISTINCT FROM 'published'", sql)
        self.assertIn("page_id_value IS DISTINCT FROM NEW.channel_external_id_snapshot", sql)
        self.assertIn("terminal Facebook publication state is immutable", sql)
        self.assertIn("Facebook publication claim evidence is immutable", sql)
        self.assertIn("prevent_facebook_publication_delete", sql)


if __name__ == "__main__":
    unittest.main()
