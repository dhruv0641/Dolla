"""Owner-scoped PostgreSQL repositories for brands and content items."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.domain.content_state import (
    ContentStatus,
    InvalidContentTransition,
    require_content_transition,
)


class RepositoryUnavailable(RuntimeError):
    """Raised when the configured repository cannot complete a database call."""


class OwnedBrandNotFound(LookupError):
    """Raised when a brand is absent or belongs to another principal."""


class OwnedContentNotFound(LookupError):
    """Raised when content is absent or not under an owned brand."""


@dataclass(frozen=True, slots=True)
class BrandRecord:
    id: UUID
    name: str
    owner_user_id: str
    timezone: str
    niche: str
    audience: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ContentRecord:
    id: UUID
    brand_id: UUID
    title: str
    idea_text: str
    topic: str | None
    audience_segment: str | None
    language: str
    target_duration_seconds: int
    priority: int
    status: str
    created_at: datetime

    @property
    def typed_status(self) -> ContentStatus:
        return ContentStatus(self.status)


class ContentRepository:
    """Persist owner-scoped brand and content rows using a pooled SQL connection."""

    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    async def create_brand(
        self, *, owner_user_id: str, name: str, timezone_name: str,
        niche: str = "", audience: str = "",
    ) -> BrandRecord:
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """INSERT INTO brands (name, owner_user_id, timezone, niche, audience)
                       VALUES (%s, %s, %s, %s, %s)
                       RETURNING id, name, owner_user_id, timezone, niche, audience, created_at, updated_at""",
                    (name, owner_user_id, timezone_name, niche, audience),
                )
                row = await cursor.fetchone()
        except Exception as exc:
            raise RepositoryUnavailable("brand storage is unavailable") from exc
        if row is None:
            raise RepositoryUnavailable("brand insert returned no row")
        return BrandRecord(*row)

    async def list_brands(self, *, owner_user_id: str) -> list[BrandRecord]:
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT id, name, owner_user_id, timezone, niche, audience, created_at, updated_at
                       FROM brands WHERE owner_user_id = %s ORDER BY created_at, id""",
                    (owner_user_id,),
                )
                rows = await cursor.fetchall()
        except Exception as exc:
            raise RepositoryUnavailable("brand storage is unavailable") from exc
        return [BrandRecord(*row) for row in rows]

    async def create_content(
        self,
        *,
        brand_id: UUID,
        owner_user_id: str,
        title: str,
        idea_text: str,
        topic: str | None,
        audience_segment: str | None,
        language: str,
        target_duration_seconds: int,
        priority: int,
    ) -> ContentRecord:
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """INSERT INTO content_items
                         (brand_id, title, idea_text, topic, audience_segment, language,
                          target_duration_seconds, priority)
                       SELECT b.id, %s, %s, %s, %s, %s, %s, %s
                       FROM brands AS b WHERE b.id = %s AND b.owner_user_id = %s
                       RETURNING id, brand_id, title, idea_text, topic, audience_segment,
                                 language, target_duration_seconds, priority, status, created_at""",
                    (title, idea_text, topic, audience_segment, language,
                     target_duration_seconds, priority, brand_id, owner_user_id),
                )
                row = await cursor.fetchone()
        except Exception as exc:
            raise RepositoryUnavailable("content storage is unavailable") from exc
        if row is None:
            raise OwnedBrandNotFound("brand not found")
        return ContentRecord(*row)

    async def list_content(self, *, brand_id: UUID, owner_user_id: str) -> list[ContentRecord]:
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT c.id, c.brand_id, c.title, c.idea_text, c.topic, c.audience_segment,
                              c.language, c.target_duration_seconds, c.priority, c.status, c.created_at
                       FROM content_items AS c JOIN brands AS b ON b.id = c.brand_id
                       WHERE b.id = %s AND b.owner_user_id = %s
                       ORDER BY c.created_at DESC, c.id""",
                    (brand_id, owner_user_id),
                )
                rows = await cursor.fetchall()
                if not rows:
                    cursor = await connection.execute(
                        "SELECT 1 FROM brands WHERE id = %s AND owner_user_id = %s",
                        (brand_id, owner_user_id),
                    )
                    if await cursor.fetchone() is None:
                        raise OwnedBrandNotFound("brand not found")
        except OwnedBrandNotFound:
            raise
        except Exception as exc:
            raise RepositoryUnavailable("content storage is unavailable") from exc
        return [ContentRecord(*row) for row in rows]

    async def transition_content(
        self,
        *,
        brand_id: UUID,
        content_id: UUID,
        owner_user_id: str,
        target_status: ContentStatus,
    ) -> ContentRecord:
        """Lock and validate an owned content row before persisting its next state."""
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT c.status FROM content_items AS c
                       JOIN brands AS b ON b.id = c.brand_id
                       WHERE c.id = %s AND b.id = %s AND b.owner_user_id = %s
                       FOR UPDATE OF c""",
                    (content_id, brand_id, owner_user_id),
                )
                current_row = await cursor.fetchone()
                if current_row is None:
                    raise OwnedContentNotFound("content not found")
                try:
                    current = ContentStatus(current_row[0])
                except (ValueError, TypeError) as exc:
                    raise RepositoryUnavailable("content has an unsupported stored status") from exc
                try:
                    require_content_transition(current, target_status)
                except InvalidContentTransition:
                    raise
                cursor = await connection.execute(
                    """UPDATE content_items AS c SET status = %s, updated_at = now()
                       FROM brands AS b
                       WHERE c.id = %s AND c.brand_id = b.id AND b.id = %s
                         AND b.owner_user_id = %s AND c.status = %s
                       RETURNING c.id, c.brand_id, c.title, c.idea_text, c.topic,
                                 c.audience_segment, c.language, c.target_duration_seconds,
                                 c.priority, c.status, c.created_at""",
                    (target_status.value, content_id, brand_id, owner_user_id, current.value),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise OwnedContentNotFound("content not found")
        except (OwnedContentNotFound, InvalidContentTransition, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("content storage is unavailable") from exc
        return ContentRecord(*row)
