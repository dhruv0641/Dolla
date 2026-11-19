"""Two-phase local deletion of explicitly retired managed media."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import stat
import tempfile
from uuid import UUID

from flowx_os.assets.storage import _hash_file
from flowx_os.db.asset_catalog import AssetCatalogRepository
from flowx_os.db.assets import AssetRecord


class AssetPurgeError(RuntimeError):
    """Safe local purge error; database remains PURGE_PENDING."""


class AssetPurgeService:
    def __init__(self, *, storage_root: Path, catalog: AssetCatalogRepository) -> None:
        self._root = Path(storage_root).expanduser().resolve() / "assets"
        self._catalog = catalog

    async def purge(self, *, asset_id: UUID, owner_user_id: str) -> bool:
        record = await self._catalog.prepare_purge(asset_id=asset_id, owner_user_id=owner_user_id)
        if record is None:
            return False
        await asyncio.to_thread(self._unlink_verified, record)
        await self._catalog.mark_purged(asset_id=asset_id, owner_user_id=owner_user_id)
        return True

    def _marker(self, record: AssetRecord) -> tuple[Path, bytes]:
        asset = record.metadata
        payload = self._root / asset.asset_id.hex / "payload"
        marker = payload.with_name(".purge-intent")
        expected = json.dumps({
            "asset_id": asset.asset_id.hex,
            "sha256_hex": asset.sha256_hex,
            "size_bytes": asset.size_bytes,
        }, sort_keys=True, separators=(",", ":")).encode("ascii")
        return marker, expected

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "posix":
            directory_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

    def _unlink_verified(self, record: AssetRecord) -> None:
        asset = record.metadata
        expected_uri = f"managed://assets/{asset.asset_id.hex}/payload"
        if asset.storage_uri != expected_uri:
            raise AssetPurgeError("managed asset identity is invalid")
        root = self._root
        object_dir = root / asset.asset_id.hex
        payload = object_dir / "payload"
        marker, expected_marker = self._marker(record)
        try:
            if (root.is_symlink() or object_dir.is_symlink() or payload.is_symlink()
                    or marker.is_symlink()
                    or object_dir.resolve().parent != root.resolve()):
                raise AssetPurgeError("managed asset path is unsafe")
            if marker.exists() and marker.read_bytes() != expected_marker:
                raise AssetPurgeError("managed purge intent does not match asset")
            if not payload.exists():
                if marker.exists():
                    self._fsync_directory(object_dir)
                    return  # Durable intent proves a previous authorized unlink attempt.
                raise AssetPurgeError("managed asset missing without purge intent")
            before = payload.lstat()
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise AssetPurgeError("managed asset is not a private regular file")
            digest, size = _hash_file(payload)
            after = payload.lstat()
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                    or digest != asset.sha256_hex or size != asset.size_bytes):
                raise AssetPurgeError("managed asset integrity changed")
            if not marker.exists():
                fd, temporary_name = tempfile.mkstemp(prefix=".purge-stage-", dir=object_dir)
                temporary = Path(temporary_name)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(expected_marker)
                        stream.flush()
                        os.fsync(stream.fileno())
                    try:
                        os.link(temporary, marker)  # Atomic no-replace publication.
                    except FileExistsError:
                        if marker.is_symlink() or marker.read_bytes() != expected_marker:
                            raise AssetPurgeError("managed purge intent does not match asset")
                    self._fsync_directory(object_dir)
                finally:
                    temporary.unlink(missing_ok=True)
            payload.unlink()
            self._fsync_directory(object_dir)
        except AssetPurgeError:
            raise
        except (OSError, RuntimeError) as exc:
            raise AssetPurgeError("managed asset removal failed; inspect pending purge") from exc
