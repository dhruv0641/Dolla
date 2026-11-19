"""Owner-scoped asset registry and verified media lineage persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from flowx_os.db.content import OwnedContentNotFound, RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, TransactionConnection, unit_of_work
from flowx_os.domain.assets import AssetKind, AssetMetadata


class AssetConflict(RuntimeError):
    """An asset UUID or managed URI already identifies different metadata."""


class InvalidAssetLineage(ValueError):
    """The supplied scene or generation job is outside the requested content lineage."""


@dataclass(frozen=True, slots=True)
class AssetRecord:
    metadata: AssetMetadata
    created_at: datetime


def _record(row: tuple[object, ...]) -> AssetRecord:
    try:
        (asset_id, content_id, scene_id, kind, storage_uri, sha256_hex, mime_type,
         size_bytes, media_metadata, source_job_id, created_at) = row
        if isinstance(media_metadata, str):
            media_metadata = json.loads(media_metadata)
        metadata = AssetMetadata(
            asset_id=asset_id, content_id=content_id, scene_id=scene_id,
            kind=AssetKind(kind), storage_uri=storage_uri, sha256_hex=sha256_hex.strip(),
            mime_type=mime_type, size_bytes=size_bytes, media_metadata=media_metadata,
            source_job_id=source_job_id,
        )
        if not isinstance(created_at, datetime):
            raise ValueError("invalid asset creation timestamp")
        return AssetRecord(metadata, created_at)
    except Exception as exc:
        raise RepositoryUnavailable("stored asset metadata is invalid") from exc


_ASSET_COLUMNS = """id, content_id, scene_id, asset_kind, storage_uri, sha256_hex,
                    mime_type, size_bytes, media_metadata, source_job_id, created_at"""
_QUALIFIED_ASSET_COLUMNS = ", ".join(
    f"a.{column.strip()}" for column in _ASSET_COLUMNS.replace("\n", "").split(",")
)


class AssetRepository:
    """Register immutable asset metadata only under an authenticated content owner."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def assert_lineage(
        self, *, brand_id: UUID, content_id: UUID, owner_user_id: str,
        scene_id: UUID | None = None, source_job_id: UUID | None = None,
        asset_id: UUID | None = None,
    ) -> None:
        """Check ownership and optional lineage before placing bytes on disk."""
        if (not isinstance(brand_id, UUID) or not isinstance(content_id, UUID)
                or not isinstance(owner_user_id, str) or not owner_user_id.strip()
                or (scene_id is not None and not isinstance(scene_id, UUID))
                or (source_job_id is not None and not isinstance(source_job_id, UUID))
                or (asset_id is not None and not isinstance(asset_id, UUID))
                or (source_job_id is not None and scene_id is None)):
            raise ValueError("asset lineage request is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                await self._assert_lineage_in_transaction(
                    connection, brand_id=brand_id, content_id=content_id,
                    owner_user_id=owner_user_id, scene_id=scene_id,
                    source_job_id=source_job_id, lock_content=False,
                )
                if asset_id is not None:
                    cursor = await connection.execute(
                        "SELECT retention_state FROM assets WHERE id = %s FOR SHARE",
                        (asset_id,),
                    )
                    row = await cursor.fetchone()
                    if row is not None and row[0] != "ACTIVE":
                        raise AssetConflict("asset identity has been retired")
        except (OwnedContentNotFound, InvalidAssetLineage, AssetConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("asset storage is unavailable") from exc

    async def register(
        self, *, brand_id: UUID, owner_user_id: str, metadata: AssetMetadata,
    ) -> AssetRecord:
        if (not isinstance(brand_id, UUID) or not isinstance(owner_user_id, str)
                or not owner_user_id.strip() or not isinstance(metadata, AssetMetadata)):
            raise ValueError("asset registration request is invalid")
        try:
            media_json = json.dumps(
                metadata.media_metadata, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
            if len(media_json.encode("utf-8")) > 65_536:
                raise ValueError("asset media metadata is too large")
        except (TypeError, ValueError) as exc:
            raise ValueError("asset media metadata must be bounded JSON") from exc

        try:
            async with unit_of_work(self._pool) as connection:
                await self._assert_lineage_in_transaction(
                    connection, brand_id=brand_id, content_id=metadata.content_id,
                    owner_user_id=owner_user_id, scene_id=metadata.scene_id,
                    source_job_id=metadata.source_job_id, lock_content=True,
                )
                cursor = await connection.execute(
                    f"""INSERT INTO assets
                         (id, content_id, scene_id, asset_kind, storage_uri, sha256_hex,
                          mime_type, size_bytes, media_metadata, source_job_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                       ON CONFLICT (id) DO NOTHING
                       RETURNING {_ASSET_COLUMNS}""",
                    (metadata.asset_id, metadata.content_id, metadata.scene_id,
                     metadata.kind.value, metadata.storage_uri, metadata.sha256_hex,
                     metadata.mime_type, metadata.size_bytes, media_json, metadata.source_job_id),
                )
                row = await cursor.fetchone()
                if row is not None:
                    return _record(row)
                cursor = await connection.execute(
                    f"""SELECT {_QUALIFIED_ASSET_COLUMNS}
                       FROM assets AS a JOIN content_items AS c ON c.id = a.content_id
                       JOIN brands AS b ON b.id = c.brand_id
                       WHERE a.id = %s AND b.owner_user_id = %s
                         AND a.retention_state = 'ACTIVE'""",
                    (metadata.asset_id, owner_user_id.strip()),
                )
                existing_row = await cursor.fetchone()
                if existing_row is None:
                    raise AssetConflict("asset identity is already registered")
                existing = _record(existing_row)
                if existing.metadata != metadata:
                    raise AssetConflict("asset identity already refers to different metadata")
                return existing
        except (OwnedContentNotFound, InvalidAssetLineage, AssetConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("asset storage is unavailable") from exc

    async def _assert_lineage_in_transaction(
        self, connection: TransactionConnection, *, brand_id: UUID, content_id: UUID, owner_user_id: str,
        scene_id: UUID | None, source_job_id: UUID | None, lock_content: bool,
    ) -> None:
        lock = " FOR KEY SHARE OF c" if lock_content else ""
        cursor = await connection.execute(
            """SELECT 1 FROM content_items AS c JOIN brands AS b ON b.id = c.brand_id
               WHERE c.id = %s AND b.id = %s AND b.owner_user_id = %s""" + lock,
            (content_id, brand_id, owner_user_id.strip()),
        )
        if await cursor.fetchone() is None:
            raise OwnedContentNotFound("content not found")
        if scene_id is not None:
            cursor = await connection.execute(
                "SELECT 1 FROM scenes WHERE id = %s AND content_id = %s",
                (scene_id, content_id),
            )
            if await cursor.fetchone() is None:
                raise InvalidAssetLineage("scene is not part of the requested content")
        if source_job_id is not None:
            cursor = await connection.execute(
                """SELECT 1 FROM generation_jobs AS j JOIN scenes AS s ON s.id = j.scene_id
                   WHERE j.id = %s AND j.scene_id = %s AND s.content_id = %s""",
                (source_job_id, scene_id, content_id),
            )
            if await cursor.fetchone() is None:
                raise InvalidAssetLineage("generation job is not part of the requested scene")

    async def list_for_content(
        self, *, brand_id: UUID, content_id: UUID, owner_user_id: str,
        scene_id: UUID | None = None,
    ) -> list[AssetRecord]:
        if (not isinstance(brand_id, UUID) or not isinstance(content_id, UUID)
                or not isinstance(owner_user_id, str) or not owner_user_id.strip()
                or (scene_id is not None and not isinstance(scene_id, UUID))):
            raise ValueError("asset query is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT 1 FROM content_items AS c JOIN brands AS b ON b.id = c.brand_id
                       WHERE c.id = %s AND b.id = %s AND b.owner_user_id = %s""",
                    (content_id, brand_id, owner_user_id.strip()),
                )
                if await cursor.fetchone() is None:
                    raise OwnedContentNotFound("content not found")
                if scene_id is not None:
                    cursor = await connection.execute(
                        "SELECT 1 FROM scenes WHERE id = %s AND content_id = %s",
                        (scene_id, content_id),
                    )
                    if await cursor.fetchone() is None:
                        raise InvalidAssetLineage("scene is not part of the requested content")
                query = f"""SELECT {_QUALIFIED_ASSET_COLUMNS}
                             FROM assets AS a JOIN content_items AS c ON c.id = a.content_id
                             JOIN brands AS b ON b.id = c.brand_id
                             WHERE c.id = %s AND b.id = %s AND b.owner_user_id = %s
                               AND a.retention_state = 'ACTIVE'"""
                params: tuple[object, ...] = (content_id, brand_id, owner_user_id.strip())
                if scene_id is not None:
                    query += " AND a.scene_id = %s"
                    params += (scene_id,)
                query += " ORDER BY a.created_at, a.id"
                cursor = await connection.execute(query, params)
                rows = await cursor.fetchall()
        except (OwnedContentNotFound, InvalidAssetLineage, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("asset storage is unavailable") from exc
        return [_record(row) for row in rows]
