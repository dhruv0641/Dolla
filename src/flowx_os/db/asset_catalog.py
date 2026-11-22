"""Tenant-scoped asset discovery and conservative retention tombstones."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from flowx_os.db.assets import AssetRecord, _QUALIFIED_ASSET_COLUMNS, _record
from flowx_os.db.content import OwnedContentNotFound, RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.domain.assets import AssetKind


class AssetRetentionBlocked(RuntimeError):
    """A retained reference or lifecycle state prohibits retirement."""


@dataclass(frozen=True, slots=True)
class AssetSearchPage:
    records: tuple[AssetRecord, ...]
    next_cursor: tuple[datetime, UUID] | None


class AssetCatalogRepository:
    """Search owned assets and hide retired entries by default."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def get_active_audio(
        self, *, asset_id: UUID, brand_id: UUID, content_id: UUID,
        owner_user_id: str,
    ) -> AssetRecord:
        """Return one active audio asset without disclosing foreign/retired rows."""
        if (not isinstance(asset_id, UUID) or not isinstance(brand_id, UUID)
                or not isinstance(content_id, UUID) or not isinstance(owner_user_id, str)
                or not owner_user_id.strip()):
            raise ValueError("audio asset lookup is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""SELECT {_QUALIFIED_ASSET_COLUMNS}
                       FROM assets AS a JOIN content_items AS c ON c.id = a.content_id
                       JOIN brands AS b ON b.id = c.brand_id
                       WHERE a.id = %s AND c.id = %s AND b.id = %s
                         AND b.owner_user_id = %s AND a.retention_state = 'ACTIVE'
                         AND a.mime_type LIKE 'audio/%'""",
                    (asset_id, content_id, brand_id, owner_user_id.strip()),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise OwnedContentNotFound("audio asset not found")
                return _record(row)
        except (OwnedContentNotFound, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("audio asset lookup is unavailable") from exc

    async def search(
        self, *, owner_user_id: str, brand_id: UUID | None = None,
        content_id: UUID | None = None, scene_id: UUID | None = None,
        kind: AssetKind | None = None, mime_type: str | None = None,
        limit: int = 50, cursor: tuple[datetime, UUID] | None = None,
    ) -> AssetSearchPage:
        if not isinstance(owner_user_id, str) or not owner_user_id.strip():
            raise ValueError("owner identity is required")
        if any(value is not None and not isinstance(value, UUID)
               for value in (brand_id, content_id, scene_id)):
            raise ValueError("asset search scope is invalid")
        if kind is not None and not isinstance(kind, AssetKind):
            raise ValueError("asset kind is invalid")
        if (mime_type is not None and (not isinstance(mime_type, str)
                or not 3 <= len(mime_type) <= 120 or any(ord(c) < 32 for c in mime_type))):
            raise ValueError("asset MIME filter is invalid")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("asset search limit must be between 1 and 100")
        if cursor is not None and (
            not isinstance(cursor, tuple) or len(cursor) != 2
            or not isinstance(cursor[0], datetime) or cursor[0].tzinfo is None
            or not isinstance(cursor[1], UUID)
        ):
            raise ValueError("asset search cursor is invalid")
        query = f"""SELECT {_QUALIFIED_ASSET_COLUMNS}
            FROM assets AS a JOIN content_items AS c ON c.id = a.content_id
            JOIN brands AS b ON b.id = c.brand_id
            WHERE b.owner_user_id = %s AND a.retention_state = 'ACTIVE'"""
        params: list[object] = [owner_user_id.strip()]
        for clause, value in (
            ("b.id", brand_id), ("c.id", content_id), ("a.scene_id", scene_id),
            ("a.asset_kind", kind.value if kind is not None else None),
            ("a.mime_type", mime_type),
        ):
            if value is not None:
                query += f" AND {clause} = %s"
                params.append(value)
        if cursor is not None:
            query += " AND (a.created_at, a.id) < (%s, %s)"
            params.extend(cursor)
        query += " ORDER BY a.created_at DESC, a.id DESC LIMIT %s"
        params.append(limit + 1)
        try:
            async with unit_of_work(self._pool) as connection:
                rows = await (await connection.execute(query, tuple(params))).fetchall()
        except Exception as exc:
            raise RepositoryUnavailable("asset search is unavailable") from exc
        records = tuple(_record(row) for row in rows[:limit])
        next_cursor = None
        if len(rows) > limit and records:
            last = records[-1]
            next_cursor = last.created_at, last.metadata.asset_id
        return AssetSearchPage(records, next_cursor)

    async def tombstone(
        self, *, asset_id: UUID, owner_user_id: str, created_before: datetime,
        reason: str,
    ) -> bool:
        """Hide an old unreferenced asset; preserve its bytes and metadata.

        Returns false for an idempotent repeat. Explicit purge is a separate step.
        """
        if not isinstance(asset_id, UUID) or not isinstance(owner_user_id, str) or not owner_user_id.strip():
            raise ValueError("asset retention identity is invalid")
        if (not isinstance(created_before, datetime) or created_before.tzinfo is None
                or created_before >= datetime.now(timezone.utc)):
            raise ValueError("explicit past retention cutoff is required")
        if (not isinstance(reason, str) or not 3 <= len(reason) <= 100
                or any(ord(c) < 32 for c in reason)):
            raise ValueError("asset retention reason is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT a.retention_state, a.created_at, c.id, c.status
                       FROM assets AS a JOIN content_items AS c ON c.id = a.content_id
                       JOIN brands AS b ON b.id = c.brand_id
                       WHERE a.id = %s AND b.owner_user_id = %s
                       FOR UPDATE OF a, c""",
                    (asset_id, owner_user_id.strip()),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise OwnedContentNotFound("asset not found")
                state, created_at, content_id, content_status = row
                if state in {"TOMBSTONED", "PURGE_PENDING", "PURGED"}:
                    return False
                if state != "ACTIVE" or content_status != "ARCHIVED" or created_at >= created_before:
                    raise AssetRetentionBlocked("asset is not eligible for retention")
                cursor = await connection.execute(
                    """SELECT (
                      EXISTS (SELECT 1 FROM scenes WHERE approved_asset_id = %s)
                      OR EXISTS (SELECT 1 FROM qa_reports WHERE asset_id = %s)
                      OR EXISTS (SELECT 1 FROM review_decisions WHERE asset_id = %s)
                      OR EXISTS (SELECT 1 FROM render_jobs WHERE content_id = %s)
                      OR EXISTS (SELECT 1 FROM publication_jobs WHERE content_id = %s)
                    )""",
                    (asset_id, asset_id, asset_id, content_id, content_id),
                )
                referenced = await cursor.fetchone()
                if referenced is None or referenced[0]:
                    raise AssetRetentionBlocked("asset has retained references")
                cursor = await connection.execute(
                    """UPDATE assets SET retention_state = 'TOMBSTONED',
                         retention_reason = %s, retention_actor = %s, tombstoned_at = now()
                       WHERE id = %s AND retention_state = 'ACTIVE'""",
                    (reason.strip(), owner_user_id.strip(), asset_id),
                )
                if cursor.rowcount != 1:
                    raise RepositoryUnavailable("asset retirement changed concurrently")
                return True
        except (OwnedContentNotFound, AssetRetentionBlocked, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("asset retention is unavailable") from exc

    async def prepare_purge(self, *, asset_id: UUID, owner_user_id: str) -> AssetRecord | None:
        """Durably claim a retired asset before any local bytes are removed."""
        if not isinstance(asset_id, UUID) or not isinstance(owner_user_id, str) or not owner_user_id.strip():
            raise ValueError("asset purge identity is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""SELECT {_QUALIFIED_ASSET_COLUMNS}, a.retention_state, c.status
                        FROM assets AS a JOIN content_items AS c ON c.id = a.content_id
                        JOIN brands AS b ON b.id = c.brand_id
                        WHERE a.id = %s AND b.owner_user_id = %s
                        FOR UPDATE OF a, c""",
                    (asset_id, owner_user_id.strip()),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise OwnedContentNotFound("asset not found")
                state, content_status = row[-2:]
                if state == "PURGED":
                    return None
                if state not in {"TOMBSTONED", "PURGE_PENDING"} or content_status != "ARCHIVED":
                    raise AssetRetentionBlocked("asset is not ready for purge")
                record = _record(row[:-2])
                cursor = await connection.execute(
                    """SELECT (
                      EXISTS (SELECT 1 FROM scenes WHERE approved_asset_id = %s)
                      OR EXISTS (SELECT 1 FROM qa_reports WHERE asset_id = %s)
                      OR EXISTS (SELECT 1 FROM review_decisions WHERE asset_id = %s)
                      OR EXISTS (SELECT 1 FROM render_jobs WHERE content_id = %s)
                      OR EXISTS (SELECT 1 FROM publication_jobs WHERE content_id = %s)
                    )""",
                    (asset_id, asset_id, asset_id, record.metadata.content_id,
                     record.metadata.content_id),
                )
                referenced = await cursor.fetchone()
                if referenced is None or referenced[0]:
                    raise AssetRetentionBlocked("asset has retained references")
                if state == "TOMBSTONED":
                    cursor = await connection.execute(
                        """UPDATE assets SET retention_state = 'PURGE_PENDING'
                           WHERE id = %s AND retention_state = 'TOMBSTONED'""",
                        (asset_id,),
                    )
                    if cursor.rowcount != 1:
                        raise RepositoryUnavailable("asset purge state changed concurrently")
                return record
        except (OwnedContentNotFound, AssetRetentionBlocked, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("asset purge preparation is unavailable") from exc

    async def mark_purged(self, *, asset_id: UUID, owner_user_id: str) -> bool:
        """Record physical deletion only after the local unlink succeeded."""
        if not isinstance(asset_id, UUID) or not isinstance(owner_user_id, str) or not owner_user_id.strip():
            raise ValueError("asset purge identity is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT a.retention_state FROM assets AS a
                       JOIN content_items AS c ON c.id = a.content_id
                       JOIN brands AS b ON b.id = c.brand_id
                       WHERE a.id = %s AND b.owner_user_id = %s FOR UPDATE OF a""",
                    (asset_id, owner_user_id.strip()),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise OwnedContentNotFound("asset not found")
                if row[0] == "PURGED":
                    return False
                if row[0] != "PURGE_PENDING":
                    raise AssetRetentionBlocked("asset purge was not prepared")
                cursor = await connection.execute(
                    """UPDATE assets SET retention_state = 'PURGED', purged_at = now()
                       WHERE id = %s AND retention_state = 'PURGE_PENDING'""",
                    (asset_id,),
                )
                if cursor.rowcount != 1:
                    raise RepositoryUnavailable("asset purge state changed concurrently")
                return True
        except (OwnedContentNotFound, AssetRetentionBlocked, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("asset purge completion is unavailable") from exc
