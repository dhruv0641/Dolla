"""Fail-closed discovery and retrieval of media exposed by Google Flow MCP."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import urlparse

from flowx_os.flow_mcp.adapter import FlowAdapter
from flowx_os.flow_mcp.capabilities import FlowAdapterError, FlowOperation


class FlowMediaError(RuntimeError):
    """Sanitized error for invalid Flow media metadata or downloaded bytes."""


@dataclass(frozen=True, slots=True)
class FlowMediaItem:
    media_id: str
    kind: str
    title: str


@dataclass(frozen=True, slots=True)
class FlowProjectMedia:
    project_id: str
    project_url: str
    items: tuple[FlowMediaItem, ...]


@dataclass(frozen=True, slots=True)
class RetrievedFlowMedia:
    media_id: str
    title: str
    kind: str
    storage_path: Path
    mime_type: str
    size_bytes: int
    sha256_hex: str


_MIME_SIGNATURES = {
    "image/png": (".png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/jpeg": (".jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    "image/webp": (".webp", lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"),
    "video/mp4": (".mp4", lambda data: len(data) >= 12 and data[4:8] == b"ftyp"),
    "video/webm": (".webm", lambda data: data.startswith(b"\x1aE\xdf\xa3")),
}


def _valid_project_url(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 2048:
        return False
    parsed = urlparse(value)
    return (parsed.scheme == "https" and parsed.hostname in {"flow.google.com", "labs.google"}
            and bool(re.search(r"(?:^|/)project/[A-Za-z0-9_-]+(?:/|$)", parsed.path)))


class FlowMediaService:
    """Read project grid metadata and safely place validated media under a fixed root."""

    def __init__(self, adapter: FlowAdapter, *, account: FlowAccountAuthorization,
                 media_root: Path, max_bytes: int = 2_000_000_000) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._adapter = adapter
        self._account = account
        self._root = Path(media_root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        if self._root.is_symlink() or not self._root.is_dir():
            raise ValueError("media root must be a real directory")
        self._max_bytes = max_bytes

    async def list_project(self, *, project_url: str) -> FlowProjectMedia:
        if not _valid_project_url(project_url):
            raise ValueError("project URL must be an HTTPS Google Flow project URL")
        try:
            result = await self._adapter.invoke(
                FlowOperation.PROJECT_OPEN, {"project_url": project_url}, account=self._account,
            )
        except FlowAdapterError:
            raise
        except Exception as exc:
            raise FlowMediaError("Flow project metadata is unavailable") from exc
        project_id, raw_items = result.get("project_id"), result.get("media")
        if not isinstance(project_id, str) or not project_id.strip() or not isinstance(raw_items, (list, tuple)):
            raise FlowMediaError("Flow project metadata is malformed")
        items: list[FlowMediaItem] = []
        seen: set[str] = set()
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            media_id, kind, title = item.get("uuid"), item.get("kind"), item.get("title")
            if not isinstance(media_id, str) or not isinstance(kind, str) or not isinstance(title, str):
                continue
            try:
                normalized_id = str(uuid.UUID(media_id))
            except (ValueError, AttributeError):
                continue
            if normalized_id in seen or kind.casefold() not in {"image", "video"} or len(title) > 500:
                continue
            seen.add(normalized_id)
            items.append(FlowMediaItem(normalized_id, kind.casefold(), title))
        return FlowProjectMedia(project_id.strip(), project_url, tuple(items))

    async def retrieve(self, *, item: FlowMediaItem) -> RetrievedFlowMedia:
        if not isinstance(item, FlowMediaItem):
            raise ValueError("a discovered Flow media item is required")
        try:
            media_id = str(uuid.UUID(item.media_id))
        except (ValueError, AttributeError) as exc:
            raise ValueError("media ID must be a UUID from verified Flow metadata") from exc
        if item.kind not in {"image", "video"}:
            raise ValueError("unsupported Flow media kind")
        stage = Path(tempfile.mkdtemp(prefix=".flow-download-", dir=self._root)).resolve()
        try:
            try:
                result = await self._adapter.invoke(
                    FlowOperation.MEDIA_DOWNLOAD,
                    {"media_id": media_id, "output_dir": str(stage)}, account=self._account,
                )
            except FlowAdapterError:
                raise
            except Exception as exc:
                raise FlowMediaError("Flow media download failed") from exc
            raw_path, content_type = result.get("path"), result.get("content_type")
            if not isinstance(raw_path, str) or not isinstance(content_type, str):
                raise FlowMediaError("Flow media download metadata is malformed")
            mime_type = content_type.split(";", 1)[0].strip().casefold()
            signature = _MIME_SIGNATURES.get(mime_type)
            if signature is None or (item.kind == "image") != mime_type.startswith("image/"):
                raise FlowMediaError("Flow media type is unsupported or conflicts with project metadata")
            candidate = Path(raw_path)
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(stage)
            except (OSError, ValueError, RuntimeError) as exc:
                raise FlowMediaError("Flow returned a path outside its isolated download directory") from exc
            if (candidate.is_symlink() or resolved.parent != stage or not resolved.is_file()):
                raise FlowMediaError("Flow returned a non-regular media file")
            size = resolved.stat().st_size
            if size <= 0 or size > self._max_bytes:
                raise FlowMediaError("Flow media size is outside the configured limit")
            digest = hashlib.sha256()
            with resolved.open("rb") as stream:
                header = stream.read(32)
                if not signature[1](header):
                    raise FlowMediaError("Flow media bytes do not match the declared media type")
                digest.update(header)
                while block := stream.read(1024 * 1024):
                    digest.update(block)
            sha256_hex = digest.hexdigest()
            destination = self._root / f"flow_{media_id}_{sha256_hex[:12]}{signature[0]}"
            if destination.exists():
                if destination.is_symlink() or not destination.is_file() or destination.stat().st_size != size:
                    raise FlowMediaError("existing managed media path conflicts with retrieved data")
                existing_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
                if existing_hash != sha256_hex:
                    raise FlowMediaError("existing managed media path has a different content hash")
            else:
                # Stage is created inside media_root, so replace is same-volume and atomic.
                os.replace(resolved, destination)
            return RetrievedFlowMedia(media_id, item.title, item.kind, destination, mime_type, size, sha256_hex)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
