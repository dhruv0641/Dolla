import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from flowx_os.maintenance.backups import BackupError, create_backup, plan_retention, restore_backup


RECIPIENT = "age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"


class BackupTests(unittest.TestCase):
    def test_backup_streams_dump_to_age_and_writes_encrypted_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service_file = root / "pg_service.conf"
            service_file.write_text("[flowx-test]\nhost=localhost\n", encoding="utf-8")
            calls = []

            def pipeline(source, sink, source_env, sink_env, output, timeout):
                calls.append((list(source), list(sink) if sink is not None else None,
                              dict(source_env), dict(sink_env)))
                self.assertIn("--format=custom", source)
                self.assertNotIn("--file", source)
                self.assertEqual(sink[0], "age")
                self.assertIn("--recipient", sink)
                self.assertEqual(source_env["PGSERVICE"], "flowx-test")
                self.assertEqual(source_env["PGSERVICEFILE"], str(service_file.resolve()))
                self.assertNotIn("PGSERVICE", sink_env)
                self.assertNotIn("PGPASSWORD", source_env)
                output.write(b"age-encrypted-custom-archive")

            with patch("flowx_os.maintenance.backups.shutil.which", side_effect=["pg_dump", "age"]):
                artifact = create_backup(
                    root / "backups", service_name="flowx-test", service_file=service_file,
                    recipient=RECIPIENT, now=datetime(2026, 11, 18, tzinfo=timezone.utc),
                    pipeline=pipeline,
                )

            self.assertEqual(len(calls), 1)
            self.assertEqual(artifact.path.name, "flowx-20261118T000000Z.dump.age")
            self.assertEqual(artifact.size_bytes, len(b"age-encrypted-custom-archive"))
            self.assertEqual(artifact.sha256, hashlib.sha256(b"age-encrypted-custom-archive").hexdigest())
            manifest = json.loads(artifact.path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["encryption"], "age")
            self.assertEqual(manifest["sha256"], artifact.sha256)
            self.assertEqual(list((root / "backups").glob("*.tmp")), [])

    def test_real_pipeline_wires_dump_stdout_to_encrypted_file_without_plaintext_intermediate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service_file = root / "service.conf"
            service_file.write_text("[test]\n", encoding="utf-8")
            plaintext_dump = b"private database dump"

            class FakeSource:
                def __init__(self, command, **kwargs):
                    self.command = command
                    self.stdout = io.BytesIO(plaintext_dump)
                    self.returncode = 0

                def wait(self, **kwargs):
                    return self.returncode

                def poll(self):
                    return self.returncode

            class FakeSink:
                def __init__(self, command, **kwargs):
                    source = kwargs["stdin"].read()
                    kwargs["stdout"].write(b"encrypted:" + source[::-1])
                    self.returncode = 0

                def wait(self, **kwargs):
                    return self.returncode

                def poll(self):
                    return self.returncode

            def fake_popen(command, **kwargs):
                return FakeSource(command, **kwargs) if command[0] == "pg_dump" else FakeSink(command, **kwargs)

            with patch("flowx_os.maintenance.backups.shutil.which", side_effect=["pg_dump", "age"]), \
                    patch("flowx_os.maintenance.backups.subprocess.Popen", side_effect=fake_popen):
                artifact = create_backup(
                    root / "backups", service_name="test", service_file=service_file,
                    recipient=RECIPIENT, now=datetime(2026, 11, 18, tzinfo=timezone.utc),
                )

            self.assertEqual(artifact.path.read_bytes(), b"encrypted:" + plaintext_dump[::-1])
            self.assertNotIn(plaintext_dump, artifact.path.read_bytes())
            self.assertEqual({p.name for p in (root / "backups").iterdir()}, {
                artifact.path.name, artifact.path.with_suffix(".manifest.json").name,
            })

    def test_failed_encryption_leaves_no_named_backup_or_temporary_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service_file = root / "pg_service.conf"
            service_file.write_text("[test]\n", encoding="utf-8")

            def fail_after_partial_output(source, sink, source_env, sink_env, output, timeout):
                output.write(b"partial ciphertext")
                raise BackupError("encrypted backup pipeline failed")

            with patch("flowx_os.maintenance.backups.shutil.which", side_effect=["pg_dump", "age"]):
                with self.assertRaises(BackupError):
                    create_backup(root / "backups", service_name="test", service_file=service_file,
                                  recipient=RECIPIENT, pipeline=fail_after_partial_output)

            self.assertEqual(list((root / "backups").glob("flowx-*.dump.age")), [])
            self.assertEqual(list((root / "backups").glob("*.tmp")), [])

    def test_backup_publication_does_not_overwrite_concurrent_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service_file = root / "service.conf"
            service_file.write_text("[test]\n", encoding="utf-8")
            output_dir = root / "backups"
            final_path = output_dir / "flowx-20261118T000000Z.dump.age"

            def race_publication(source, sink, source_env, sink_env, output, timeout):
                output.write(b"new ciphertext")
                final_path.parent.mkdir(parents=True, exist_ok=True)
                final_path.write_bytes(b"other invocation's archive")

            with patch("flowx_os.maintenance.backups.shutil.which", side_effect=["pg_dump", "age"]):
                with self.assertRaises(BackupError):
                    create_backup(output_dir, service_name="test", service_file=service_file,
                                  recipient=RECIPIENT,
                                  now=datetime(2026, 11, 18, tzinfo=timezone.utc),
                                  pipeline=race_publication)

            self.assertEqual(final_path.read_bytes(), b"other invocation's archive")
            self.assertFalse(final_path.with_suffix(".manifest.json").exists())

    def test_rejects_non_native_age_recipient(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service_file = Path(temp_dir) / "service.conf"
            service_file.write_text("[test]\n", encoding="utf-8")
            with self.assertRaisesRegex(BackupError, "native age public key"):
                create_backup(Path(temp_dir) / "backups", service_name="test", service_file=service_file,
                              recipient="not-a-recipient")

    def test_retention_is_dry_run_and_only_selects_encrypted_archives(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in (
                "flowx-20260801T000000Z.dump.age",
                "flowx-20261101T000000Z.dump.age",
                "flowx-20261117T000000Z.dump.age",
                "flowx-20260801T000000Z.dump",
                "other-file.dump.age",
            ):
                (root / name).write_bytes(b"fixture")
            candidates = plan_retention(
                root, keep_latest=1, retention_days=30,
                now=datetime(2026, 11, 18, tzinfo=timezone.utc),
            )
            self.assertEqual([path.name for path in candidates], ["flowx-20260801T000000Z.dump.age"])
            self.assertTrue(candidates[0].exists())

    def test_restore_decrypts_to_pg_restore_stdin_and_never_cleans(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service_file = root / "service.conf"
            identity_file = root / "age-identity"
            archive = root / "flowx-20261118T000000Z.dump.age"
            service_file.write_text("[test]\n", encoding="utf-8")
            identity_file.write_text("AGE-SECRET-KEY-EXTERNAL-TEST\n", encoding="utf-8")
            archive.write_bytes(b"encrypted-archive")
            archive.with_suffix(".manifest.json").write_text(json.dumps({
                "file": archive.name,
                "size_bytes": archive.stat().st_size,
                "sha256": hashlib.sha256(b"encrypted-archive").hexdigest(),
                "encryption": "age",
            }), encoding="utf-8")
            calls = []

            def pipeline(source, sink, source_env, sink_env, output, timeout):
                calls.append((list(source), list(sink) if sink is not None else None,
                              dict(source_env), dict(sink_env)))

            with patch("flowx_os.maintenance.backups.shutil.which", side_effect=["age", "pg_restore"]):
                restore_backup(archive, target_service="test", service_file=service_file,
                               identity_file=identity_file, pipeline=pipeline)

            self.assertEqual(len(calls), 2)
            decrypt, auth_sink, age_env, _ = calls[0]
            self.assertIsNone(auth_sink)
            self.assertEqual(decrypt[:4], ["age", "--decrypt", "--identity", str(identity_file.resolve())])
            self.assertEqual(calls[0][0], calls[1][0])
            _, restore_command, _, env = calls[1]
            self.assertEqual(restore_command[0], "pg_restore")
            self.assertEqual(env["PGSERVICE"], "test")
            self.assertNotIn("PGSERVICE", age_env)
            self.assertIn("--single-transaction", restore_command)
            self.assertNotIn("--clean", restore_command)
            self.assertEqual(restore_command[-1], "-")

    def test_restore_pipeline_streams_decrypted_data_directly_to_pg_restore(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service_file = root / "service.conf"
            identity_file = root / "age-identity"
            archive = root / "flowx-20261118T000000Z.dump.age"
            plaintext_dump = b"decrypted custom-format dump"
            service_file.write_text("[test]\n", encoding="utf-8")
            identity_file.write_text("external identity path", encoding="utf-8")
            archive.write_bytes(b"ciphertext")
            archive.with_suffix(".manifest.json").write_text(json.dumps({
                "file": archive.name,
                "size_bytes": len(b"ciphertext"),
                "sha256": hashlib.sha256(b"ciphertext").hexdigest(),
                "encryption": "age",
            }), encoding="utf-8")
            consumed = []

            class FakeSource:
                def __init__(self, command, **kwargs):
                    self.stdout = io.BytesIO(plaintext_dump)
                    self.returncode = 0

                def wait(self, **kwargs):
                    return self.returncode

                def poll(self):
                    return self.returncode

            class FakeSink:
                def __init__(self, command, **kwargs):
                    consumed.append(kwargs["stdin"].read())
                    self.returncode = 0

                def wait(self, **kwargs):
                    return self.returncode

                def poll(self):
                    return self.returncode

            def fake_popen(command, **kwargs):
                return FakeSource(command, **kwargs) if command[0] == "age" else FakeSink(command, **kwargs)

            with patch("flowx_os.maintenance.backups.shutil.which", side_effect=["age", "pg_restore"]), \
                    patch("flowx_os.maintenance.backups.subprocess.Popen", side_effect=fake_popen):
                restore_backup(archive, target_service="test", service_file=service_file,
                               identity_file=identity_file)

            self.assertEqual(consumed, [plaintext_dump])
            self.assertEqual(set(root.iterdir()), {
                service_file, identity_file, archive, archive.with_suffix(".manifest.json"),
            })

    def test_restore_rejects_checksum_mismatch_before_running_pipeline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service_file = root / "service.conf"
            identity_file = root / "age-identity"
            archive = root / "flowx-20261118T000000Z.dump.age"
            service_file.write_text("[test]\n", encoding="utf-8")
            identity_file.write_text("external identity path", encoding="utf-8")
            archive.write_bytes(b"ciphertext")
            archive.with_suffix(".manifest.json").write_text(json.dumps({
                "file": archive.name, "sha256": "bad", "encryption": "age",
            }), encoding="utf-8")
            called = False

            def pipeline(*args):
                nonlocal called
                called = True

            with self.assertRaisesRegex(BackupError, "manifest"):
                restore_backup(archive, target_service="test", service_file=service_file,
                               identity_file=identity_file, pipeline=pipeline)
            self.assertFalse(called)

    def test_restore_authentication_failure_prevents_database_restore(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service_file = root / "service.conf"
            identity_file = root / "age-identity"
            archive = root / "flowx-20261118T000000Z.dump.age"
            service_file.write_text("[test]\n", encoding="utf-8")
            identity_file.write_text("external identity path", encoding="utf-8")
            archive.write_bytes(b"ciphertext")
            archive.with_suffix(".manifest.json").write_text(json.dumps({
                "file": archive.name, "size_bytes": archive.stat().st_size,
                "sha256": hashlib.sha256(b"ciphertext").hexdigest(), "encryption": "age",
            }), encoding="utf-8")
            calls = []

            def fail_authentication(source, sink, source_env, sink_env, output, timeout):
                calls.append((list(source), sink, timeout))
                # Simulate age emitting bytes and then rejecting the final authentication tag.
                raise BackupError("encrypted backup pipeline failed")

            with patch("flowx_os.maintenance.backups.shutil.which", side_effect=["age", "pg_restore"]):
                with self.assertRaisesRegex(BackupError, "pipeline failed"):
                    restore_backup(archive, target_service="test", service_file=service_file,
                                   identity_file=identity_file, pipeline=fail_authentication,
                                   timeout_seconds=12)

            self.assertEqual(len(calls), 1)
            self.assertIsNone(calls[0][1])
            self.assertEqual(calls[0][2], 12)
            self.assertFalse(any(path.name.startswith(".flowx-restore-") for path in root.iterdir()))


if __name__ == "__main__":
    unittest.main()
