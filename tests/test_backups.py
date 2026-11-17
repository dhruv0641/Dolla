import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from flowx_os.maintenance.backups import (
    BackupError,
    create_backup,
    plan_retention,
    restore_backup,
)


class BackupTests(unittest.TestCase):
    def test_backup_uses_service_file_verifies_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service_file = root / "pg_service.conf"
            service_file.write_text("[flowx-test]\nhost=localhost\n", encoding="utf-8")
            calls = []

            def run(args, **kwargs):
                calls.append((args, kwargs))
                if "--format=custom" in args:
                    Path(args[args.index("--file") + 1]).write_bytes(b"postgres-custom-archive")
                return subprocess.CompletedProcess(args, 0)

            with patch("flowx_os.maintenance.backups.shutil.which", side_effect=["pg_dump", "pg_restore"]):
                artifact = create_backup(
                    root / "backups", service_name="flowx-test", service_file=service_file,
                    now=datetime(2026, 11, 18, tzinfo=timezone.utc), run=run,
                )
            self.assertTrue(artifact.path.is_file())
            self.assertEqual(artifact.size_bytes, len(b"postgres-custom-archive"))
            self.assertTrue(artifact.path.with_suffix(".manifest.json").is_file())
            dump_args, kwargs = calls[0]
            self.assertNotIn("--password", dump_args)
            self.assertEqual(kwargs["env"]["PGSERVICE"], "flowx-test")
            self.assertEqual(kwargs["env"]["PGSERVICEFILE"], str(service_file.resolve()))

    def test_failed_archive_verification_leaves_no_named_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service_file = root / "pg_service.conf"
            service_file.write_text("[test]\n", encoding="utf-8")

            def run(args, **kwargs):
                if "--format=custom" in args:
                    Path(args[args.index("--file") + 1]).write_bytes(b"archive")
                else:
                    raise subprocess.CalledProcessError(1, args)
                return subprocess.CompletedProcess(args, 0)

            with patch("flowx_os.maintenance.backups.shutil.which", side_effect=["pg_dump", "pg_restore"]):
                with self.assertRaises(BackupError):
                    create_backup(root / "backups", service_name="test", service_file=service_file, run=run)
            self.assertEqual(list((root / "backups").glob("flowx-*.dump")), [])

    def test_retention_is_a_dry_run_and_preserves_latest_and_unexpired(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (
                "flowx-20260801T000000Z.dump",
                "flowx-20261101T000000Z.dump",
                "flowx-20261117T000000Z.dump",
                "other-file.dump",
            ):
                (root / name).write_text("fixture", encoding="utf-8")
            candidates = plan_retention(
                root,
                keep_latest=1,
                retention_days=30,
                now=datetime(2026, 11, 18, tzinfo=timezone.utc),
            )
            self.assertEqual([path.name for path in candidates], ["flowx-20260801T000000Z.dump"])
            self.assertTrue(candidates[0].exists())

    def test_restore_requires_checksum_manifest_and_never_uses_clean(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service_file = root / "service.conf"
            archive = root / "flowx-20261118T000000Z.dump"
            service_file.write_text("[test]\n", encoding="utf-8")
            archive.write_bytes(b"archive")
            manifest = {
                "file": archive.name,
                "sha256": __import__("hashlib").sha256(b"archive").hexdigest(),
            }
            archive.with_suffix(".manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            calls = []
            with patch("flowx_os.maintenance.backups.shutil.which", return_value="pg_restore"):
                restore_backup(archive, target_service="test", service_file=service_file,
                               run=lambda args, **kwargs: calls.append(args))
            self.assertNotIn("--clean", calls[0])
            self.assertIn("--single-transaction", calls[0])

    def test_restore_rejects_checksum_mismatch_before_database_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service_file = root / "service.conf"
            archive = root / "flowx-20261118T000000Z.dump"
            service_file.write_text("[test]\n", encoding="utf-8")
            archive.write_bytes(b"archive")
            archive.with_suffix(".manifest.json").write_text(
                json.dumps({"file": archive.name, "sha256": "bad"}), encoding="utf-8"
            )
            with self.assertRaisesRegex(BackupError, "manifest"):
                restore_backup(archive, target_service="test", service_file=service_file)


if __name__ == "__main__":
    unittest.main()
