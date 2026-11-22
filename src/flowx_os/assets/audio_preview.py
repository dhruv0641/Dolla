"""Integrity-verified, bounded byte-range delivery for managed audio."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Protocol
from uuid import UUID

from flowx_os.db.assets import AssetRecord


class AudioPreviewError(RuntimeError):
    def __init__(self, code: str, message: str, *, total: int | None = None) -> None:
        self.code = code
        self.total = total
        super().__init__(message)


class AudioRecordStore(Protocol):
    async def get_active_audio(
        self, *, asset_id: UUID, brand_id: UUID, content_id: UUID,
        owner_user_id: str,
    ) -> AssetRecord: ...


@dataclass(frozen=True, slots=True)
class AudioByteRange:
    start: int
    end: int
    total: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True, slots=True)
class AudioPreviewPayload:
    data: bytes
    mime_type: str
    etag: str
    selected_range: AudioByteRange
    partial: bool


def parse_byte_range(value: str | None, *, total: int,
                     maximum_bytes: int) -> tuple[int, int, bool]:
    if type(total) is not int or total <= 0 or type(maximum_bytes) is not int or maximum_bytes <= 0:
        raise ValueError("audio range limits are invalid")
    if value is None:
        if total > maximum_bytes:
            raise AudioPreviewError("RANGE_REQUIRED", "a bounded byte range is required", total=total)
        return 0, total - 1, False
    if not isinstance(value, str) or len(value) > 100 or "," in value:
        raise AudioPreviewError("RANGE_INVALID", "only one byte range is supported", total=total)
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if match is None or (not match.group(1) and not match.group(2)):
        raise AudioPreviewError("RANGE_INVALID", "audio byte range is invalid", total=total)
    first, last = match.groups()
    if first:
        start = int(first)
        end = int(last) if last else total - 1
        if start >= total or end < start:
            raise AudioPreviewError("RANGE_UNSATISFIABLE", "audio byte range is unsatisfiable", total=total)
        end = min(end, total - 1)
    else:
        suffix = int(last)
        if suffix <= 0:
            raise AudioPreviewError("RANGE_UNSATISFIABLE", "audio byte range is unsatisfiable", total=total)
        suffix = min(suffix, total)
        start, end = total - suffix, total - 1
    if end - start + 1 > maximum_bytes:
        raise AudioPreviewError("RANGE_TOO_LARGE", "audio byte range exceeds the preview limit", total=total)
    return start, end, True


class AudioPreviewService:
    """Resolve ownership in the store, verify immutable bytes, then return a bounded range."""

    def __init__(self, *, storage_root: Path, store: AudioRecordStore,
                 maximum_source_bytes: int = 250_000_000,
                 maximum_preview_bytes: int = 8_000_000) -> None:
        if (type(maximum_source_bytes) is not int or not 1024 <= maximum_source_bytes <= 1_000_000_000
                or type(maximum_preview_bytes) is not int or not 1024 <= maximum_preview_bytes <= 64_000_000
                or maximum_preview_bytes > maximum_source_bytes):
            raise ValueError("audio preview limits are invalid")
        self._root = Path(storage_root).expanduser().resolve() / "assets"
        self._store = store
        self._maximum_source = maximum_source_bytes
        self._maximum_preview = maximum_preview_bytes

    async def preview(
        self, *, asset_id: UUID, brand_id: UUID, content_id: UUID,
        owner_user_id: str, range_header: str | None,
    ) -> AudioPreviewPayload:
        record = await self._store.get_active_audio(
            asset_id=asset_id, brand_id=brand_id, content_id=content_id,
            owner_user_id=owner_user_id,
        )
        return await asyncio.to_thread(self._read_verified, record, range_header)

    def _read_verified(self, record: AssetRecord, range_header: str | None) -> AudioPreviewPayload:
        asset = record.metadata
        expected_uri = f"managed://assets/{asset.asset_id.hex}/payload"
        path = self._root / asset.asset_id.hex / "payload"
        try:
            if (asset.storage_uri != expected_uri or not asset.mime_type.startswith("audio/")
                    or asset.size_bytes > self._maximum_source
                    or self._root.is_symlink() or path.parent.is_symlink() or path.is_symlink()
                    or path.parent.resolve().parent != self._root
                    or not stat.S_ISREG(path.lstat().st_mode) or path.lstat().st_nlink != 1):
                raise AudioPreviewError("AUDIO_PREVIEW_UNAVAILABLE", "audio preview is unavailable")
            digest = hashlib.sha256()
            size = 0
            selected = bytearray()
            start, end, partial = parse_byte_range(
                range_header, total=asset.size_bytes,
                maximum_bytes=self._maximum_preview,
            )
            with path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise AudioPreviewError("AUDIO_PREVIEW_UNAVAILABLE", "audio preview is unavailable")
                offset = 0
                while block := stream.read(1024 * 1024):
                    size += len(block)
                    if size > self._maximum_source:
                        raise AudioPreviewError("AUDIO_PREVIEW_UNAVAILABLE", "audio preview is unavailable")
                    digest.update(block)
                    block_end = offset + len(block) - 1
                    if block_end >= start and offset <= end:
                        left = max(0, start - offset)
                        right = min(len(block), end - offset + 1)
                        selected.extend(block[left:right])
                    offset += len(block)
                after = os.fstat(stream.fileno())
            identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
            if (identity(before) != identity(after) or size != asset.size_bytes
                    or digest.hexdigest() != asset.sha256_hex
                    or len(selected) != end - start + 1):
                raise AudioPreviewError("AUDIO_INTEGRITY_MISMATCH", "audio preview integrity check failed")
            return AudioPreviewPayload(
                bytes(selected), asset.mime_type, f'"sha256-{asset.sha256_hex}"',
                AudioByteRange(start, end, size), partial,
            )
        except AudioPreviewError:
            raise
        except OSError as exc:
            raise AudioPreviewError("AUDIO_PREVIEW_UNAVAILABLE", "audio preview is unavailable") from exc
