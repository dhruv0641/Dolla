from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import unittest
from uuid import UUID

from pydantic import ValidationError

from flowx_os.db.render_jobs import (
    RenderArtifactRole,
    RenderArtifactSpec,
    RenderJobConflict,
    RenderJobRepository,
    RenderJobStatus,
    RenderVersionRequest,
)


JOB_ID = UUID("fabf036e-874c-44cd-996d-c1cd94a48c76")
BRAND_ID = UUID("79312d0e-6a03-4c1d-b850-22ea214d8a2e")
CONTENT_ID = UUID("1da8cf70-3f38-40c6-9ef2-0a26c9750ef1")
INPUT_ID = UUID("93b68f29-4b28-4a78-bb27-0c9db24fb62a")
FINAL_ID = UUID("9d421854-feef-4b77-ab7f-ab8335db2134")
EXPORT_ID = UUID("28fcb18d-3e3a-4ec3-8be1-f16957833363")
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, row=None, rows=None, rowcount=1):
        self.row = row
        self.rows = rows if rows is not None else []
        self.rowcount = rowcount

    async def fetchone(self):
        return self.row

    async def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, results=()):
        self.results = list(results)
        self.calls = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, query, params=None):
        self.calls.append((query, params))
        result = self.results.pop(0) if self.results else None
        if isinstance(result, FakeCursor):
            return result
        return FakeCursor(row=result)


class FakePool:
    def __init__(self, connection):
        self.connection_value = connection

    @asynccontextmanager
    async def connection(self):
        yield self.connection_value


def request(**updates):
    values = {
        "job_id": JOB_ID, "brand_id": BRAND_ID, "content_id": CONTENT_ID,
        "owner_user_id": "owner-1", "render_version": 1,
        "plan_fingerprint": "a" * 64,
        "inputs_manifest": {"asset_ids": [str(INPUT_ID)]},
        "command_manifest": {"schema_version": 1, "operation": "COMPOSE", "duration_ms": 1000},
    }
    values.update(updates)
    return RenderVersionRequest.model_validate(values)


def row(status="PENDING", *, attempts=0, lease_owner=None, lease_expires=None,
        final=None, error=None, started=None, finished=None, job_id=JOB_ID,
        inputs=None, command=None, fingerprint="a" * 64):
    return (
        job_id, CONTENT_ID, 1, status,
        inputs or {"asset_ids": [str(INPUT_ID)]},
        command or {"schema_version": 1, "operation": "COMPOSE", "duration_ms": 1000},
        fingerprint, attempts, lease_owner, lease_expires, final, error, NOW, started, finished,
    )


def repository(connection, max_attempts=3):
    return RenderJobRepository(
        FakePool(connection), now=lambda: NOW,
        lease_duration=timedelta(minutes=5), max_attempts=max_attempts,
    )


class RenderJobRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def test_request_rejects_noncanonical_duplicate_secret_and_nonfinite_manifests(self):
        with self.assertRaises(ValidationError):
            request(inputs_manifest={"asset_ids": [str(INPUT_ID).upper()]})
        with self.assertRaises(ValidationError):
            request(inputs_manifest={"asset_ids": [str(INPUT_ID), str(INPUT_ID)]})
        with self.assertRaises(ValidationError):
            request(command_manifest={"access_token": "do-not-store"})
        with self.assertRaises(ValidationError):
            request(command_manifest={"value": float("nan")})
        with self.assertRaises(ValidationError):
            request(command_manifest={"tuple": (1, 2)})

    def test_artifact_contract_requires_one_role_appropriate_profile(self):
        final = RenderArtifactSpec(asset_id=FINAL_ID, role=RenderArtifactRole.FINAL_VIDEO)
        export = RenderArtifactSpec(
            asset_id=EXPORT_ID, role=RenderArtifactRole.EXPORT_VARIANT,
            profile_id="YOUTUBE_SHORTS_V1",
        )
        self.assertIsNone(final.profile_id)
        self.assertEqual(export.profile_id, "YOUTUBE_SHORTS_V1")
        with self.assertRaises(ValidationError):
            RenderArtifactSpec(asset_id=EXPORT_ID, role=RenderArtifactRole.EXPORT_VARIANT)
        with self.assertRaises(ValidationError):
            RenderArtifactSpec(asset_id=FINAL_ID, role=RenderArtifactRole.FINAL_VIDEO, profile_id="PROFILE")

    async def test_create_inserts_after_owner_check_and_replays_exact_version(self):
        connection = FakeConnection([(1,), row()])
        created = await repository(connection).create_or_get(request())
        self.assertEqual((created.job_id, created.status), (JOB_ID, RenderJobStatus.PENDING))
        self.assertIn("owner_user_id", connection.calls[0][0])
        self.assertIn("ON CONFLICT (content_id, render_version) DO NOTHING", connection.calls[1][0])

        connection = FakeConnection([(1,), None, row()])
        existing = await repository(connection).create_or_get(request())
        self.assertEqual(existing.job_id, JOB_ID)
        self.assertIn("FOR UPDATE OF r", connection.calls[2][0])

    async def test_create_rejects_version_rebinding(self):
        other_job = UUID("b832a764-5b0a-458c-a5dc-7f871c27180b")
        connection = FakeConnection([(1,), None, row(job_id=other_job)])
        with self.assertRaises(RenderJobConflict):
            await repository(connection).create_or_get(request())

    async def test_claim_acquires_lease_and_same_worker_replay_is_idempotent(self):
        claimed_row = row(
            "RUNNING", attempts=1, lease_owner="worker-1",
            lease_expires=NOW + timedelta(minutes=5), started=NOW,
        )
        connection = FakeConnection([row(), claimed_row])
        claim = await repository(connection).claim(
            job_id=JOB_ID, brand_id=BRAND_ID, content_id=CONTENT_ID,
            owner_user_id="owner-1", worker_id="worker-1",
        )
        self.assertTrue(claim.claimed)
        self.assertEqual(claim.record.attempt_count, 1)
        self.assertIn("attempt_count = attempt_count + 1", connection.calls[1][0])

        connection = FakeConnection([claimed_row])
        replay = await repository(connection).claim(
            job_id=JOB_ID, brand_id=BRAND_ID, content_id=CONTENT_ID,
            owner_user_id="owner-1", worker_id="worker-1",
        )
        self.assertFalse(replay.claimed)
        self.assertEqual(len(connection.calls), 1)

    async def test_expired_lease_can_be_recovered_but_attempt_limit_fails_closed(self):
        expired = row(
            "RUNNING", attempts=1, lease_owner="dead-worker",
            lease_expires=NOW - timedelta(seconds=1), started=NOW - timedelta(minutes=10),
        )
        recovered = row(
            "RUNNING", attempts=2, lease_owner="worker-2",
            lease_expires=NOW + timedelta(minutes=5), started=expired[13],
        )
        connection = FakeConnection([expired, recovered])
        claim = await repository(connection).claim(
            job_id=JOB_ID, brand_id=BRAND_ID, content_id=CONTENT_ID,
            owner_user_id="owner-1", worker_id="worker-2",
        )
        self.assertTrue(claim.claimed)
        self.assertEqual(claim.record.attempt_count, 2)

        exhausted = row(
            "RUNNING", attempts=2, lease_owner="dead-worker",
            lease_expires=NOW - timedelta(seconds=1), started=NOW,
        )
        with self.assertRaises(RenderJobConflict):
            await repository(FakeConnection([exhausted]), max_attempts=2).claim(
                job_id=JOB_ID, brand_id=BRAND_ID, content_id=CONTENT_ID,
                owner_user_id="owner-1", worker_id="worker-2",
            )

    async def test_failure_and_retry_are_idempotent_and_redacted(self):
        running = row(
            "RUNNING", attempts=1, lease_owner="worker-1",
            lease_expires=NOW + timedelta(minutes=5), started=NOW,
        )
        failed = row("FAILED", attempts=1, error="FFMPEG_FAILED", started=NOW, finished=NOW)
        connection = FakeConnection([running, failed])
        result = await repository(connection).mark_failed(
            job_id=JOB_ID, brand_id=BRAND_ID, content_id=CONTENT_ID,
            owner_user_id="owner-1", worker_id="worker-1", error_code="FFMPEG_FAILED",
        )
        self.assertEqual(result.error_code, "FFMPEG_FAILED")
        self.assertNotIn("error_log", connection.calls[1][0])
        with self.assertRaises(ValueError):
            await repository(FakeConnection()).mark_failed(
                job_id=JOB_ID, brand_id=BRAND_ID, content_id=CONTENT_ID,
                owner_user_id="owner-1", worker_id="worker-1", error_code="path C:\\secret",
            )

        pending = row("PENDING", attempts=1, started=NOW)
        connection = FakeConnection([failed, pending])
        retried = await repository(connection).retry_failed(
            job_id=JOB_ID, brand_id=BRAND_ID, content_id=CONTENT_ID, owner_user_id="owner-1",
        )
        self.assertEqual(retried.status, RenderJobStatus.PENDING)
        self.assertIn("status = 'PENDING'", connection.calls[1][0])

    async def test_all_state_changes_reject_a_naive_clock(self):
        naive = datetime(2026, 11, 22, 12, 0)
        repo = RenderJobRepository(FakePool(FakeConnection()), now=lambda: naive)
        common = {
            "job_id": JOB_ID, "brand_id": BRAND_ID, "content_id": CONTENT_ID,
            "owner_user_id": "owner-1",
        }
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            await repo.mark_failed(**common, worker_id="worker-1", error_code="FAILED")
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            await repo.retry_failed(**common)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            await repo.complete(
                **common, worker_id="worker-1", final_asset_id=FINAL_ID,
                artifacts=(RenderArtifactSpec(
                    asset_id=FINAL_ID, role=RenderArtifactRole.FINAL_VIDEO,
                ),),
            )

    async def test_state_changes_reject_unsafe_owner_identity(self):
        with self.assertRaisesRegex(ValueError, "owner-scoped"):
            await repository(FakeConnection()).retry_failed(
                job_id=JOB_ID, brand_id=BRAND_ID, content_id=CONTENT_ID,
                owner_user_id="owner\nspoof",
            )

    async def test_complete_checks_active_kinds_inserts_artifacts_and_is_idempotent(self):
        running = row(
            "RUNNING", attempts=1, lease_owner="worker-1",
            lease_expires=NOW + timedelta(minutes=5), started=NOW,
        )
        done = row("DONE", attempts=1, final=FINAL_ID, started=NOW, finished=NOW)
        final = RenderArtifactSpec(asset_id=FINAL_ID, role=RenderArtifactRole.FINAL_VIDEO)
        export = RenderArtifactSpec(
            asset_id=EXPORT_ID, role=RenderArtifactRole.EXPORT_VARIANT,
            profile_id="YOUTUBE_SHORTS_V1",
        )
        connection = FakeConnection([
            running,
            FakeCursor(rows=[(FINAL_ID, "FINAL_VIDEO"), (EXPORT_ID, "EXPORT_VARIANT")]),
            None, None, done,
        ])
        result = await repository(connection).complete(
            job_id=JOB_ID, brand_id=BRAND_ID, content_id=CONTENT_ID,
            owner_user_id="owner-1", worker_id="worker-1", final_asset_id=FINAL_ID,
            artifacts=(final, export),
        )
        self.assertEqual(result.status, RenderJobStatus.DONE)
        self.assertIn("retention_state = 'ACTIVE'", connection.calls[1][0])
        self.assertEqual(sum("INSERT INTO render_job_artifacts" in call[0] for call in connection.calls), 2)

        stored_rows = [(EXPORT_ID, "EXPORT_VARIANT", "YOUTUBE_SHORTS_V1"), (FINAL_ID, "FINAL_VIDEO", None)]
        connection = FakeConnection([done, FakeCursor(rows=stored_rows)])
        replay = await repository(connection).complete(
            job_id=JOB_ID, brand_id=BRAND_ID, content_id=CONTENT_ID,
            owner_user_id="owner-1", worker_id="worker-1", final_asset_id=FINAL_ID,
            artifacts=(final, export),
        )
        self.assertEqual(replay.status, RenderJobStatus.DONE)
        self.assertEqual(len(connection.calls), 2)


if __name__ == "__main__":
    unittest.main()
