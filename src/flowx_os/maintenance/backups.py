"""Verified PostgreSQL backup and restore primitives, with dry-run retention."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Callable, Mapping, Sequence


_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")
_BACKUP_NAME = re.compile(r"^flowx-(\d{8}T\d{6}Z)\.dump\.age$")
_AGE_RECIPIENT = re.compile(r"^age1[0-9a-z]{20,100}$")
PipelineRunner = Callable[[Sequence[str], Sequence[str] | None, Mapping[str, str], Mapping[str, str], BinaryIO | None, float], None]


class BackupError(RuntimeError):
    """Raised when backup, verification, or restore fails safely."""


@dataclass(frozen=True)
class BackupArtifact:
    path: Path
    size_bytes: int
    sha256: str


def _safe_service_name(service_name: str) -> str:
    if not isinstance(service_name, str) or not _SERVICE_NAME.fullmatch(service_name):
        raise BackupError("service name must use only letters, digits, underscore, dot, or hyphen")
    return service_name


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_pipeline(
    source_command: Sequence[str],
    sink_command: Sequence[str] | None,
    source_env: Mapping[str, str],
    sink_env: Mapping[str, str],
    sink_output: BinaryIO | None = None,
    timeout_seconds: float = 3600,
) -> None:
    """Connect two tools without materializing plaintext on disk."""
    source = None
    sink = None
    try:
        source = subprocess.Popen(
            list(source_command), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if sink_command is not None else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=dict(source_env),
        )
        if sink_command is None:
            source_status = source.wait(timeout=timeout_seconds)
            if source_status != 0:
                raise BackupError("encrypted backup pipeline failed")
            return
        assert source.stdout is not None
        sink = subprocess.Popen(
            list(sink_command), stdin=source.stdout,
            stdout=sink_output if sink_output is not None else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=dict(sink_env),
        )
        source.stdout.close()
        sink_status = sink.wait(timeout=timeout_seconds)
        source_status = source.wait(timeout=timeout_seconds)
        if sink_status != 0 or source_status != 0:
            raise BackupError("encrypted backup pipeline failed")
    except subprocess.TimeoutExpired as exc:
        raise BackupError("backup or restore tool exceeded its execution timeout") from exc
    except OSError as exc:
        raise BackupError("backup encryption or restore tool could not start") from exc
    finally:
        for process in (sink, source):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if source is not None and source.stdout is not None and not source.stdout.closed:
            source.stdout.close()


def _tool_env() -> dict[str, str]:
    """Return only OS variables needed to launch native tools."""
    allowed = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
    return {name: os.environ[name] for name in allowed if name in os.environ}


def create_backup(
    directory: str | Path,
    *,
    service_name: str,
    service_file: str | Path,
    recipient: str,
    now: datetime | None = None,
    timeout_seconds: float = 3600,
    pipeline: PipelineRunner = _run_pipeline,
) -> BackupArtifact:
    """Stream a custom-format dump through age encryption to a named artifact.

    Credentials must be supplied by the protected libpq service file (and its
    referenced password file); they never appear in the command-line arguments.
    The database dump is piped directly into age and is never stored as plaintext.
    """
    service = _safe_service_name(service_name)
    if not isinstance(recipient, str) or not _AGE_RECIPIENT.fullmatch(recipient):
        raise BackupError("recipient must be a native age public key")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise BackupError("timeout_seconds must be a positive finite number")
    service_path = Path(service_file).expanduser().resolve()
    if not service_path.is_file():
        raise BackupError("configured PostgreSQL service file does not exist")
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise BackupError("backup timestamp must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)
    output_dir = Path(directory).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / f"flowx-{timestamp:%Y%m%dT%H%M%SZ}.dump.age"
    manifest_path = final_path.with_suffix(".manifest.json")
    if final_path.exists() or manifest_path.exists():
        raise BackupError("backup archive already exists for this timestamp")
    fd, temp_name = tempfile.mkstemp(prefix=".flowx-backup-", suffix=".age.tmp", dir=output_dir)
    temp_path = Path(temp_name)
    postgres_env = _tool_env()
    postgres_env["PGSERVICE"] = service
    postgres_env["PGSERVICEFILE"] = str(service_path)
    age_env = _tool_env()
    manifest_tmp: Path | None = None
    archive_published = False
    manifest_published = False
    try:
        dump = shutil.which("pg_dump")
        age = shutil.which("age")
        if not dump or not age:
            raise BackupError("pg_dump and age must be installed and available on PATH")
        dump_command = [dump, "--format=custom", "--no-password", "--dbname", service]
        encrypt_command = [age, "--encrypt", "--recipient", recipient]
        with os.fdopen(fd, "wb") as encrypted_stream:
            fd = -1
            pipeline(dump_command, encrypt_command, postgres_env, age_env, encrypted_stream, timeout_seconds)
            encrypted_stream.flush()
            os.fsync(encrypted_stream.fileno())
        if not temp_path.is_file() or temp_path.stat().st_size == 0:
            raise BackupError("age did not produce a non-empty encrypted archive")
        checksum = _sha256_file(temp_path)
        size = temp_path.stat().st_size
        manifest = {
            "file": final_path.name,
            "size_bytes": size,
            "sha256": checksum,
            "created_at": timestamp.isoformat(),
            "service_name": service,
            "encryption": "age",
        }
        manifest_fd, manifest_name = tempfile.mkstemp(
            prefix=".flowx-manifest-", suffix=".tmp", dir=output_dir
        )
        manifest_tmp = Path(manifest_name)
        with os.fdopen(manifest_fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(manifest, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp_path, final_path)
        archive_published = True
        temp_path.unlink()
        try:
            os.link(manifest_tmp, manifest_path)
        except OSError:
            raise
        manifest_published = True
        return BackupArtifact(final_path, size, checksum)
    except BackupError:
        raise
    except OSError as exc:
        raise BackupError("encrypted database backup could not be written") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        temp_path.unlink(missing_ok=True)
        if archive_published and not manifest_published:
            final_path.unlink(missing_ok=True)
        if manifest_tmp is not None:
            manifest_tmp.unlink(missing_ok=True)


def plan_retention(
    directory: str | Path,
    *,
    keep_latest: int = 7,
    retention_days: int = 30,
    now: datetime | None = None,
) -> list[Path]:
    """Return expired backup archives eligible for deletion; this is dry-run only."""
    if isinstance(keep_latest, bool) or not isinstance(keep_latest, int) or keep_latest < 1:
        raise BackupError("keep_latest must be at least 1")
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 1:
        raise BackupError("retention_days must be at least 1")
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise BackupError("retention timestamp must be timezone-aware")
    cutoff = timestamp.astimezone(timezone.utc) - timedelta(days=retention_days)
    root = Path(directory)
    archives: list[tuple[datetime, Path]] = []
    if not root.exists():
        return []
    for path in root.iterdir():
        match = _BACKUP_NAME.fullmatch(path.name)
        if not match or not path.is_file():
            continue
        try:
            created = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        archives.append((created, path))
    archives.sort(key=lambda item: item[0], reverse=True)
    protected = {path for _, path in archives[:keep_latest]}
    return [path for created, path in archives if created < cutoff and path not in protected]


def restore_backup(
    archive_path: str | Path,
    *,
    target_service: str,
    service_file: str | Path,
    identity_file: str | Path,
    timeout_seconds: float = 3600,
    pipeline: PipelineRunner = _run_pipeline,
) -> None:
    """Decrypt directly into pg_restore for an approved empty-database restore."""
    service = _safe_service_name(target_service)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise BackupError("timeout_seconds must be a positive finite number")
    archive = Path(archive_path).expanduser().resolve()
    service_path = Path(service_file).expanduser().resolve()
    identity_path = Path(identity_file).expanduser().resolve()
    if not _BACKUP_NAME.fullmatch(archive.name):
        raise BackupError("archive must use the encrypted .dump.age format")
    if not archive.is_file() or not service_path.is_file() or not identity_path.is_file():
        raise BackupError("encrypted archive, service file, and age identity file must exist")
    manifest_path = archive.with_suffix(".manifest.json")
    snapshot_fd, snapshot_name = tempfile.mkstemp(prefix=".flowx-restore-", suffix=".dump.age", dir=archive.parent)
    snapshot = Path(snapshot_name)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("file") != archive.name or manifest.get("encryption") != "age":
            raise ValueError("archive name mismatch")
        expected_hash = manifest.get("sha256")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise ValueError("invalid checksum")
        digest = hashlib.sha256()
        size = 0
        with archive.open("rb") as source, os.fdopen(snapshot_fd, "wb") as destination:
            snapshot_fd = -1
            for block in iter(lambda: source.read(1024 * 1024), b""):
                destination.write(block)
                digest.update(block)
                size += len(block)
            destination.flush()
            os.fsync(destination.fileno())
        if manifest.get("size_bytes") != size or digest.hexdigest() != expected_hash:
            raise ValueError("archive checksum mismatch")
    except (OSError, ValueError, TypeError) as exc:
        if snapshot_fd >= 0:
            os.close(snapshot_fd)
        snapshot.unlink(missing_ok=True)
        raise BackupError("backup manifest is missing or does not match the archive") from exc
    age = shutil.which("age")
    restore = shutil.which("pg_restore")
    if not age or not restore:
        snapshot.unlink(missing_ok=True)
        raise BackupError("age and pg_restore must be installed and available on PATH")
    postgres_env = _tool_env()
    postgres_env["PGSERVICE"] = service
    postgres_env["PGSERVICEFILE"] = str(service_path)
    age_env = _tool_env()
    decrypt_command = [age, "--decrypt", "--identity", str(identity_path), str(snapshot)]
    try:
        # Drain a complete authentication pass before pg_restore can mutate the target.
        pipeline(decrypt_command, None, age_env, age_env, None, timeout_seconds)
        pipeline(
            decrypt_command,
            [restore, "--no-password", "--exit-on-error", "--single-transaction", "--dbname", service, "-"],
            age_env,
            postgres_env,
            None,
            timeout_seconds,
        )
    except BackupError:
        raise
    except OSError as exc:
        raise BackupError("PostgreSQL restore failed; inspect the target database before retrying") from exc
    finally:
        snapshot.unlink(missing_ok=True)
