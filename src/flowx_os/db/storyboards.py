"""Owner-scoped persistence for immutable storyboard versions and scene timelines."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from flowx_os.db.content import (
    OwnedContentNotFound,
    RepositoryUnavailable,
)
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.domain.content_state import ContentStatus, InvalidContentTransition, require_content_transition
from flowx_os.domain.storyboard import StoryboardTimeline


class StoryboardVersionConflict(RuntimeError):
    """The caller's expected version is stale."""

    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__("storyboard version changed")


class InvalidStoryboardTimeline(ValueError):
    """The timeline does not satisfy the owning content's duration contract."""


@dataclass(frozen=True, slots=True)
class StoryboardVersionRecord:
    content_id: UUID
    version: int
    title: str
    total_duration_ms: int
    storyboard: StoryboardTimeline
    created_at: datetime


def _record(row: tuple[object, ...]) -> StoryboardVersionRecord:
    try:
        content_id, version, title, duration, raw_timeline, created_at = row
        if isinstance(raw_timeline, str):
            raw_timeline = json.loads(raw_timeline)
        storyboard = StoryboardTimeline.model_validate(raw_timeline)
        if (not isinstance(content_id, UUID) or isinstance(version, bool)
                or not isinstance(version, int) or not isinstance(title, str)
                or isinstance(duration, bool) or not isinstance(duration, int)
                or not isinstance(created_at, datetime)):
            raise ValueError("stored storyboard row has invalid field types")
        return StoryboardVersionRecord(content_id, version, title, duration, storyboard, created_at)
    except Exception as exc:
        raise RepositoryUnavailable("stored storyboard version is invalid") from exc


class StoryboardRepository:
    """Store append-only storyboard snapshots while projecting versioned scenes."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def save_version(
        self, *, brand_id: UUID, content_id: UUID, owner_user_id: str,
        expected_version: int, storyboard: StoryboardTimeline,
    ) -> StoryboardVersionRecord:
        if (not isinstance(brand_id, UUID) or not isinstance(content_id, UUID)
                or not isinstance(owner_user_id, str) or not owner_user_id.strip()
                or isinstance(expected_version, bool) or not isinstance(expected_version, int)
                or expected_version < 0 or not isinstance(storyboard, StoryboardTimeline)):
            raise ValueError("storyboard version request is invalid")
        try:
            timeline_json = json.dumps(
                storyboard.model_dump(mode="json"),
                ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("storyboard timeline is not canonical JSON") from exc

        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT c.storyboard_version, c.target_duration_seconds, c.status
                       FROM content_items AS c
                       JOIN brands AS b ON b.id = c.brand_id
                       WHERE c.id = %s AND b.id = %s AND b.owner_user_id = %s
                       FOR UPDATE OF c""",
                    (content_id, brand_id, owner_user_id.strip()),
                )
                content = await cursor.fetchone()
                if content is None:
                    raise OwnedContentNotFound("content not found")
                current_version, target_duration, raw_status = content
                if (isinstance(current_version, bool) or not isinstance(current_version, int)
                        or isinstance(target_duration, bool) or not isinstance(target_duration, int)):
                    raise RepositoryUnavailable("stored content storyboard metadata is invalid")
                if expected_version != current_version:
                    raise StoryboardVersionConflict(current_version)
                if storyboard.total_duration_ms != target_duration * 1000:
                    raise InvalidStoryboardTimeline("timeline duration must equal the content target duration")
                try:
                    status = ContentStatus(raw_status)
                except (ValueError, TypeError) as exc:
                    raise RepositoryUnavailable("stored content status is invalid") from exc
                if status == ContentStatus.STORYBOARD_READY:
                    next_status = status
                else:
                    require_content_transition(status, ContentStatus.STORYBOARD_READY)
                    next_status = ContentStatus.STORYBOARD_READY

                version = current_version + 1
                cursor = await connection.execute(
                    """INSERT INTO storyboard_versions
                         (content_id, version, title, total_duration_ms, timeline_json, created_by_user_id)
                       VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                       RETURNING content_id, version, title, total_duration_ms, timeline_json, created_at""",
                    (content_id, version, storyboard.title, storyboard.total_duration_ms,
                     timeline_json, owner_user_id.strip()),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RepositoryUnavailable("storyboard version insert returned no row")

                for scene in storyboard.scenes:
                    cursor = await connection.execute(
                        """INSERT INTO scenes
                             (content_id, scene_index, start_ms, end_ms, beat, narration_text,
                              visual_prompt, prompt_version, storyboard_version)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (content_id, scene.scene_number, scene.start_ms, scene.end_ms,
                         scene.beat, scene.narration_text, scene.visual_prompt,
                         scene.prompt_version, version),
                    )
                cursor = await connection.execute(
                    """UPDATE content_items
                       SET storyboard_version = %s, status = %s, updated_at = now()
                       WHERE id = %s AND storyboard_version = %s
                       RETURNING storyboard_version, status""",
                    (version, next_status.value, content_id, current_version),
                )
                if await cursor.fetchone() is None:
                    raise StoryboardVersionConflict(current_version)
        except (OwnedContentNotFound, StoryboardVersionConflict, InvalidStoryboardTimeline,
                InvalidContentTransition, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("storyboard storage is unavailable") from exc
        return _record(row)

    async def list_versions(
        self, *, brand_id: UUID, content_id: UUID, owner_user_id: str,
    ) -> list[StoryboardVersionRecord]:
        if (not isinstance(brand_id, UUID) or not isinstance(content_id, UUID)
                or not isinstance(owner_user_id, str) or not owner_user_id.strip()):
            raise ValueError("content owner identity is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT 1 FROM content_items AS c
                       JOIN brands AS b ON b.id = c.brand_id
                       WHERE c.id = %s AND b.id = %s AND b.owner_user_id = %s""",
                    (content_id, brand_id, owner_user_id.strip()),
                )
                if await cursor.fetchone() is None:
                    raise OwnedContentNotFound("content not found")
                cursor = await connection.execute(
                    """SELECT sv.content_id, sv.version, sv.title, sv.total_duration_ms,
                              sv.timeline_json, sv.created_at
                       FROM storyboard_versions AS sv
                       JOIN content_items AS c ON c.id = sv.content_id
                       JOIN brands AS b ON b.id = c.brand_id
                       WHERE c.id = %s AND b.id = %s AND b.owner_user_id = %s
                       ORDER BY sv.version""",
                    (content_id, brand_id, owner_user_id.strip()),
                )
                rows = await cursor.fetchall()
        except (OwnedContentNotFound, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("storyboard storage is unavailable") from exc
        return [_record(row) for row in rows]
