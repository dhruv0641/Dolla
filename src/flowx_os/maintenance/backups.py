"""Verified PostgreSQL backup and restore primitives, with dry-run retention."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")
_BACKUP_NAME = re.compile(r"^flowx-(\d{8}T\d{6}Z)\.dump$")
CommandRunner = Callable[..., subprocess.CompletedProcess]


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


def create_backup(
    directory: str | Path,
    *,
    service_name: str,
    service_file: str | Path,
    now: datetime | None = None,
    run: CommandRunner = subprocess.run,
) -> BackupArtifact:
    """Create a custom-format dump via a libpq service file and verify it.

    Credentials must be supplied by the protected libpq service file (and its
    referenced password file); they never appear in the command-line arguments.
    """
    service = _safe_service_name(service_name)
    service_path = Path(service_file).expanduser().resolve()
    if not service_path.is_file():
        raise BackupError("configured PostgreSQL service file does not exist")
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise BackupError("backup timestamp must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)
    output_dir = Path(directory).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / f"flowx-{timestamp:%Y%m%dT%H%M%SZ}.dump"
    if final_path.exists():
        raise BackupError("backup archive already exists for this timestamp")
    fd, temp_name = tempfile.mkstemp(prefix=".flowx-backup-", suffix=".dump.tmp", dir=output_dir)
    os.close(fd)
    temp_path = Path(temp_name)
    env = os.environ.copy()
    env["PGSERVICE"] = service
    env["PGSERVICEFILE"] = str(service_path)
    try:
        dump = shutil.which("pg_dump")
        restore = shutil.which("pg_restore")
        if not dump or not restore:
            raise BackupError("pg_dump and pg_restore must be installed and available on PATH")
        run([dump, "--format=custom", "--no-password", "--file", str(temp_path), "--dbname", service],
            check=True, capture_output=True, text=True, env=env)
        if not temp_path.is_file() or temp_path.stat().st_size == 0:
            raise BackupError("pg_dump did not produce a non-empty archive")
        run([restore, "--list", "--no-password", str(temp_path)],
            check=True, capture_output=True, text=True, env=env)
        checksum = _sha256_file(temp_path)
        size = temp_path.stat().st_size
        os.replace(temp_path, final_path)
        manifest = {"file": final_path.name, "size_bytes": size, "sha256": checksum,
                    "created_at": timestamp.isoformat(), "service_name": service}
        manifest_path = final_path.with_suffix(".manifest.json")
        manifest_tmp = manifest_path.with_suffix(".manifest.json.tmp")
        manifest_tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(manifest_tmp, manifest_path)
        return BackupArtifact(final_path, size, checksum)
    except subprocess.CalledProcessError as exc:
        raise BackupError("PostgreSQL backup or archive verification failed") from exc
    except OSError as exc:
        raise BackupError("database backup could not be written") from exc
    finally:
        temp_path.unlink(missing_ok=True)


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
    run: CommandRunner = subprocess.run,
) -> None:
    """Restore into a pre-created empty database; never drops or cleans objects."""
    service = _safe_service_name(target_service)
    archive = Path(archive_path).expanduser().resolve()
    service_path = Path(service_file).expanduser().resolve()
    if not archive.is_file() or not service_path.is_file():
        raise BackupError("backup archive and PostgreSQL service file must exist")
    manifest_path = archive.with_suffix(".manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("file") != archive.name:
            raise ValueError("archive name mismatch")
        expected_hash = manifest.get("sha256")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise ValueError("invalid checksum")
        digest = _sha256_file(archive)
        if digest != expected_hash:
            raise ValueError("archive checksum mismatch")
    except (OSError, ValueError, TypeError) as exc:
        raise BackupError("backup manifest is missing or does not match the archive") from exc
    restore = shutil.which("pg_restore")
    if not restore:
        raise BackupError("pg_restore must be installed and available on PATH")
    env = os.environ.copy()
    env["PGSERVICE"] = service
    env["PGSERVICEFILE"] = str(service_path)
    try:
        run([restore, "--no-password", "--exit-on-error", "--single-transaction",
             "--dbname", service, str(archive)], check=True, capture_output=True, text=True, env=env)
    except subprocess.CalledProcessError as exc:
        raise BackupError("PostgreSQL restore failed; inspect the target database before retrying") from exc
