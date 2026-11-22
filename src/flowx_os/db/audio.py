"""Owner-scoped persistence for local voice profiles and synthesis claims."""

from __future__ import annotations

import json
import re
from uuid import UUID

from flowx_os.audio.synthesis import (
    SynthesisClaim,
    SynthesisRequest,
    SynthesisResult,
    VoiceConsentStatus,
    VoiceLicenseStatus,
    VoiceProfile,
    VoiceSource,
    WavEvidence,
)
from flowx_os.db.content import OwnedContentNotFound, RepositoryUnavailable
from flowx_os.db.transaction import ConnectionPool, unit_of_work


class VoiceProfileConflict(RuntimeError):
    """A profile identity is already bound to different immutable settings."""


class SynthesisStateConflict(RuntimeError):
    """A synthesis request cannot be safely started or transitioned."""


_PROFILE_COLUMNS = """vp.id, vp.brand_id, vp.name, vp.engine_name, vp.engine_version,
                       vp.voice_key, vp.language, vp.sample_rate_hz, vp.channels,
                       vp.source, vp.license_status, vp.license_reference,
                       vp.consent_status, vp.consent_reference, vp.active, vp.config"""


def _profile(row: tuple[object, ...]) -> VoiceProfile:
    try:
        config = row[15]
        if isinstance(config, str):
            config = json.loads(config)
        return VoiceProfile(
            profile_id=row[0], brand_id=row[1], name=row[2], engine_name=row[3],
            engine_version=row[4], voice_key=row[5], language=row[6],
            sample_rate_hz=row[7], channels=row[8], source=VoiceSource(row[9]),
            license_status=VoiceLicenseStatus(row[10]), license_reference=row[11],
            consent_status=VoiceConsentStatus(row[12]), consent_reference=row[13],
            active=row[14], config=config,
        )
    except Exception as exc:
        raise RepositoryUnavailable("stored voice profile is invalid") from exc


def _profile_snapshot(profile: VoiceProfile) -> str:
    return json.dumps(
        profile.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


class AudioRepository:
    """Create immutable profiles and claim synthesis before provider execution."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def create_profile(self, *, profile: VoiceProfile, owner_user_id: str) -> VoiceProfile:
        if not isinstance(profile, VoiceProfile) or not isinstance(owner_user_id, str) or not owner_user_id.strip():
            raise ValueError("voice profile request is invalid")
        config = json.dumps(profile.config, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    "SELECT 1 FROM brands WHERE id = %s AND owner_user_id = %s FOR KEY SHARE",
                    (profile.brand_id, owner_user_id.strip()),
                )
                if await cursor.fetchone() is None:
                    raise OwnedContentNotFound("brand not found")
                cursor = await connection.execute(
                    f"""INSERT INTO voice_profiles
                         (id, brand_id, name, engine_name, engine_version, voice_key,
                          language, sample_rate_hz, channels, source, license_status,
                          license_reference, consent_status, consent_reference, active, config)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                       ON CONFLICT DO NOTHING RETURNING {_PROFILE_COLUMNS.replace('vp.', '')}""",
                    (profile.profile_id, profile.brand_id, profile.name, profile.engine_name,
                     profile.engine_version, profile.voice_key, profile.language,
                     profile.sample_rate_hz, profile.channels, profile.source.value,
                     profile.license_status.value, profile.license_reference,
                     profile.consent_status.value, profile.consent_reference,
                     profile.active, config),
                )
                row = await cursor.fetchone()
                if row is None:
                    cursor = await connection.execute(
                        f"""SELECT {_PROFILE_COLUMNS} FROM voice_profiles AS vp
                           JOIN brands AS b ON b.id = vp.brand_id
                           WHERE vp.id = %s AND b.owner_user_id = %s""",
                        (profile.profile_id, owner_user_id.strip()),
                    )
                    row = await cursor.fetchone()
                    if row is None or _profile(row) != profile:
                        raise VoiceProfileConflict("voice profile identity is already registered")
                return _profile(row)
        except (OwnedContentNotFound, VoiceProfileConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("voice profile storage is unavailable") from exc

    async def get_profile(self, *, profile_id: UUID, brand_id: UUID, owner_user_id: str) -> VoiceProfile:
        if (not isinstance(profile_id, UUID) or not isinstance(brand_id, UUID)
                or not isinstance(owner_user_id, str) or not owner_user_id.strip()):
            raise ValueError("voice profile lookup is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""SELECT {_PROFILE_COLUMNS} FROM voice_profiles AS vp
                       JOIN brands AS b ON b.id = vp.brand_id
                       WHERE vp.id = %s AND vp.brand_id = %s AND b.owner_user_id = %s""",
                    (profile_id, brand_id, owner_user_id.strip()),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise OwnedContentNotFound("voice profile not found")
                return _profile(row)
        except (OwnedContentNotFound, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("voice profile storage is unavailable") from exc

    async def deactivate_profile(self, *, profile_id: UUID, brand_id: UUID,
                                 owner_user_id: str) -> VoiceProfile:
        """Irreversibly disable future claims without mutating profile evidence."""
        if (not isinstance(profile_id, UUID) or not isinstance(brand_id, UUID)
                or not isinstance(owner_user_id, str) or not owner_user_id.strip()):
            raise ValueError("voice profile deactivation is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""UPDATE voice_profiles AS vp SET active = false
                       FROM brands AS b WHERE vp.id = %s AND vp.brand_id = %s
                         AND b.id = vp.brand_id AND b.owner_user_id = %s
                       RETURNING {_PROFILE_COLUMNS}""",
                    (profile_id, brand_id, owner_user_id.strip()),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise OwnedContentNotFound("voice profile not found")
                return _profile(row)
        except (OwnedContentNotFound, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("voice profile storage is unavailable") from exc

    async def claim(self, *, request: SynthesisRequest, profile: VoiceProfile,
                    request_fingerprint: str) -> SynthesisClaim:
        if (not isinstance(request, SynthesisRequest) or not isinstance(profile, VoiceProfile)
                or not isinstance(request_fingerprint, str)
                or re.fullmatch(r"[0-9a-f]{64}", request_fingerprint) is None):
            raise ValueError("synthesis claim is invalid")
        snapshot = _profile_snapshot(profile)
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    f"""SELECT {_PROFILE_COLUMNS} FROM voice_profiles AS vp
                       JOIN brands AS b ON b.id = vp.brand_id
                       JOIN content_items AS c ON c.brand_id = b.id
                       WHERE vp.id = %s AND vp.brand_id = %s AND b.owner_user_id = %s
                         AND c.id = %s AND vp.active = true
                         AND vp.license_status = 'VERIFIED'
                         AND vp.consent_status IN ('NOT_REQUIRED','VERIFIED')
                       FOR SHARE OF vp, b, c""",
                    (profile.profile_id, request.brand_id, request.owner_user_id, request.content_id),
                )
                current_row = await cursor.fetchone()
                if current_row is None:
                    raise OwnedContentNotFound("synthesis lineage not found")
                if _profile(current_row) != profile:
                    raise SynthesisStateConflict("voice profile changed before synthesis claim")
                if request.scene_id is not None:
                    cursor = await connection.execute(
                        "SELECT 1 FROM scenes WHERE id = %s AND content_id = %s FOR KEY SHARE",
                        (request.scene_id, request.content_id),
                    )
                    if await cursor.fetchone() is None:
                        raise OwnedContentNotFound("synthesis scene not found")
                cursor = await connection.execute(
                    """INSERT INTO tts_synthesis_requests
                         (id, asset_id, profile_id, brand_id, content_id, scene_id,
                          request_fingerprint, profile_snapshot)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                       ON CONFLICT (id) DO NOTHING RETURNING id""",
                    (request.request_id, request.asset_id, profile.profile_id, request.brand_id,
                     request.content_id, request.scene_id, request_fingerprint, snapshot),
                )
                if await cursor.fetchone() is not None:
                    return SynthesisClaim(True)
                cursor = await connection.execute(
                    """SELECT r.asset_id, r.profile_id, r.brand_id, r.content_id, r.scene_id,
                              r.request_fingerprint, r.profile_snapshot, r.status,
                              r.completed_asset_id, r.duration_ms, r.sample_rate_hz,
                              r.channels, r.sample_width_bytes
                       FROM tts_synthesis_requests AS r
                       JOIN brands AS b ON b.id = r.brand_id
                       WHERE r.id = %s AND b.owner_user_id = %s FOR UPDATE OF r""",
                    (request.request_id, request.owner_user_id),
                )
                row = await cursor.fetchone()
                expected = (
                    request.asset_id, profile.profile_id, request.brand_id, request.content_id,
                    request.scene_id, request_fingerprint,
                )
                stored_snapshot = None if row is None else (
                    json.loads(row[6]) if isinstance(row[6], str) else row[6]
                )
                if row is None or tuple(row[:6]) != expected or stored_snapshot != json.loads(snapshot):
                    raise SynthesisStateConflict("synthesis request identity conflicts with stored state")
                if row[7] != "COMPLETED" or row[8] != request.asset_id:
                    raise SynthesisStateConflict("synthesis request requires reconciliation; do not retry automatically")
                evidence = WavEvidence(row[9], row[10], row[11], row[12])
                result = SynthesisResult(request.request_id, request.asset_id, request_fingerprint, evidence, True)
                return SynthesisClaim(False, result)
        except (OwnedContentNotFound, SynthesisStateConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("synthesis claim storage is unavailable") from exc

    async def complete(self, *, result: SynthesisResult) -> None:
        if not isinstance(result, SynthesisResult):
            raise ValueError("synthesis result is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """UPDATE tts_synthesis_requests AS r SET
                         status = 'COMPLETED', completed_asset_id = %s,
                         duration_ms = %s, sample_rate_hz = %s, channels = %s,
                         sample_width_bytes = %s, completed_at = now()
                       WHERE r.id = %s AND r.asset_id = %s AND r.request_fingerprint = %s
                         AND r.status = 'CLAIMED'
                         AND EXISTS (SELECT 1 FROM assets AS a
                                     WHERE a.id = r.asset_id AND a.content_id = r.content_id
                                       AND a.asset_kind = 'NARRATION' AND a.retention_state = 'ACTIVE')
                       RETURNING r.id""",
                    (result.asset_id, result.evidence.duration_ms, result.evidence.sample_rate_hz,
                     result.evidence.channels, result.evidence.sample_width_bytes,
                     result.request_id, result.asset_id, result.request_fingerprint),
                )
                if await cursor.fetchone() is None:
                    raise SynthesisStateConflict("synthesis completion could not be committed")
        except (SynthesisStateConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("synthesis completion storage is unavailable") from exc

    async def fail(self, *, request_id: UUID, error_code: str) -> None:
        if (not isinstance(request_id, UUID) or not isinstance(error_code, str)
                or re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}", error_code) is None):
            raise ValueError("synthesis failure is invalid")
        try:
            async with unit_of_work(self._pool) as connection:
                cursor = await connection.execute(
                    """UPDATE tts_synthesis_requests SET status = 'FAILED', error_code = %s,
                         completed_at = now() WHERE id = %s AND status = 'CLAIMED' RETURNING id""",
                    (error_code, request_id),
                )
                if await cursor.fetchone() is None:
                    raise SynthesisStateConflict("synthesis failure could not be committed")
        except (SynthesisStateConflict, RepositoryUnavailable):
            raise
        except Exception as exc:
            raise RepositoryUnavailable("synthesis failure storage is unavailable") from exc
