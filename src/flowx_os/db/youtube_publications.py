"""Owner-scoped persistence for official YouTube publication claims."""

from __future__ import annotations

from datetime import datetime
import json
import re
from uuid import UUID

from flowx_os.db.content import OwnedContentNotFound, RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.publishing.youtube import (
    YouTubeError,
    YouTubePrivacy,
    YouTubePublicationClaim,
    YouTubePublicationResult,
    YouTubePublishRequest,
    YouTubeRemoteVideo,
    YouTubeUploadOutcome,
    YouTubeUploadSession,
    YouTubeUploadState,
)


class YouTubePublicationConflict(RuntimeError):
    """A request or publication identity already names different work."""


class YouTubePublicationNotAllowed(RuntimeError):
    """The approved asset/channel/content evidence is not publishable."""


_CLAIM_COLUMNS = """p.id, p.request_fingerprint, b.id, b.owner_user_id,
    p.content_id, p.channel_id,
    p.asset_id, p.approval_decision_id, p.artifact_version,
    ch.external_channel_id, ch.credentials_ref, a.storage_uri, a.sha256_hex,
    a.size_bytes, a.mime_type, p.intended_privacy_status, p.status,
    p.upload_session_ref, p.remote_upload_id, p.remote_post_id"""
_SAFE_REMOTE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


class YouTubePublicationRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def claim(self, request: YouTubePublishRequest) -> YouTubePublicationClaim:
        if not isinstance(request, YouTubePublishRequest):
            raise ValueError("YouTube publication request is required")
        metadata = json.dumps(
            request.metadata, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT c.status
                       FROM content_items AS c
                       JOIN brands AS b ON b.id = c.brand_id
                       WHERE c.id = %s AND c.brand_id = %s AND b.owner_user_id = %s
                       FOR UPDATE OF c""",
                    (request.content_id, request.brand_id, request.owner_user_id),
                )
                owned = await cursor.fetchone()
                if owned is None:
                    raise OwnedContentNotFound("content not found")

                existing = await self._find_request(
                    connection, request_id=request.request_id,
                    brand_id=request.brand_id, owner_user_id=request.owner_user_id,
                )
                if existing is not None:
                    claim = self._claim(existing)
                    if claim.publication_id != request.publication_id or claim.request_fingerprint != request.fingerprint:
                        raise YouTubePublicationConflict("YouTube request already identifies different work")
                    return claim
                if owned[0] != "READY":
                    raise YouTubePublicationNotAllowed("content is not ready for publication")

                cursor = await connection.execute(
                    """SELECT a.asset_kind, a.retention_state, a.storage_uri,
                              a.sha256_hex, a.mime_type, a.size_bytes, a.media_metadata,
                              rja.profile_id, rj.render_version, rd.id, rd.decision,
                              ch.platform, ch.external_channel_id, ch.credentials_ref,
                              ch.permissions_status, ch.enabled
                       FROM assets AS a
                       JOIN render_job_artifacts AS rja
                         ON rja.asset_id = a.id AND rja.artifact_role = 'EXPORT_VARIANT'
                       JOIN render_jobs AS rj
                         ON rj.id = rja.render_job_id AND rj.content_id = a.content_id
                        AND rj.status = 'DONE'
                       JOIN review_decisions AS rd
                         ON rd.asset_id = a.id AND rd.content_id = a.content_id
                        AND rd.decision = 'APPROVE' AND rd.request_id IS NOT NULL
                       JOIN social_channels AS ch
                         ON ch.id = %s AND ch.brand_id = %s
                       WHERE a.id = %s AND a.content_id = %s AND a.scene_id IS NULL
                       ORDER BY rd.created_at DESC LIMIT 1
                       FOR KEY SHARE OF a, rja, rj, rd, ch""",
                    (request.channel_id, request.brand_id, request.asset_id, request.content_id),
                )
                evidence = await cursor.fetchone()
                if evidence is None:
                    raise YouTubePublicationNotAllowed("exact approved YouTube export is unavailable")
                (kind, retention, storage_uri, sha256_hex, mime_type, size_bytes,
                 raw_media, profile_id, render_version, approval_id, decision,
                 platform, external_channel_id, credentials_ref, permissions, enabled) = evidence
                media = json.loads(raw_media) if isinstance(raw_media, str) else raw_media
                if not self._eligible(
                    request=request, kind=kind, retention=retention, storage_uri=storage_uri,
                    sha256_hex=sha256_hex, mime_type=mime_type, size_bytes=size_bytes,
                    media=media, profile_id=profile_id, render_version=render_version,
                    approval_id=approval_id, decision=decision, platform=platform,
                    external_channel_id=external_channel_id, credentials_ref=credentials_ref,
                    permissions=permissions, enabled=enabled,
                ):
                    raise YouTubePublicationNotAllowed("YouTube publication evidence is not eligible")

                cursor = await connection.execute(
                    f"""INSERT INTO publication_jobs
                         (id, request_id, request_fingerprint, content_id, channel_id,
                          asset_id, approval_decision_id, artifact_version,
                          asset_sha256_hex, asset_size_bytes, intended_privacy_status,
                          platform_metadata, status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s::jsonb, 'DRAFT')
                       ON CONFLICT (request_id) WHERE request_id IS NOT NULL DO NOTHING
                       RETURNING id""",
                    (
                        request.publication_id, request.request_id, request.fingerprint,
                        request.content_id, request.channel_id, request.asset_id,
                        approval_id, request.artifact_version, sha256_hex,
                        size_bytes, request.privacy_status.value, metadata,
                    ),
                )
                inserted = await cursor.fetchone()
                row = await self._find_request(
                    connection, request_id=request.request_id,
                    brand_id=request.brand_id, owner_user_id=request.owner_user_id,
                )
                if row is None:
                    raise YouTubePublicationConflict("YouTube publication claim is unavailable")
                claim = self._claim(row)
                if claim.publication_id != request.publication_id or claim.request_fingerprint != request.fingerprint:
                    raise YouTubePublicationConflict("YouTube request already identifies different work")
                return claim
        except (OwnedContentNotFound, YouTubePublicationConflict,
                YouTubePublicationNotAllowed, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("YouTube publication storage is unavailable") from exc

    async def record_session(
        self, *, claim: YouTubePublicationClaim, session: YouTubeUploadSession,
    ) -> YouTubePublicationClaim:
        if not isinstance(claim, YouTubePublicationClaim) or not isinstance(session, YouTubeUploadSession):
            raise ValueError("YouTube upload session update is invalid")
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = 'UPLOAD_STARTED',
                      upload_session_ref = %s, remote_upload_id = %s,
                      last_error_code = NULL, last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s AND status = 'DRAFT'
               RETURNING id""",
            (session.session_ref, session.upload_id, claim.publication_id, claim.request_fingerprint),
        )

    async def record_upload(
        self, *, claim: YouTubePublicationClaim, outcome: YouTubeUploadOutcome,
    ) -> YouTubePublicationClaim:
        if not isinstance(claim, YouTubePublicationClaim) or not isinstance(outcome, YouTubeUploadOutcome):
            raise ValueError("YouTube upload update is invalid")
        status = {
            YouTubeUploadState.INCOMPLETE: "UPLOAD_STARTED",
            YouTubeUploadState.COMPLETE: "PROCESSING",
            YouTubeUploadState.UNKNOWN: "VERIFY_PENDING",
        }[outcome.state]
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = %s, uploaded_bytes = %s,
                      remote_post_id = COALESCE(%s, remote_post_id),
                      last_error_code = NULL, last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status IN ('UPLOAD_STARTED','VERIFY_PENDING')
               RETURNING id""",
            (status, outcome.committed_bytes, outcome.video_id,
             claim.publication_id, claim.request_fingerprint),
        )

    async def record_transport_failure(
        self, *, claim: YouTubePublicationClaim, error: YouTubeError,
    ) -> None:
        if not isinstance(claim, YouTubePublicationClaim) or not isinstance(error, YouTubeError):
            raise ValueError("YouTube transport failure is invalid")
        status = "VERIFY_PENDING" if error.ambiguous or claim.upload_session_ref else "FAILED"
        message = str(error)
        if len(message) > 500 or re.search(
            r"(?i)(token|secret|credential|authorization|cookie)\s*[:=]", message,
        ):
            message = "YouTube transport failed"
        try:
            async with unit_of_work(self._pool) as connection:
                await self._lock_owned(connection, claim)
                await connection.execute(
                    """UPDATE publication_jobs SET status = %s, last_error_code = %s,
                              last_error_message = %s
                       WHERE id = %s AND request_fingerprint = %s
                         AND status NOT IN ('PUBLISHED','FAILED','CANCELLED')""",
                    (status, error.code, message, claim.publication_id, claim.request_fingerprint),
                )
        except (YouTubePublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("YouTube publication storage is unavailable") from exc

    async def record_verification(
        self, *, claim: YouTubePublicationClaim, remote: YouTubeRemoteVideo,
        status: str,
    ) -> YouTubePublicationResult:
        if (not isinstance(claim, YouTubePublicationClaim)
                or not isinstance(remote, YouTubeRemoteVideo)
                or status not in {"PROCESSING", "PUBLISHED", "FAILED"}):
            raise ValueError("YouTube verification update is invalid")
        remote_status = json.dumps({
            "schema_version": 1,
            "video_id": remote.video_id,
            "channel_id": remote.channel_external_id,
            "upload_status": remote.upload_status,
            "processing_status": remote.processing_status,
            "privacy_status": remote.privacy_status.value,
        }, sort_keys=True, separators=(",", ":"))
        try:
            async with unit_of_work(self._pool) as connection:
                await self._lock_owned(connection, claim)
                cursor = await connection.execute(
                    """UPDATE publication_jobs SET status = %s,
                              remote_post_id = %s, remote_url = %s,
                              last_remote_status = %s::jsonb,
                              verification_attempt_count = verification_attempt_count + 1,
                              last_verified_at = now(),
                              published_at = CASE WHEN %s = 'PUBLISHED' THEN now() ELSE NULL END,
                              last_error_code = CASE WHEN %s = 'FAILED' THEN 'REMOTE_TERMINAL' ELSE NULL END,
                              last_error_message = NULL
                       WHERE id = %s AND request_fingerprint = %s
                         AND status IN ('PROCESSING','VERIFY_PENDING')
                       RETURNING id, status, remote_post_id, remote_url""",
                    (status, remote.video_id, remote.canonical_url, remote_status,
                     status, status, claim.publication_id, claim.request_fingerprint),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise YouTubePublicationConflict("YouTube verification state changed")
                return YouTubePublicationResult(row[0], row[1], row[2], row[3])
        except (YouTubePublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("YouTube publication storage is unavailable") from exc

    async def _update_claim(self, claim: YouTubePublicationClaim, query: str, params) -> YouTubePublicationClaim:
        try:
            async with unit_of_work(self._pool) as connection:
                await self._lock_owned(connection, claim)
                cursor = await connection.execute(query, params)
                updated = await cursor.fetchone()
                if updated is None:
                    raise YouTubePublicationConflict("YouTube publication state changed")
                row = await self._find_claim(connection, claim)
                if row is None:
                    raise YouTubePublicationConflict("YouTube publication claim is unavailable")
                return self._claim(row)
        except (YouTubePublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("YouTube publication storage is unavailable") from exc

    @staticmethod
    async def _lock_owned(connection, claim: YouTubePublicationClaim) -> None:
        cursor = await connection.execute(
            """SELECT p.status FROM publication_jobs AS p
               JOIN social_channels AS ch ON ch.id = p.channel_id
               JOIN brands AS b ON b.id = ch.brand_id
               WHERE p.id = %s AND p.request_fingerprint = %s
                 AND p.asset_id = %s AND p.channel_id = %s
                 AND b.id = %s AND b.owner_user_id = %s
               FOR UPDATE OF p""",
            (claim.publication_id, claim.request_fingerprint, claim.asset_id,
             claim.channel_id, claim.brand_id, claim.owner_user_id),
        )
        if await cursor.fetchone() is None:
            raise YouTubePublicationConflict("YouTube publication claim is unavailable")

    @staticmethod
    async def _find_request(connection, *, request_id: UUID, brand_id: UUID, owner_user_id: str):
        cursor = await connection.execute(
            f"""SELECT {_CLAIM_COLUMNS}
                FROM publication_jobs AS p
                JOIN social_channels AS ch ON ch.id = p.channel_id
                JOIN brands AS b ON b.id = ch.brand_id
                JOIN assets AS a ON a.id = p.asset_id
                WHERE p.request_id = %s AND b.id = %s AND b.owner_user_id = %s
                FOR UPDATE OF p""",
            (request_id, brand_id, owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    async def _find_claim(connection, claim: YouTubePublicationClaim):
        cursor = await connection.execute(
            f"""SELECT {_CLAIM_COLUMNS}
                FROM publication_jobs AS p
                JOIN social_channels AS ch ON ch.id = p.channel_id
                JOIN brands AS b ON b.id = ch.brand_id
                JOIN assets AS a ON a.id = p.asset_id
                WHERE p.id = %s AND p.request_fingerprint = %s
                  AND b.id = %s AND b.owner_user_id = %s
                FOR UPDATE OF p""",
            (claim.publication_id, claim.request_fingerprint,
             claim.brand_id, claim.owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    def _eligible(**values) -> bool:
        request = values["request"]
        media = values["media"]
        return bool(
            values["kind"] == "EXPORT_VARIANT"
            and values["retention"] == "ACTIVE"
            and values["storage_uri"] == f"managed://assets/{request.asset_id.hex}/payload"
            and isinstance(values["sha256_hex"], str)
            and re.fullmatch(r"[0-9a-f]{64}", values["sha256_hex"].strip())
            and values["mime_type"] == "video/mp4"
            and type(values["size_bytes"]) is int and values["size_bytes"] > 0
            and isinstance(media, dict)
            and media.get("export_profile_id") == "YOUTUBE_SHORTS_V1"
            and media.get("platform") == "YOUTUBE"
            and media.get("publishing_performed") is False
            and values["profile_id"] == "YOUTUBE_SHORTS_V1"
            and values["render_version"] == request.artifact_version
            and isinstance(values["approval_id"], UUID)
            and values["decision"] == "APPROVE"
            and values["platform"] == "YOUTUBE"
            and _SAFE_REMOTE_ID.fullmatch(values["external_channel_id"] or "")
            and re.fullmatch(r"secretref://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+", values["credentials_ref"] or "")
            and values["permissions"] == "VALID"
            and values["enabled"] is True
        )

    @staticmethod
    def _claim(row) -> YouTubePublicationClaim:
        try:
            (publication_id, request_fingerprint, brand_id, owner_user_id,
             content_id, channel_id, asset_id,
             approval_id, artifact_version, external_channel_id, credentials_ref,
             storage_uri, sha256_hex, size_bytes, mime_type, privacy, status,
             session_ref, upload_id, video_id) = row
            return YouTubePublicationClaim(
                publication_id=publication_id,
                request_fingerprint=request_fingerprint.strip(),
                brand_id=brand_id, owner_user_id=owner_user_id,
                content_id=content_id, channel_id=channel_id, asset_id=asset_id,
                approval_decision_id=approval_id, artifact_version=artifact_version,
                channel_external_id=external_channel_id, credentials_ref=credentials_ref,
                asset_storage_uri=storage_uri, asset_sha256_hex=sha256_hex.strip(),
                asset_size_bytes=size_bytes, asset_mime_type=mime_type,
                privacy_status=YouTubePrivacy(privacy), status=status,
                upload_session_ref=session_ref, remote_upload_id=upload_id,
                remote_video_id=video_id,
            )
        except Exception as exc:
            raise RepositoryUnavailable("stored YouTube publication claim is invalid") from exc
