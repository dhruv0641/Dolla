"""Owner-scoped persistence for Facebook Page Reel publication claims."""

from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

from flowx_os.db.content import OwnedContentNotFound, RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work
from flowx_os.publishing.facebook import (
    FacebookError,
    FacebookPublicationClaim,
    FacebookPublicationResult,
    FacebookPublishReceipt,
    FacebookPublishRequest,
    FacebookRemoteReel,
    FacebookUploadReceipt,
    FacebookUploadSession,
    FacebookVideoState,
    FacebookVideoStatus,
)


class FacebookPublicationConflict(RuntimeError):
    """A request or transition identifies different work."""


class FacebookPublicationNotAllowed(RuntimeError):
    """The approved artifact or current Page evidence is not publishable."""


_CLAIM_COLUMNS = """p.id, p.request_fingerprint, b.id, b.owner_user_id,
    p.content_id, p.channel_id, p.asset_id, p.approval_decision_id,
    p.artifact_version, p.channel_external_id_snapshot,
    p.credentials_ref_snapshot, p.destination_fingerprint,
    a.storage_uri, a.sha256_hex, a.size_bytes, a.mime_type,
    p.status, p.facebook_phase, p.remote_upload_id, p.upload_session_ref,
    p.remote_post_id, p.remote_url, p.verification_attempt_count"""
_SAFE_REMOTE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_SAFE_PAGE_ID = re.compile(r"^[0-9]{1,50}$")
_SECRET_REF = re.compile(r"^secretref://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$")


class FacebookPublicationRepository:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def claim(self, request: FacebookPublishRequest) -> FacebookPublicationClaim:
        if not isinstance(request, FacebookPublishRequest):
            raise ValueError("Facebook publication request is required")
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
                        raise FacebookPublicationConflict(
                            "Facebook request already identifies different work"
                        )
                    return claim
                if owned[0] != "READY":
                    raise FacebookPublicationNotAllowed("content is not ready for publication")

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
                    raise FacebookPublicationNotAllowed("exact approved Facebook export is unavailable")
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
                    raise FacebookPublicationNotAllowed("Facebook publication evidence is not eligible")
                metadata = json.dumps(request.metadata, sort_keys=True, separators=(",", ":"))
                cursor = await connection.execute(
                    """INSERT INTO publication_jobs
                         (id, publication_contract, request_id, request_fingerprint,
                          content_id, channel_id, asset_id, approval_decision_id,
                          artifact_version, channel_external_id_snapshot,
                          credentials_ref_snapshot, destination_fingerprint,
                          asset_sha256_hex, asset_size_bytes, intended_privacy_status,
                          platform_metadata, status, facebook_phase)
                       VALUES (%s, 'FACEBOOK_REELS_V1', %s, %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, 'public', %s::jsonb,
                               'DRAFT', 'CLAIMED')
                       ON CONFLICT (request_id) WHERE request_id IS NOT NULL DO NOTHING
                       RETURNING id""",
                    (request.publication_id, request.request_id, request.fingerprint,
                     request.content_id, request.channel_id, request.asset_id, approval_id,
                     request.artifact_version, external_id, credentials_ref,
                     self._destination_fingerprint(external_id, credentials_ref),
                     sha256_hex, size_bytes, metadata),
                )
                await cursor.fetchone()
                row = await self._find_request(
                    connection, request_id=request.request_id,
                    brand_id=request.brand_id, owner_user_id=request.owner_user_id,
                )
                if row is None:
                    raise FacebookPublicationConflict("Facebook claim was not created")
                claim = self._claim(row)
                if (claim.publication_id != request.publication_id
                        or claim.request_fingerprint != request.fingerprint):
                    raise FacebookPublicationConflict("Facebook claim conflicts with stored work")
                return claim
        except (OwnedContentNotFound, FacebookPublicationConflict,
                FacebookPublicationNotAllowed, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Facebook publication storage is unavailable") from exc

    async def assert_network_ready(self, claim: FacebookPublicationClaim) -> None:
        if not isinstance(claim, FacebookPublicationClaim):
            raise ValueError("Facebook publication claim is required")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """SELECT 1 FROM publication_jobs AS p
                       JOIN social_channels AS ch ON ch.id = p.channel_id
                       JOIN brands AS b ON b.id = ch.brand_id
                       WHERE p.id = %s AND p.request_fingerprint = %s
                         AND p.publication_contract = 'FACEBOOK_REELS_V1'
                         AND b.id = %s AND b.owner_user_id = %s
                         AND ch.enabled = true AND ch.permissions_status = 'VALID'
                         AND ch.platform = 'FACEBOOK'
                         AND ch.external_channel_id = p.channel_external_id_snapshot
                         AND ch.credentials_ref = p.credentials_ref_snapshot
                         AND p.channel_external_id_snapshot = %s
                         AND p.credentials_ref_snapshot = %s
                         AND p.destination_fingerprint = %s
                       FOR KEY SHARE OF p, ch""",
                    (claim.publication_id, claim.request_fingerprint, claim.brand_id,
                     claim.owner_user_id, claim.page_id, claim.credentials_ref,
                     claim.destination_fingerprint),
                )
                if await cursor.fetchone() is None:
                    raise FacebookPublicationNotAllowed("Facebook Page authorization changed")
        except (FacebookPublicationNotAllowed, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Facebook publication storage is unavailable") from exc

    async def reserve_start(self, claim: FacebookPublicationClaim) -> FacebookPublicationClaim:
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = 'UPLOAD_STARTED',
                      facebook_phase = 'START_RESERVED', last_error_code = NULL,
                      last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status = 'DRAFT' AND facebook_phase = 'CLAIMED'
               RETURNING id""",
            (claim.publication_id, claim.request_fingerprint),
        )

    async def record_session(
        self, *, claim: FacebookPublicationClaim, session: FacebookUploadSession,
    ) -> FacebookPublicationClaim:
        if not isinstance(session, FacebookUploadSession):
            raise ValueError("Facebook upload session is invalid")
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = 'UPLOAD_STARTED',
                      facebook_phase = 'SESSION_CREATED', remote_upload_id = %s,
                      upload_session_ref = %s, last_error_code = NULL,
                      last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status = 'UPLOAD_STARTED' AND facebook_phase = 'START_RESERVED'
                 AND remote_upload_id IS NULL AND upload_session_ref IS NULL
               RETURNING id""",
            (session.video_id, session.upload_session_ref,
             claim.publication_id, claim.request_fingerprint),
        )

    async def reserve_upload(self, claim: FacebookPublicationClaim) -> FacebookPublicationClaim:
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = 'PROCESSING',
                      facebook_phase = 'UPLOAD_RESERVED', last_error_code = NULL,
                      last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status = 'UPLOAD_STARTED' AND facebook_phase = 'SESSION_CREATED'
                 AND remote_upload_id IS NOT NULL AND upload_session_ref IS NOT NULL
               RETURNING id""",
            (claim.publication_id, claim.request_fingerprint),
        )

    async def record_upload(
        self, *, claim: FacebookPublicationClaim, receipt: FacebookUploadReceipt,
    ) -> FacebookPublicationClaim:
        if (not isinstance(receipt, FacebookUploadReceipt)
                or receipt.video_id != claim.remote_video_id):
            raise ValueError("Facebook upload receipt is invalid")
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = 'PROCESSING',
                      facebook_phase = 'UPLOAD_ACCEPTED', last_error_code = NULL,
                      last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status = 'PROCESSING' AND facebook_phase = 'UPLOAD_RESERVED'
                 AND remote_upload_id = %s
               RETURNING id""",
            (claim.publication_id, claim.request_fingerprint, receipt.video_id),
        )

    async def record_video_status(
        self, *, claim: FacebookPublicationClaim, remote: FacebookVideoStatus,
    ) -> FacebookPublicationClaim:
        if (not isinstance(remote, FacebookVideoStatus)
                or remote.video_id != claim.remote_video_id
                or remote.page_id != claim.page_id
                or remote.source_file_size != claim.asset_size_bytes):
            raise ValueError("Facebook video status is invalid")
        if remote.state in {FacebookVideoState.ERROR, FacebookVideoState.EXPIRED,
                            FacebookVideoState.UPLOAD_FAILED}:
            status, phase = "FAILED", "FAILED"
        elif claim.phase == "PUBLISH_ACCEPTED":
            status, phase = "VERIFY_PENDING", "PUBLISH_ACCEPTED"
        elif remote.state == FacebookVideoState.READY:
            status, phase = "PROCESSING", "VIDEO_READY"
        else:
            status, phase = "PROCESSING", "VIDEO_PROCESSING"
        error_code = (
            f"VIDEO_{remote.state.value.upper()}"
            if phase == "FAILED" else None
        )
        evidence = self._status_evidence(remote)
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = %s, facebook_phase = %s,
                      uploaded_bytes = %s, last_remote_status = %s::jsonb,
                      verification_attempt_count = verification_attempt_count + 1,
                      last_verified_at = now(), last_error_code = %s,
                      last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status IN ('PROCESSING','VERIFY_PENDING')
                 AND facebook_phase IN ('UPLOAD_ACCEPTED','VIDEO_PROCESSING',
                     'VIDEO_READY','PUBLISH_ACCEPTED')
               RETURNING id""",
            (status, phase, remote.bytes_transferred, evidence, error_code,
             claim.publication_id, claim.request_fingerprint),
        )

    async def reserve_publish(self, claim: FacebookPublicationClaim) -> FacebookPublicationClaim:
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = 'PUBLISH_REQUESTED',
                      facebook_phase = 'PUBLISH_RESERVED', last_error_code = NULL,
                      last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status = 'PROCESSING' AND facebook_phase = 'VIDEO_READY'
                 AND remote_upload_id IS NOT NULL AND uploaded_bytes = asset_size_bytes
               RETURNING id""",
            (claim.publication_id, claim.request_fingerprint),
        )

    async def record_publish(
        self, *, claim: FacebookPublicationClaim, receipt: FacebookPublishReceipt,
    ) -> FacebookPublicationClaim:
        if (not isinstance(receipt, FacebookPublishReceipt)
                or receipt.video_id != claim.remote_video_id):
            raise ValueError("Facebook publish receipt is invalid")
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = 'VERIFY_PENDING',
                      facebook_phase = 'PUBLISH_ACCEPTED', remote_post_id = %s,
                      last_error_code = NULL, last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status = 'PUBLISH_REQUESTED' AND facebook_phase = 'PUBLISH_RESERVED'
                 AND remote_upload_id = %s AND remote_post_id IS NULL
               RETURNING id""",
            (receipt.post_id, claim.publication_id,
             claim.request_fingerprint, receipt.video_id),
        )

    async def record_transport_failure(
        self, *, claim: FacebookPublicationClaim, error: FacebookError,
    ) -> None:
        if not isinstance(claim, FacebookPublicationClaim) or not isinstance(error, FacebookError):
            raise ValueError("Facebook transport failure is invalid")
        message = str(error)
        if len(message) > 500 or re.search(
            r"(?i)(token|secret|credential|authorization|cookie)\s*[:=]", message,
        ):
            message = "Facebook transport failed"
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
        except (FacebookPublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Facebook publication storage is unavailable") from exc

    async def record_verification(
        self, *, claim: FacebookPublicationClaim, status: FacebookVideoStatus,
        remote: FacebookRemoteReel,
    ) -> FacebookPublicationResult:
        if (not isinstance(status, FacebookVideoStatus)
                or not isinstance(remote, FacebookRemoteReel)
                or status.state != FacebookVideoState.PUBLISHED
                or status.video_id != claim.remote_video_id
                or status.page_id != claim.page_id
                or status.bytes_transferred != claim.asset_size_bytes
                or remote.video_id != claim.remote_video_id
                or remote.page_id != claim.page_id
                or (claim.remote_post_id is not None
                    and remote.post_id != claim.remote_post_id)):
            raise ValueError("Facebook verification evidence is invalid")
        evidence = json.dumps({
            **json.loads(self._status_evidence(status)),
            "post_id": remote.post_id,
            "permalink": remote.permalink,
            "published": remote.published,
        }, sort_keys=True, separators=(",", ":"))
        try:
            async with unit_of_work(self._pool) as connection:
                await self._lock_owned(connection, claim)
                cursor = await connection.execute(
                    """UPDATE publication_jobs SET status = 'PUBLISHED',
                              facebook_phase = 'VERIFIED', remote_post_id = %s,
                              remote_url = %s, last_remote_status = %s::jsonb,
                              verification_attempt_count = verification_attempt_count + 1,
                              last_verified_at = now(), published_at = now(),
                              last_error_code = NULL, last_error_message = NULL
                       WHERE id = %s AND request_fingerprint = %s
                         AND status = 'VERIFY_PENDING'
                         AND facebook_phase = 'PUBLISH_ACCEPTED'
                         AND remote_upload_id = %s
                         AND (remote_post_id IS NULL OR remote_post_id = %s)
                       RETURNING id, status, remote_upload_id, remote_url""",
                    (remote.post_id, remote.permalink, evidence,
                     claim.publication_id, claim.request_fingerprint,
                     remote.video_id, remote.post_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise FacebookPublicationConflict("Facebook verification state changed")
                return FacebookPublicationResult(row[0], row[1], row[2], row[3])
        except (FacebookPublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Facebook publication storage is unavailable") from exc

    async def recover_session(
        self, *, request: FacebookPublishRequest, session: FacebookUploadSession,
    ) -> FacebookPublicationClaim:
        if not isinstance(session, FacebookUploadSession):
            raise ValueError("Facebook session recovery is invalid")
        return await self._recover(
            request=request, expected_phase="START_RESERVED",
            query="""UPDATE publication_jobs SET status = 'UPLOAD_STARTED',
                            facebook_phase = 'SESSION_CREATED', remote_upload_id = %s,
                            upload_session_ref = %s, last_error_code = NULL,
                            last_error_message = NULL
                     WHERE id = %s AND request_fingerprint = %s
                       AND status = 'UPLOAD_STARTED' AND facebook_phase = 'START_RESERVED'
                       AND remote_upload_id IS NULL AND upload_session_ref IS NULL
                     RETURNING id""",
            params=(session.video_id, session.upload_session_ref),
        )

    async def recover_upload(
        self, *, request: FacebookPublishRequest, status: FacebookVideoStatus,
    ) -> FacebookPublicationClaim:
        if (not isinstance(status, FacebookVideoStatus)
                or status.uploading_status != "completed"
                or status.bytes_transferred != status.source_file_size):
            raise ValueError("Facebook upload recovery evidence is invalid")
        claim = await self._recover_claim(request, "UPLOAD_RESERVED")
        if (status.video_id != claim.remote_video_id or status.page_id != claim.page_id
                or status.source_file_size != claim.asset_size_bytes):
            raise FacebookPublicationConflict("Facebook upload recovery identity changed")
        return await self._update_claim(
            claim,
            """UPDATE publication_jobs SET status = 'PROCESSING',
                      facebook_phase = 'UPLOAD_ACCEPTED', uploaded_bytes = %s,
                      last_remote_status = %s::jsonb, last_verified_at = now(),
                      verification_attempt_count = verification_attempt_count + 1,
                      last_error_code = NULL, last_error_message = NULL
               WHERE id = %s AND request_fingerprint = %s
                 AND status = 'PROCESSING' AND facebook_phase = 'UPLOAD_RESERVED'
                 AND remote_upload_id = %s
               RETURNING id""",
            (status.bytes_transferred, self._status_evidence(status),
             claim.publication_id, claim.request_fingerprint, status.video_id),
        )

    async def recover_publish(
        self, *, request: FacebookPublishRequest, receipt: FacebookPublishReceipt,
    ) -> FacebookPublicationClaim:
        if not isinstance(receipt, FacebookPublishReceipt):
            raise ValueError("Facebook publish recovery is invalid")
        return await self._recover(
            request=request, expected_phase="PUBLISH_RESERVED",
            query="""UPDATE publication_jobs SET status = 'VERIFY_PENDING',
                            facebook_phase = 'PUBLISH_ACCEPTED', remote_post_id = %s,
                            last_error_code = NULL, last_error_message = NULL
                     WHERE id = %s AND request_fingerprint = %s
                       AND status = 'PUBLISH_REQUESTED' AND facebook_phase = 'PUBLISH_RESERVED'
                       AND remote_upload_id = %s AND remote_post_id IS NULL
                     RETURNING id""",
            params=(receipt.post_id, receipt.video_id),
        )

    async def _recover(
        self, *, request: FacebookPublishRequest, expected_phase: str,
        query: str, params: tuple[object, ...],
    ) -> FacebookPublicationClaim:
        claim = await self._recover_claim(request, expected_phase)
        try:
            async with unit_of_work(self._pool) as connection:
                await self._lock_owned(connection, claim)
                cursor = await connection.execute(
                    query, params + (claim.publication_id, claim.request_fingerprint)
                    if expected_phase == "START_RESERVED"
                    else (params[0], claim.publication_id, claim.request_fingerprint, params[1]),
                )
                if await cursor.fetchone() is None:
                    raise FacebookPublicationConflict("Facebook recovery state changed")
                row = await self._find_claim(connection, claim)
                if row is None:
                    raise FacebookPublicationConflict("Facebook claim is unavailable")
                return self._claim(row)
        except (FacebookPublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Facebook publication storage is unavailable") from exc

    async def _recover_claim(
        self, request: FacebookPublishRequest, expected_phase: str,
    ) -> FacebookPublicationClaim:
        if not isinstance(request, FacebookPublishRequest):
            raise ValueError("Facebook recovery request is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                row = await self._find_request(
                    connection, request_id=request.request_id,
                    brand_id=request.brand_id, owner_user_id=request.owner_user_id,
                )
                if row is None:
                    raise FacebookPublicationConflict("Facebook claim is unavailable")
                claim = self._claim(row)
                if (claim.publication_id != request.publication_id
                        or claim.request_fingerprint != request.fingerprint
                        or claim.phase != expected_phase):
                    raise FacebookPublicationConflict("Facebook publication is not recoverable")
                return claim
        except (FacebookPublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Facebook publication storage is unavailable") from exc

    async def cancel_unknown(
        self, *, request: FacebookPublishRequest, reason: str,
    ) -> FacebookPublicationResult:
        normalized = reason.strip() if isinstance(reason, str) else ""
        if (not isinstance(request, FacebookPublishRequest) or not normalized
                or len(normalized) > 500 or any(ord(char) < 32 for char in normalized)
                or re.search(r"(?i)(token|secret|credential|authorization|cookie)\s*[:=]", normalized)):
            raise ValueError("Facebook cancellation reason is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                row = await self._find_request(
                    connection, request_id=request.request_id,
                    brand_id=request.brand_id, owner_user_id=request.owner_user_id,
                )
                if row is None:
                    raise FacebookPublicationConflict("Facebook claim is unavailable")
                claim = self._claim(row)
                if (claim.publication_id != request.publication_id
                        or claim.request_fingerprint != request.fingerprint
                        or claim.phase not in {"START_RESERVED", "UPLOAD_RESERVED", "PUBLISH_RESERVED"}):
                    raise FacebookPublicationConflict("Facebook publication cannot be cancelled")
                cursor = await connection.execute(
                    """UPDATE publication_jobs SET status = 'CANCELLED',
                              facebook_phase = 'CANCELLED',
                              last_error_code = 'OPERATOR_CANCELLED',
                              last_error_message = %s
                       WHERE id = %s AND request_fingerprint = %s
                         AND facebook_phase IN ('START_RESERVED','UPLOAD_RESERVED','PUBLISH_RESERVED')
                       RETURNING id, status, remote_upload_id, remote_url""",
                    (normalized, claim.publication_id, claim.request_fingerprint),
                )
                result = await cursor.fetchone()
                if result is None:
                    raise FacebookPublicationConflict("Facebook cancellation state changed")
                return FacebookPublicationResult(result[0], result[1], result[2], result[3])
        except (FacebookPublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Facebook publication storage is unavailable") from exc

    async def _update_claim(self, claim, query, params) -> FacebookPublicationClaim:
        if not isinstance(claim, FacebookPublicationClaim):
            raise ValueError("Facebook publication claim is required")
        try:
            async with unit_of_work(self._pool) as connection:
                await self._lock_owned(connection, claim)
                cursor = await connection.execute(query, params)
                if await cursor.fetchone() is None:
                    raise FacebookPublicationConflict("Facebook publication state changed")
                row = await self._find_claim(connection, claim)
                if row is None:
                    raise FacebookPublicationConflict("Facebook claim is unavailable")
                return self._claim(row)
        except (FacebookPublicationConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("Facebook publication storage is unavailable") from exc

    @staticmethod
    async def _lock_owned(connection, claim: FacebookPublicationClaim) -> None:
        cursor = await connection.execute(
            """SELECT p.status FROM publication_jobs AS p
               JOIN social_channels AS ch ON ch.id = p.channel_id
               JOIN brands AS b ON b.id = ch.brand_id
               WHERE p.id = %s AND p.request_fingerprint = %s
                 AND p.publication_contract = 'FACEBOOK_REELS_V1'
                 AND p.asset_id = %s AND p.channel_id = %s
                 AND b.id = %s AND b.owner_user_id = %s
               FOR UPDATE OF p""",
            (claim.publication_id, claim.request_fingerprint, claim.asset_id,
             claim.channel_id, claim.brand_id, claim.owner_user_id),
        )
        if await cursor.fetchone() is None:
            raise FacebookPublicationConflict("Facebook claim is unavailable")

    @staticmethod
    async def _find_request(connection, *, request_id: UUID, brand_id: UUID, owner_user_id: str):
        cursor = await connection.execute(
            f"""SELECT {_CLAIM_COLUMNS} FROM publication_jobs AS p
                JOIN social_channels AS ch ON ch.id = p.channel_id
                JOIN brands AS b ON b.id = ch.brand_id
                JOIN assets AS a ON a.id = p.asset_id
                WHERE p.request_id = %s AND p.publication_contract = 'FACEBOOK_REELS_V1'
                  AND b.id = %s AND b.owner_user_id = %s FOR UPDATE OF p""",
            (request_id, brand_id, owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    async def _find_claim(connection, claim: FacebookPublicationClaim):
        cursor = await connection.execute(
            f"""SELECT {_CLAIM_COLUMNS} FROM publication_jobs AS p
                JOIN social_channels AS ch ON ch.id = p.channel_id
                JOIN brands AS b ON b.id = ch.brand_id
                JOIN assets AS a ON a.id = p.asset_id
                WHERE p.id = %s AND p.request_fingerprint = %s
                  AND p.publication_contract = 'FACEBOOK_REELS_V1'
                  AND b.id = %s AND b.owner_user_id = %s FOR UPDATE OF p""",
            (claim.publication_id, claim.request_fingerprint,
             claim.brand_id, claim.owner_user_id),
        )
        return await cursor.fetchone()

    @staticmethod
    def _destination_fingerprint(external_id: str, credentials_ref: str) -> str:
        return hashlib.sha256(f"{external_id}|{credentials_ref}".encode("utf-8")).hexdigest()

    @staticmethod
    def _status_evidence(remote: FacebookVideoStatus) -> str:
        return json.dumps({
            "schema_version": 1,
            "video_id": remote.video_id,
            "page_id": remote.page_id,
            "video_status": remote.state.value,
            "uploading_status": remote.uploading_status,
            "processing_status": remote.processing_status,
            "publishing_status": remote.publishing_status,
            "bytes_transferred": remote.bytes_transferred,
            "source_file_size": remote.source_file_size,
        }, sort_keys=True, separators=(",", ":"))

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
            and media.get("export_profile_id") == "FACEBOOK_REELS_V1"
            and media.get("platform") == "FACEBOOK"
            and media.get("publishing_performed") is False
            and values["profile_id"] == "FACEBOOK_REELS_V1"
            and values["render_version"] == request.artifact_version
            and isinstance(values["approval_id"], UUID)
            and values["decision"] == "APPROVE"
            and values["platform"] == "FACEBOOK"
            and _SAFE_PAGE_ID.fullmatch(values["external_id"] or "")
            and _SECRET_REF.fullmatch(values["credentials_ref"] or "")
            and values["permissions"] == "VALID" and values["enabled"] is True
        )

    @staticmethod
    def _claim(row) -> FacebookPublicationClaim:
        try:
            (publication_id, fingerprint, brand_id, owner_user_id, content_id,
             channel_id, asset_id, approval_id, artifact_version, external_id,
             credentials_ref, destination_fingerprint, storage_uri, sha256_hex,
             size_bytes, mime_type, status, phase, video_id, session_ref,
             post_id, remote_url, verification_attempt_count) = row
            return FacebookPublicationClaim(
                publication_id=publication_id, request_fingerprint=fingerprint.strip(),
                brand_id=brand_id, owner_user_id=owner_user_id, content_id=content_id,
                channel_id=channel_id, asset_id=asset_id,
                approval_decision_id=approval_id, artifact_version=artifact_version,
                page_id=external_id, credentials_ref=credentials_ref,
                destination_fingerprint=destination_fingerprint.strip(),
                asset_storage_uri=storage_uri, asset_sha256_hex=sha256_hex.strip(),
                asset_size_bytes=size_bytes, asset_mime_type=mime_type,
                status=status, phase=phase,
                verification_attempt_count=verification_attempt_count,
                remote_video_id=video_id, upload_session_ref=session_ref,
                remote_post_id=post_id, remote_url=remote_url,
            )
        except Exception as exc:
            raise RepositoryUnavailable("stored Facebook publication claim is invalid") from exc
