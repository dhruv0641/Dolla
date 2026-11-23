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
        self.assertEqual(sql.count("rja.artifact_role = 'EXPORT_VARIANT'"), 2)
        self.assertNotIn("rja.artifact_role = 'FINAL_VIDEO'", sql)
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

    def test_recommendations_and_experiments_are_evidence_bound_and_inert(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0026_evidence_recommendations_experiments.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE analytics_recommendations", sql)
        self.assertIn("CREATE TABLE analytics_experiment_proposals", sql)
        self.assertIn("cohort_analysis_request_report_identity", sql)
        self.assertIn("report_status IS DISTINCT FROM 'DESCRIPTIVE'", sql)
        self.assertIn("eligible_count < 2", sql)
        self.assertIn("NEW.recommendation_data->'sources' IS DISTINCT FROM report_data->'sources'", sql)
        self.assertIn("NEW.recommendation_data->'disclosed_cohorts' IS DISTINCT FROM report_data->'cohorts'", sql)
        self.assertIn("DESCRIPTIVE_ASSOCIATION_ONLY_NOT_CAUSAL_NO_GUARANTEED_WINNER", sql)
        self.assertIn("single_variable text NOT NULL", sql)
        self.assertIn("CHECK (control_target_size = treatment_target_size)", sql)
        self.assertIn("FIXED_SAMPLE_NO_EARLY_EFFICACY_STOP", sql)
        self.assertIn("PAUSE_ON_UNKNOWN_AUTH_JOB_OR_SPEND_STATE", sql)
        self.assertIn("NEW.proposal_data->'human_approval_required' IS DISTINCT FROM 'true'::jsonb", sql)
        self.assertIn("NEW.proposal_data->'execution_authorized' IS DISTINCT FROM 'false'::jsonb", sql)
        self.assertIn("NEW.proposal_data->'generation_authorized' IS DISTINCT FROM 'false'::jsonb", sql)
        self.assertIn("NEW.proposal_data->'spend_authorized' IS DISTINCT FROM 'false'::jsonb", sql)
        self.assertIn("NEW.proposal_data->'account_connection_authorized' IS DISTINCT FROM 'false'::jsonb", sql)
        self.assertIn("NEW.proposal_data->'upload_authorized' IS DISTINCT FROM 'false'::jsonb", sql)
        self.assertIn("NEW.proposal_data->'publishing_authorized' IS DISTINCT FROM 'false'::jsonb", sql)
        self.assertIn("jsonb_object_keys(NEW.recommendation_data)) <> 25", sql)
        self.assertIn("jsonb_object_keys(NEW.proposal_data)) <> 30", sql)
        self.assertIn("recommendation and experiment evidence is immutable", sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON analytics_recommendations", sql)
        self.assertIn("BEFORE UPDATE OR DELETE ON analytics_experiment_proposals", sql)
        self.assertIn("Legacy unverified table", sql)

    def test_feedback_loop_is_approval_spend_and_outcome_gated(self):
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0027_spend_aware_feedback_loop.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE analytics_feedback_gates", sql)
        self.assertIn("CREATE TABLE analytics_feedback_outcomes", sql)
        self.assertIn("CREATE TABLE analytics_feedback_approval_attestations", sql)
        self.assertIn("CREATE TABLE analytics_feedback_approval_revocations", sql)
        self.assertIn("operation text CHECK (operation IN ('video_generate'))", sql)
        self.assertIn("source_operation text", sql)
        self.assertIn("CREATE ROLE flowx_feedback_attestation_writer NOLOGIN", sql)
        self.assertIn("CREATE ROLE flowx_feedback_gate_runtime NOLOGIN", sql)
        self.assertIn("SECURITY DEFINER", sql)
        self.assertIn("persist_feedback_approval_attestation", sql)
        self.assertIn("persist_feedback_approval_revocation", sql)
        self.assertIn("TO flowx_feedback_attestation_writer", sql)
        self.assertIn("GRANT INSERT ON analytics_feedback_gates, analytics_feedback_outcomes", sql)
        self.assertIn("flow_credit_reservation_exact_identity", sql)
        self.assertIn("session_health", sql)
        self.assertIn("account_health IS DISTINCT FROM 'HEALTHY'", sql)
        self.assertIn("account_paused", sql)
        self.assertIn("NOT account_compliance", sql)
        self.assertIn("reservation_state IS DISTINCT FROM 'RESERVED'", sql)
        self.assertIn("NEW.quoted_credits > NEW.maximum_credits", sql)
        self.assertIn("requested_at')::timestamptz > NEW.approved_at", sql)
        self.assertIn("decision_now := clock_timestamp()", sql)
        self.assertIn("reservation_expiry <= decision_now", sql)
        self.assertIn("reconciled_at < decision_now - interval '15 minutes'", sql)
        self.assertIn("active_count > account_max_inflight", sql)
        self.assertIn("active_credits > observed_daily", sql)
        self.assertIn("human_kind IS DISTINCT FROM 'HUMAN_EXPERIMENT'", sql)
        self.assertIn("spend_kind IS DISTINCT FROM 'SPEND'", sql)
        self.assertIn("NEW.approved_at < human_verified", sql)
        self.assertIn("NEW.approved_at < spend_verified", sql)
        self.assertIn("analytics_feedback_approval_revocations", sql)
        self.assertIn("flow_credit_alarms", sql)
        self.assertIn("state = 'OPEN'", sql)
        self.assertIn("APPROVED_PENDING_FRESH_EXECUTOR_REVALIDATION", sql)
        self.assertIn("separate_executor_must_revalidate_exact_reservation", sql)
        self.assertIn("NEW.gate_data->'execution_authorized' IS DISTINCT FROM 'false'::jsonb", sql)
        self.assertIn("jsonb_object_keys(NEW.gate_data)) <> 26", sql)
        self.assertIn("NEW.gate_data->'automatic_execution' IS DISTINCT FROM 'false'::jsonb", sql)
        self.assertIn("NEW.gate_data->'publishing_authorized' IS DISTINCT FROM 'false'::jsonb", sql)
        self.assertIn("report_created < gate_approved", sql)
        self.assertIn("metadata.created_at < gate_approved", sql)
        self.assertIn("observation.published_at <= gate_approved", sql)
        self.assertIn("observation.window_started_at <= gate_approved", sql)
        self.assertIn("observation.observed_at <= gate_approved", sql)
        self.assertIn("DESCRIPTIVE_FEEDBACK_ONLY_NOT_CAUSAL", sql)
        self.assertIn("new_recommendation_requires_separate_human_review", sql)
        self.assertIn("causal_claim_authorized", sql)
        self.assertIn("feedback gate and outcome evidence is immutable", sql)
        self.assertIn("REVOKE INSERT, UPDATE, DELETE ON analytics_feedback_gates FROM PUBLIC", sql)

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

    def test_comment_ingestion_is_authorized_bounded_idempotent_and_immutable(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0028_authorized_comment_ingestion.sql"
        )
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE comment_ingestion_runs", sql)
        self.assertIn("CREATE TABLE comment_ingestion_attempts", sql)
        self.assertIn("CREATE TABLE comment_ingestion_batches", sql)
        self.assertIn("CREATE TABLE community_comment_versions", sql)
        self.assertIn("CREATE VIEW community_comments_current", sql)
        self.assertIn("uq_comment_ingestion_active_publication", sql)
        self.assertIn("UNIQUE (sync_id, page_index)", sql)
        self.assertIn("verdict = 'IN_SYNC'", sql)
        self.assertIn("remote_state = 'PUBLISHED'", sql)
        self.assertIn("ch.permissions_status", sql)
        self.assertIn("expected_comment_ingestion_target", sql)
        self.assertIn("comment ingestion reservation is invalid", sql)
        self.assertIn("comment ingestion batch evidence is invalid", sql)
        self.assertIn("comment ingestion batch is incomplete at commit", sql)
        self.assertIn("comment_remote_ids", sql)
        self.assertIn("newer.observed_at > r.observed_at", sql)
        self.assertIn("authorization_fingerprint", sql)
        self.assertIn("youtube.readonly", sql)
        self.assertIn("instagram_business_manage_comments", sql)
        self.assertIn("pages_read_engagement", sql)
        self.assertIn("attempt_count = OLD.attempt_count + 1", sql)
        self.assertIn("status = 'ABANDONED'", sql)
        self.assertIn("comment ingestion run abandonment is invalid", sql)
        self.assertIn("!~ '[[:cntrl:]]'", sql)
        self.assertIn("community comment version evidence is invalid", sql)
        self.assertIn("author_external_id_hash", sql)
        self.assertIn("state = 'DELETED'", sql)
        self.assertIn("comment ingestion evidence is immutable", sql)
        self.assertIn("REVOKE ALL ON community_comment_versions FROM PUBLIC", sql)

    def test_community_analysis_is_source_bound_deterministic_and_inert(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0029_community_theme_safety_analysis.sql"
        )
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE community_analysis_reports", sql)
        self.assertIn("CREATE TABLE community_comment_classifications", sql)
        self.assertIn("CREATE TABLE community_theme_clusters", sql)
        self.assertIn("expected_community_classification", sql)
        self.assertIn("community_comments_current", sql)
        self.assertIn("ORDER BY r.created_at DESC, r.sync_id DESC", sql)
        self.assertIn("FOR UPDATE OF p", sql)
        self.assertIn("run_value.status <> 'COMPLETE'", sql)
        self.assertIn("community-theme-v1", sql)
        self.assertIn("community-safety-v1", sql)
        self.assertIn("NO_DETECTED_SIGNAL", sql)
        self.assertIn("PROMPT_INJECTION", sql)
        self.assertIn("SELF_HARM", sql)
        self.assertIn("safety.personal_data", sql)
        self.assertIn("source_snapshot_fingerprint", sql)
        self.assertIn("outbound_action_authorized = false", sql)
        self.assertIn("CHECK (created_at = requested_at)", sql)
        self.assertIn("NEW.requested_at > clock_timestamp()", sql)
        self.assertIn("community analysis evidence is incomplete at commit", sql)
        self.assertIn("community analysis evidence is immutable", sql)
        self.assertIn("REVOKE ALL ON community_analysis_reports FROM PUBLIC", sql)

    def test_reply_drafts_are_classification_bound_escalated_and_inert(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0030_community_reply_drafts_escalation.sql"
        )
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE community_reply_draft_records", sql)
        self.assertIn("expected_community_reply_draft", sql)
        self.assertIn("community_analysis_reports", sql)
        self.assertIn("community_comment_classifications", sql)
        self.assertIn("community_comments_current", sql)
        self.assertIn("FOR UPDATE OF p", sql)
        self.assertIn("DRAFT_REQUIRES_HUMAN_APPROVAL", sql)
        self.assertIn("ESCALATED_NO_DRAFT", sql)
        self.assertIn("CONTENT_UNAVAILABLE_NO_DRAFT", sql)
        self.assertIn("safety_category_value <> 'NO_DETECTED_SIGNAL'", sql)
        self.assertIn("safety_severity_value = 'CRITICAL'", sql)
        self.assertIn("human_approval_required = true", sql)
        self.assertIn("outbound_action_authorized = false", sql)
        self.assertIn("community reply draft evidence is invalid", sql)
        self.assertIn("community reply draft evidence is immutable", sql)
        self.assertIn("REVOKE ALL ON community_reply_draft_records FROM PUBLIC", sql)

    def test_official_responses_require_exact_approval_reservation_and_remote_proof(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0031_community_human_approval_official_responses.sql"
        )
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE community_response_approvals", sql)
        self.assertIn("CREATE TABLE community_official_responses", sql)
        self.assertIn("reviewer_role IN ('admin','reviewer')", sql)
        self.assertIn("flowx_community_approval_writer", sql)
        self.assertIn("flowx_community_response_runtime", sql)
        self.assertIn("record_community_response_approval", sql)
        self.assertIn("lock_community_response_publication", sql)
        self.assertIn("SECURITY DEFINER", sql)
        self.assertIn("draft.disposition <> 'DRAFT_REQUIRES_HUMAN_APPROVAL'", sql)
        self.assertIn("community_comments_current", sql)
        self.assertIn("WHERE p.id = NEW.publication_id FOR UPDATE", sql)
        self.assertIn("MUTATION_RESERVED", sql)
        self.assertIn("youtube.force-ssl", sql)
        self.assertIn("instagram_business_manage_comments", sql)
        self.assertIn("pages_manage_engagement", sql)
        self.assertIn("recovery_evidence_id", sql)
        self.assertIn("NEW.identity_recovered_at <= OLD.mutation_reserved_at", sql)
        self.assertIn("COALESCE(NEW.identity_recovered_at, NEW.mutation_reserved_at)", sql)
        self.assertIn("verification_fingerprint", sql)
        self.assertIn("verification_parent_comment_id", sql)
        self.assertIn("expected_authorization", sql)
        self.assertIn("expected_receipt", sql)
        self.assertIn("interval '300 seconds'", sql)
        self.assertIn("interval '30 seconds'", sql)
        self.assertIn("official response authorization refresh is invalid", sql)
        self.assertIn("NEW.verification_visible IS DISTINCT FROM true", sql)
        self.assertIn("official response state transition is invalid", sql)
        self.assertIn("response approval is immutable", sql)
        self.assertIn("REVOKE ALL ON community_official_responses FROM PUBLIC", sql)


if __name__ == "__main__":
    unittest.main()
