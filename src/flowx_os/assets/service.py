"""Coordinate validated local asset storage with owner-scoped asset lineage."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

from flowx_os.assets.storage import AssetStorageError, ManagedAssetStore
from flowx_os.db.assets import AssetConflict, AssetRepository, AssetRecord, InvalidAssetLineage
from flowx_os.db.content import OwnedContentNotFound, RepositoryUnavailable
from flowx_os.domain.assets import AssetKind, AssetMetadata


class AssetIngestError(RuntimeError):
    """A managed asset could not be stored and registered consistently."""


class AssetIngestService:
    """Validate, store and register an asset using a stable caller-provided UUID."""

    def __init__(self, *, storage_root: Path, repository: AssetRepository,
                 max_bytes: int = 2_000_000_000) -> None:
        self._store = ManagedAssetStore(storage_root, max_bytes=max_bytes)
        self._repository = repository

    async def ingest(
        self, *, asset_id: UUID, source_path: Path, mime_type: str,
        brand_id: UUID, content_id: UUID, owner_user_id: str, kind: AssetKind,
        scene_id: UUID | None = None, source_job_id: UUID | None = None,
        media_metadata: dict[str, object] | None = None,
    ) -> AssetRecord:
        """Store immutable bytes and then register their verified digest and lineage.

        The asset UUID is the idempotency key. If PostgreSQL is unavailable after
        the atomic file placement, a retry with the same ID and same bytes safely
        reuses that object; a retry with different bytes fails closed.
        """
        try:
            if (not isinstance(asset_id, UUID) or not isinstance(brand_id, UUID)
                    or not isinstance(content_id, UUID)
                    or (scene_id is not None and not isinstance(scene_id, UUID))
                    or (source_job_id is not None and not isinstance(source_job_id, UUID))
                    or not isinstance(owner_user_id, str) or not owner_user_id.strip()
                    or not isinstance(kind, AssetKind)):
                raise ValueError("asset ingest identity or lineage is invalid")
            media_values = media_metadata if media_metadata is not None else {}
            serialized_media = json.dumps(
                media_values, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
            if len(serialized_media.encode("utf-8")) > 65_536:
                raise ValueError("asset media metadata is too large")
            # Validate caller-controlled metadata before writing any bytes.
            AssetMetadata(
                asset_id=asset_id, content_id=content_id, scene_id=scene_id,
                source_job_id=source_job_id, kind=kind,
                storage_uri=f"managed://assets/{asset_id.hex}/payload",
                sha256_hex="0" * 64, mime_type=mime_type, size_bytes=1,
                media_metadata=media_values,
            )
            await self._repository.assert_lineage(
                brand_id=brand_id, content_id=content_id, owner_user_id=owner_user_id,
                scene_id=scene_id, source_job_id=source_job_id,
            )
            stored = await asyncio.to_thread(
                self._store.store, asset_id=asset_id, source_path=source_path, mime_type=mime_type,
            )
            metadata = AssetMetadata(
                asset_id=asset_id,
                content_id=content_id,
                scene_id=scene_id,
                source_job_id=source_job_id,
                kind=kind,
                storage_uri=stored.storage_uri,
                sha256_hex=stored.sha256_hex,
                mime_type=stored.mime_type,
                size_bytes=stored.size_bytes,
                media_metadata=media_values,
            )
            return await self._repository.register(
                brand_id=brand_id, owner_user_id=owner_user_id, metadata=metadata,
            )
        except (ValueError, AssetStorageError, AssetConflict, InvalidAssetLineage,
                OwnedContentNotFound, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise AssetIngestError("asset ingest failed; inspect the recorded asset state before retrying") from exc
