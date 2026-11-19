"""Bounded, content-verified local asset storage."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class AssetStorageError(RuntimeError):
    """Safe-to-display local storage error."""


class AssetStorageConflict(AssetStorageError):
    """An asset UUID already names different immutable bytes."""


@dataclass(frozen=True, slots=True)
class StoredAssetFile:
    asset_id: uuid.UUID
    path: Path
    storage_uri: str
    sha256_hex: str
    mime_type: str
    size_bytes: int


_SIGNATURES: dict[str, tuple[str, Callable[[bytes], bool]]] = {
    "image/png": (".png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/jpeg": (".jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    "image/webp": (".webp", lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"),
    "video/mp4": (".mp4", lambda data: len(data) >= 12 and data[4:8] == b"ftyp"),
    "video/webm": (".webm", lambda data: data.startswith(b"\x1aE\xdf\xa3")),
    "audio/wav": (".wav", lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"),
    "audio/mpeg": (".mp3", lambda data: data.startswith(b"ID3") or (len(data) >= 2 and data[:1] == b"\xff" and data[1] & 0xE0 == 0xE0)),
    "audio/ogg": (".ogg", lambda data: data.startswith(b"OggS")),
    "text/plain": (".txt", lambda data: b"\x00" not in data),
}


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


class ManagedAssetStore:
    """Atomically copy validated files to a fixed, non-user-addressable root."""

    def __init__(self, storage_root: Path, *, max_bytes: int = 2_000_000_000) -> None:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 0 < max_bytes <= 4_000_000_000:
            raise ValueError("asset byte limit is invalid")
        base = Path(storage_root).expanduser()
        self._root = base / "assets"
        self._root.mkdir(parents=True, exist_ok=True)
        if self._root.is_symlink() or not self._root.is_dir():
            raise ValueError("managed asset root must be a real directory")
        self._root = self._root.resolve()
        self._max_bytes = max_bytes

    def store(self, *, asset_id: uuid.UUID, source_path: Path, mime_type: str) -> StoredAssetFile:
        if not isinstance(asset_id, uuid.UUID):
            raise ValueError("asset ID must be a UUID")
        if not isinstance(mime_type, str):
            raise ValueError("asset MIME type is required")
        normalized_mime = mime_type.split(";", 1)[0].strip().casefold()
        signature = _SIGNATURES.get(normalized_mime)
        if signature is None:
            raise AssetStorageError("asset MIME type is not supported")
        source = Path(source_path)
        try:
            source_stat = source.lstat()
            if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
                raise AssetStorageError("asset source must be a regular file")
            source = source.resolve(strict=True)
            if source.stat().st_size <= 0 or source.stat().st_size > self._max_bytes:
                raise AssetStorageError("asset source size is outside the configured limit")
        except AssetStorageError:
            raise
        except (OSError, RuntimeError) as exc:
            raise AssetStorageError("asset source is unavailable") from exc

        object_dir = self._root / asset_id.hex
        try:
            object_dir.mkdir(mode=0o700, exist_ok=True)
            if object_dir.is_symlink() or not object_dir.is_dir() or object_dir.resolve().parent != self._root:
                raise AssetStorageError("managed asset object path is unsafe")
        except AssetStorageError:
            raise
        except OSError as exc:
            raise AssetStorageError("managed asset storage is unavailable") from exc
        target = object_dir / "payload"
        fd, temp_name = tempfile.mkstemp(prefix=".stage-", dir=object_dir)
        staged = Path(temp_name)
        digest = hashlib.sha256()
        size = 0
        prefix = bytearray()
        try:
            with os.fdopen(fd, "wb") as output, source.open("rb") as incoming:
                while block := incoming.read(1024 * 1024):
                    size += len(block)
                    if size > self._max_bytes:
                        raise AssetStorageError("asset source exceeds the configured byte limit")
                    if len(prefix) < 64:
                        prefix.extend(block[:64 - len(prefix)])
                    digest.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            if size <= 0 or not signature[1](bytes(prefix)):
                raise AssetStorageError("asset bytes do not match the declared MIME type")
            sha256_hex = digest.hexdigest()
            if target.exists():
                if target.is_symlink() or not target.is_file():
                    raise AssetStorageError("existing managed asset object is unsafe")
                existing_hash, existing_size = _hash_file(target)
                if existing_hash != sha256_hex or existing_size != size:
                    raise AssetStorageConflict("asset UUID already refers to different bytes")
                staged.unlink()
            else:
                try:
                    # Same-directory hard-link creation is atomic and refuses to replace an existing object.
                    os.link(staged, target)
                except FileExistsError:
                    if target.is_symlink() or not target.is_file():
                        raise AssetStorageError("existing managed asset object is unsafe")
                    existing_hash, existing_size = _hash_file(target)
                    if existing_hash != sha256_hex or existing_size != size:
                        raise AssetStorageConflict("asset UUID already refers to different bytes")
                staged.unlink(missing_ok=True)
            return StoredAssetFile(
                asset_id=asset_id,
                path=target,
                storage_uri=f"managed://assets/{asset_id.hex}/payload",
                sha256_hex=sha256_hex,
                mime_type=normalized_mime,
                size_bytes=size,
            )
        except AssetStorageError:
            raise
        except (OSError, RuntimeError) as exc:
            raise AssetStorageError("managed asset write failed") from exc
        finally:
            staged.unlink(missing_ok=True)
