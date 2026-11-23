"""Owner-scoped persistence for Instagram Reels publication claims."""

from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

from flowx_os.db.content import OwnedContentNotFound, RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.publishing.instagram import (
    InstagramContainer,
    InstagramContainerState,
    InstagramContainerStatus,
    InstagramError,
    InstagramPublicationClaim,
    InstagramPublicationResult,
    InstagramPublishedMedia,
    InstagramPublishRequest,
    InstagramRemoteMedia,
)


class InstagramPublicationConflict(RuntimeError):
    """A request or state transition names different work."""


class InstagramPublicationNotAllowed(RuntimeError):
    """The approved asset/account evidence is not publishable."""


_CLAIM_COLUMNS = """p.id, p.request_fingerprint, b.id, b.owner_user_id,
    p.content_id, p.channel_id, p.asset_id, p.approval_decision_id,
    p.artifact_version, p.channel_external_id_snapshot,
    p.credentials_ref_snapshot, p.destination_fingerprint,
    p.media_source_ref_snapshot, a.storage_uri, a.sha256_hex, a.size_bytes,
    a.mime_type, p.status, p.instagram_phase, p.remote_upload_id,
    p.remote_post_id, p.remote_url, p.verification_attempt_count"""
_SAFE_REMOTE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_SECRET_REF = re.compile(r"^secretref://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$")


class InstagramPublicationRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def claim(self, request: InstagramPublishRequest) -> InstagramPublicationClaim:
        if not isinstance(request, InstagramPublishRequest):
            raise ValueError("Instagram publication request is required")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT c.status FROM content_items AS c
                       JOIN brands AS b ON b.id = c.brand_id
                       WHERE c.id = %s AND b.id = %s AND b.owner_user_id = %s
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
                    if (claim.publication_id != request.publication_id
                            or claim.request_fingerprint != request.fingerprint):
                        raise InstagramPublicationConflict(
                            "Instagram request already identifies different work"
                        )
                    return claim
                if owned[0] != "READY":
                    raise InstagramPublicationNotAllowed("content is not ready for publication")

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
                       JOIN social_channels AS ch ON ch.id = %s AND ch.brand_id = %s
                       WHERE a.id = %s AND a.content_id = %s AND a.scene_id IS NULL
                       ORDER BY rd.created_at DESC LIMIT 1
                       FOR KEY SHARE OF a, rja, rj, rd, ch""",
                    (request.channel_id, request.brand_id, request.asset_id, request.content_id),
                )
                evidence = await cursor.fetchone()
                if evidence is None:
                    raise InstagramPublicationNotAllowed("exact approved Instagram export is unavailable")
                (kind, retention, storage_uri, sha256_hex, mime_type, size_bytes,
                 raw_media, profile_id, render_version, approval_id, decision,
                 platform, external_id, credentials_ref, permissions, enabled) = evidence
                media = json.loads(raw_media) if isinstance(raw_media, str) else raw_media
                if not self._eligible(
                    request=request, kind=kind, retention=retention, storage_uri=storage_uri,
                    sha256_hex=sha256_hex, mime_type=mime_type, size_bytes=size_bytes,
                    media=media, profile_id=profile_id, render_version=render_version,
                    approval_id=approval_id, decision=decision, platform=platform,
                    external_id=external_id, credentials_ref=credentials_ref,
                    permissions=permissions, enabled=enabled,
                ):
                    raise InstagramPublicationNotAllowed(
                        "Instagram publication evidence is not eligible"
                    )
                metadata = json.dumps(request.metadata, sort_keys=True, separators=(",", ":"))
                cursor = await connection.execute(
                    """INSERT INTO publication_jobs
                         (id, publication_contract, request_id, request_fingerprint,
                          content_id, channel_id, asset_id, approval_decision_id,
                          artifact_version, channel_external_id_snapshot,
                          credentials_ref_snapshot, destination_fingerprint,
                          media_source_ref_snapshot, asset_sha256_hex, asset_size_bytes,
                          intended_privacy_status, platform_metadata, status, instagram_phase)
                       VALUES (%s, 'INSTAGRAM_REELS_V1', %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s, 'public', %s::jsonb,
                               'DRAFT', 'CLAIMED')
                       ON CONFLICT (request_id) WHERE request_id IS NOT NULL DO NOTHING
                       RETURNING id""",
                    (
                        request.publication_id, request.request_id, request.fingerprint,
                        request.content_id, request.channel_id, request.asset_id, approval_id,
                        request.artifact_version, external_id, credentials_ref,
                        self._destination_fingerprint(external_id, credentials_ref),
                        request.media_source_ref, sha256_hex, size_bytes, metadata,
                    ),
                )
                await cursor.fetchone()
                row = await self._find_request(
                    connection, request_id=request.request_id,
                    brand_id=request.brand_id, owner_user_id=request.owner_user_id,
                )
                if row is None:
                    raise InstagramPublicationConflict("Instagram claim was not created")
                claim = self._claim(row)
                if (claim.publication_id != request.publication_id
                        or claim.request_fingerprint != request.fingerprint):
                    raise InstagramPublicationConflict("Instagram claim conflicts with stored work")
                return claim
        except (OwnedContentNotFound, InstagramPublicationConflict,
                InstagramPublicationNotAllowed, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Instagram publication storage is unavailable") from exc

    async def assert_network_ready(self, claim: InstagramPublicationClaim) -> None:
        if not isinstance(claim, InstagramPublicationClaim):
            raise ValueError("Instagram publication claim is required")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT 1 FROM publication_jobs AS p
                       JOIN social_channels AS ch ON ch.id = p.channel_id
                       JOIN brands AS b ON b.id = ch.brand_id
                       JOIN publication_delivery_reservations AS dr
                         ON dr.publication_id = p.id
                       JOIN publication_delivery_approvals AS da
                         ON da.id = dr.approval_id AND da.publication_id = p.id
                       WHERE p.id = %s AND p.request_fingerprint = %s
                         AND p.publication_contract = 'INSTAGRAM_REELS_V1'
                         AND b.id = %s AND b.owner_user_id = %s
                         AND ch.enabled = true AND ch.permissions_status = 'VALID'
                         AND ch.platform = 'INSTAGRAM'
                         AND ch.external_channel_id = p.channel_external_id_snapshot
                         AND ch.credentials_ref = p.credentials_ref_snapshot
                         AND p.channel_external_id_snapshot = %s
                         AND p.credentials_ref_snapshot = %s
                         AND p.destination_fingerprint = %s
                         AND dr.owner_user_id = b.owner_user_id
                         AND dr.content_id = p.content_id AND dr.channel_id = p.channel_id
                         AND dr.asset_id = p.asset_id AND dr.artifact_version = p.artifact_version
                         AND dr.destination_fingerprint = p.destination_fingerprint
                         AND dr.state IN ('SCHEDULED','DISPATCH_RESERVED')
                         AND dr.scheduled_at_utc <= now()
                         AND da.decision = 'APPROVE' AND da.valid_until > now()
                         AND NOT EXISTS (
                           SELECT 1 FROM publication_reconciliations AS pr
                           WHERE pr.publication_id = p.id AND pr.requires_human_review = true
                         )
                       FOR KEY SHARE OF p, ch""",
                    (claim.publication_id, claim.request_fingerprint, claim.brand_id,
                     claim.owner_user_id, claim.professional_account_id,
                     claim.credentials_ref, claim.destination_fingerprint),
                )
                if await cursor.fetchone() is None:
                    raise InstagramPublicationNotAllowed(
                        "Instagram account authorization changed"
                    )
        except (InstagramPublicationNotAllowed, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Instagram publication storage is unavailable") from exc

    async def reserve_container(
        self, claim: InstagramPublicationClaim,
    ) -> InstagramPublicationClaim:
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = 'UPLOAD_STARTED',
                      instagram_phase = 'CONTAINER_RESERVED',
                      last_error_code = NULL, last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status = 'DRAFT' AND instagram_phase = 'CLAIMED'
               RETURNING id""",
            (claim.publication_id, claim.request_fingerprint),
        )

    async def record_container(
        self, *, claim: InstagramPublicationClaim, container: InstagramContainer,
    ) -> InstagramPublicationClaim:
        if not isinstance(container, InstagramContainer):
            raise ValueError("Instagram container update is invalid")
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = 'PROCESSING',
                      instagram_phase = 'CONTAINER_CREATED', remote_upload_id = %s,
                      last_error_code = NULL, last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status = 'UPLOAD_STARTED' AND instagram_phase = 'CONTAINER_RESERVED'
                 AND remote_upload_id IS NULL AND remote_post_id IS NULL
               RETURNING id""",
            (container.container_id, claim.publication_id, claim.request_fingerprint),
        )

    async def record_container_status(
        self, *, claim: InstagramPublicationClaim, remote: InstagramContainerStatus,
    ) -> InstagramPublicationClaim:
        if not isinstance(remote, InstagramContainerStatus):
            raise ValueError("Instagram container status is invalid")
        if remote.container_id != claim.remote_container_id:
            raise InstagramPublicationConflict("Instagram container identity changed")
        if claim.remote_media_id is not None:
            # Preserve accepted media identity while persisting every later
            # container observation so bounded reconciliation still advances.
            status, phase = "VERIFY_PENDING", "MEDIA_RECORDED"
        else:
            status = "PROCESSING"
            phase = {
                InstagramContainerState.IN_PROGRESS: "CONTAINER_PROCESSING",
                InstagramContainerState.FINISHED: "CONTAINER_READY",
                InstagramContainerState.PUBLISHED: "MEDIA_ID_UNKNOWN",
                InstagramContainerState.ERROR: "FAILED",
                InstagramContainerState.EXPIRED: "FAILED",
            }[remote.state]
            if remote.state == InstagramContainerState.PUBLISHED:
                status = "VERIFY_PENDING"
            elif remote.state in {InstagramContainerState.ERROR, InstagramContainerState.EXPIRED}:
                status = "FAILED"
        evidence = json.dumps({
            "schema_version": 1,
            "container_id": remote.container_id,
            "container_status": remote.state.value,
        }, sort_keys=True, separators=(",", ":"))
        error_code = (
            f"CONTAINER_{remote.state.value}"
            if remote.state in {InstagramContainerState.ERROR, InstagramContainerState.EXPIRED}
            else None
        )
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = %s, instagram_phase = %s,
                      last_remote_status = %s::jsonb,
                      verification_attempt_count = verification_attempt_count + 1,
                      last_verified_at = now(), last_error_code = %s,
                      last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status IN ('PROCESSING','VERIFY_PENDING')
                 AND instagram_phase IN ('CONTAINER_CREATED','CONTAINER_PROCESSING',
                     'CONTAINER_READY','MEDIA_RECORDED','MEDIA_ID_UNKNOWN')
               RETURNING id""",
            (status, phase, evidence, error_code,
             claim.publication_id, claim.request_fingerprint),
        )

    async def reserve_publish(
        self, claim: InstagramPublicationClaim,
    ) -> InstagramPublicationClaim:
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = 'PUBLISH_REQUESTED',
                      instagram_phase = 'PUBLISH_RESERVED',
                      last_error_code = NULL, last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status = 'PROCESSING' AND instagram_phase = 'CONTAINER_READY'
                 AND remote_upload_id IS NOT NULL AND remote_post_id IS NULL
               RETURNING id""",
            (claim.publication_id, claim.request_fingerprint),
        )

    async def record_media(
        self, *, claim: InstagramPublicationClaim, media: InstagramPublishedMedia,
    ) -> InstagramPublicationClaim:
        if not isinstance(media, InstagramPublishedMedia):
            raise ValueError("Instagram media update is invalid")
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = 'VERIFY_PENDING',
                      instagram_phase = 'MEDIA_RECORDED', remote_post_id = %s,
                      last_error_code = NULL, last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status = 'PUBLISH_REQUESTED' AND instagram_phase = 'PUBLISH_RESERVED'
                 AND remote_post_id IS NULL
               RETURNING id""",
            (media.media_id, claim.publication_id, claim.request_fingerprint),
        )

    async def record_transport_failure(
        self, *, claim: InstagramPublicationClaim, error: InstagramError,
    ) -> None:
        if not isinstance(claim, InstagramPublicationClaim) or not isinstance(error, InstagramError):
            raise ValueError("Instagram transport failure is invalid")
        message = str(error)
        if len(message) > 500 or re.search(
            r"(?i)(token|secret|credential|authorization|cookie)\s*[:=]", message,
        ):
            message = "Instagram transport failed"
        try:
            async with unit_of_work(self._pool) as connection:
                await self._lock_owned(connection, claim)
                await connection.execute(
                    """UPDATE publication_jobs SET last_error_code = %s,
                              last_error_message = %s
                       WHERE id = %s AND request_fingerprint = %s
                         AND status NOT IN ('PUBLISHED','FAILED','CANCELLED')""",
                    (error.code, message, claim.publication_id, claim.request_fingerprint),
                )
        except (InstagramPublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Instagram publication storage is unavailable") from exc

    async def record_verification(
        self, *, claim: InstagramPublicationClaim, container: InstagramContainerStatus,
        media: InstagramRemoteMedia,
    ) -> InstagramPublicationResult:
        if (not isinstance(container, InstagramContainerStatus)
                or not isinstance(media, InstagramRemoteMedia)
                or container.state != InstagramContainerState.PUBLISHED
                or container.container_id != claim.remote_container_id
                or media.media_id != claim.remote_media_id
                or media.owner_id != claim.professional_account_id):
            raise ValueError("Instagram verification update is invalid")
        evidence = json.dumps({
            "schema_version": 1,
            "container_id": container.container_id,
            "container_status": container.state.value,
            "media_id": media.media_id,
            "owner_id": media.owner_id,
            "media_type": media.media_type,
            "permalink": media.permalink,
        }, sort_keys=True, separators=(",", ":"))
        try:
            async with unit_of_work(self._pool) as connection:
                await self._lock_owned(connection, claim)
                cursor = await connection.execute(
                    """UPDATE publication_jobs SET status = 'PUBLISHED',
                              instagram_phase = 'VERIFIED', remote_url = %s,
                              last_remote_status = %s::jsonb,
                              verification_attempt_count = verification_attempt_count + 1,
                              last_verified_at = now(), published_at = now(),
                              last_error_code = NULL, last_error_message = NULL
                       WHERE id = %s AND request_fingerprint = %s
                         AND status = 'VERIFY_PENDING'
                         AND instagram_phase = 'MEDIA_RECORDED'
                         AND remote_upload_id = %s AND remote_post_id = %s
                       RETURNING id, status, remote_post_id, remote_url""",
                    (media.permalink, evidence, claim.publication_id,
                     claim.request_fingerprint, container.container_id, media.media_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise InstagramPublicationConflict("Instagram verification state changed")
                return InstagramPublicationResult(row[0], row[1], row[2], row[3])
        except (InstagramPublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Instagram publication storage is unavailable") from exc

    async def recover_container(
        self, *, request: InstagramPublishRequest, container: InstagramContainer,
    ) -> InstagramPublicationClaim:
        return await self._recover(
            request=request, expected_phases={"CONTAINER_RESERVED"},
            query="""UPDATE publication_jobs SET status = 'PROCESSING',
                            instagram_phase = 'CONTAINER_CREATED', remote_upload_id = %s,
                            last_error_code = NULL, last_error_message = NULL
                     WHERE id = %s AND request_fingerprint = %s
                       AND status = 'UPLOAD_STARTED' AND instagram_phase = 'CONTAINER_RESERVED'
                       AND remote_upload_id IS NULL AND remote_post_id IS NULL
                     RETURNING id""",
            params_prefix=(container.container_id,),
        )

    async def recover_media(
        self, *, request: InstagramPublishRequest, media: InstagramPublishedMedia,
    ) -> InstagramPublicationClaim:
        return await self._recover(
            request=request, expected_phases={"PUBLISH_RESERVED", "MEDIA_ID_UNKNOWN"},
            query="""UPDATE publication_jobs SET status = 'VERIFY_PENDING',
                            instagram_phase = 'MEDIA_RECORDED', remote_post_id = %s,
                            last_error_code = NULL, last_error_message = NULL
                     WHERE id = %s AND request_fingerprint = %s
                       AND status IN ('PUBLISH_REQUESTED','VERIFY_PENDING')
                       AND instagram_phase IN ('PUBLISH_RESERVED','MEDIA_ID_UNKNOWN')
                       AND remote_upload_id IS NOT NULL AND remote_post_id IS NULL
                     RETURNING id""",
            params_prefix=(media.media_id,),
        )

    async def _recover(
        self, *, request: InstagramPublishRequest, expected_phases: set[str],
        query: str, params_prefix: tuple[object, ...],
    ) -> InstagramPublicationClaim:
        if not isinstance(request, InstagramPublishRequest):
            raise ValueError("Instagram recovery request is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                row = await self._find_request(
                    connection, request_id=request.request_id,
                    brand_id=request.brand_id, owner_user_id=request.owner_user_id,
                )
                if row is None:
                    raise InstagramPublicationConflict("Instagram claim is unavailable")
                claim = self._claim(row)
                if (claim.publication_id != request.publication_id
                        or claim.request_fingerprint != request.fingerprint
                        or claim.phase not in expected_phases):
                    raise InstagramPublicationConflict("Instagram publication is not recoverable")
                cursor = await connection.execute(
                    query, params_prefix + (claim.publication_id, claim.request_fingerprint),
                )
                if await cursor.fetchone() is None:
                    raise InstagramPublicationConflict("Instagram recovery state changed")
                updated = await self._find_claim(connection, claim)
                if updated is None:
                    raise InstagramPublicationConflict("Instagram claim is unavailable")
                return self._claim(updated)
        except (InstagramPublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Instagram publication storage is unavailable") from exc

    async def cancel_unknown(
        self, *, request: InstagramPublishRequest, reason: str,
    ) -> InstagramPublicationResult:
        normalized = reason.strip() if isinstance(reason, str) else ""
        if (not isinstance(request, InstagramPublishRequest) or not normalized
                or len(normalized) > 500 or any(ord(char) < 32 for char in normalized)
                or re.search(r"(?i)(token|secret|credential|authorization|cookie)\s*[:=]", normalized)):
            raise ValueError("Instagram cancellation reason is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                row = await self._find_request(
                    connection, request_id=request.request_id,
                    brand_id=request.brand_id, owner_user_id=request.owner_user_id,
                )
                if row is None:
                    raise InstagramPublicationConflict("Instagram claim is unavailable")
                claim = self._claim(row)
                if (claim.publication_id != request.publication_id
                        or claim.request_fingerprint != request.fingerprint
                        or claim.phase not in {
                            "CONTAINER_RESERVED", "PUBLISH_RESERVED", "MEDIA_ID_UNKNOWN",
                        } or claim.remote_media_id is not None):
                    raise InstagramPublicationConflict("Instagram publication cannot be cancelled")
                cursor = await connection.execute(
                    """UPDATE publication_jobs SET status = 'CANCELLED',
                              instagram_phase = 'CANCELLED',
                              last_error_code = 'OPERATOR_CANCELLED',
                              last_error_message = %s
                       WHERE id = %s AND request_fingerprint = %s
                         AND instagram_phase IN ('CONTAINER_RESERVED','PUBLISH_RESERVED','MEDIA_ID_UNKNOWN')
                         AND remote_post_id IS NULL
                       RETURNING id, status, remote_post_id, remote_url""",
                    (normalized, claim.publication_id, claim.request_fingerprint),
                )
                result = await cursor.fetchone()
                if result is None:
                    raise InstagramPublicationConflict("Instagram cancellation state changed")
                return InstagramPublicationResult(result[0], result[1], result[2], result[3])
        except (InstagramPublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Instagram publication storage is unavailable") from exc

    async def _update_claim(self, claim, query, params) -> InstagramPublicationClaim:
        if not isinstance(claim, InstagramPublicationClaim):
            raise ValueError("Instagram publication claim is required")
        try:
            async with unit_of_work(self._pool) as connection:
                await self._lock_owned(connection, claim)
                cursor = await connection.execute(query, params)
                if await cursor.fetchone() is None:
                    raise InstagramPublicationConflict("Instagram publication state changed")
                row = await self._find_claim(connection, claim)
                if row is None:
                    raise InstagramPublicationConflict("Instagram claim is unavailable")
                return self._claim(row)
        except (InstagramPublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Instagram publication storage is unavailable") from exc

    @staticmethod
    async def _lock_owned(connection, claim: InstagramPublicationClaim) -> None:
        cursor = await connection.execute(
            """SELECT p.status FROM publication_jobs AS p
               JOIN social_channels AS ch ON ch.id = p.channel_id
               JOIN brands AS b ON b.id = ch.brand_id
               WHERE p.id = %s AND p.request_fingerprint = %s
                 AND p.publication_contract = 'INSTAGRAM_REELS_V1'
                 AND p.asset_id = %s AND p.channel_id = %s
                 AND b.id = %s AND b.owner_user_id = %s
               FOR UPDATE OF p""",
            (claim.publication_id, claim.request_fingerprint, claim.asset_id,
             claim.channel_id, claim.brand_id, claim.owner_user_id),
        )
        if await cursor.fetchone() is None:
            raise InstagramPublicationConflict("Instagram claim is unavailable")

    @staticmethod
    async def _find_request(connection, *, request_id: UUID, brand_id: UUID, owner_user_id: str):
        cursor = await connection.execute(
            f"""SELECT {_CLAIM_COLUMNS} FROM publication_jobs AS p
                JOIN social_channels AS ch ON ch.id = p.channel_id
                JOIN brands AS b ON b.id = ch.brand_id
                JOIN assets AS a ON a.id = p.asset_id
                WHERE p.request_id = %s AND p.publication_contract = 'INSTAGRAM_REELS_V1'
                  AND b.id = %s AND b.owner_user_id = %s FOR UPDATE OF p""",
            (request_id, brand_id, owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    async def _find_claim(connection, claim: InstagramPublicationClaim):
        cursor = await connection.execute(
            f"""SELECT {_CLAIM_COLUMNS} FROM publication_jobs AS p
                JOIN social_channels AS ch ON ch.id = p.channel_id
                JOIN brands AS b ON b.id = ch.brand_id
                JOIN assets AS a ON a.id = p.asset_id
                WHERE p.id = %s AND p.request_fingerprint = %s
                  AND p.publication_contract = 'INSTAGRAM_REELS_V1'
                  AND b.id = %s AND b.owner_user_id = %s FOR UPDATE OF p""",
            (claim.publication_id, claim.request_fingerprint,
             claim.brand_id, claim.owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    def _destination_fingerprint(external_id: str, credentials_ref: str) -> str:
        return hashlib.sha256(f"{external_id}|{credentials_ref}".encode("utf-8")).hexdigest()

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
            and type(values["size_bytes"]) is int and 0 < values["size_bytes"] <= 300_000_000
            and isinstance(media, dict)
            and media.get("export_profile_id") == "INSTAGRAM_REELS_V1"
            and media.get("platform") == "INSTAGRAM"
            and media.get("publishing_performed") is False
            and values["profile_id"] == "INSTAGRAM_REELS_V1"
            and values["render_version"] == request.artifact_version
            and isinstance(values["approval_id"], UUID)
            and values["decision"] == "APPROVE"
            and values["platform"] == "INSTAGRAM"
            and _SAFE_REMOTE_ID.fullmatch(values["external_id"] or "")
            and _SECRET_REF.fullmatch(values["credentials_ref"] or "")
            and values["permissions"] == "VALID" and values["enabled"] is True
        )

    @staticmethod
    def _claim(row) -> InstagramPublicationClaim:
        try:
            (publication_id, fingerprint, brand_id, owner_user_id, content_id,
             channel_id, asset_id, approval_id, artifact_version, external_id,
             credentials_ref, destination_fingerprint, media_source_ref, storage_uri,
             sha256_hex, size_bytes, mime_type, status, phase, container_id,
             media_id, remote_url, verification_attempt_count) = row
            return InstagramPublicationClaim(
                publication_id=publication_id, request_fingerprint=fingerprint.strip(),
                brand_id=brand_id, owner_user_id=owner_user_id, content_id=content_id,
                channel_id=channel_id, asset_id=asset_id,
                approval_decision_id=approval_id, artifact_version=artifact_version,
                professional_account_id=external_id, credentials_ref=credentials_ref,
                destination_fingerprint=destination_fingerprint.strip(),
                media_source_ref=media_source_ref, asset_storage_uri=storage_uri,
                asset_sha256_hex=sha256_hex.strip(), asset_size_bytes=size_bytes,
                asset_mime_type=mime_type, status=status, phase=phase,
                verification_attempt_count=verification_attempt_count,
                remote_container_id=container_id, remote_media_id=media_id,
                remote_url=remote_url,
            )
        except Exception as exc:
            raise RepositoryUnavailable("stored Instagram publication claim is invalid") from exc
