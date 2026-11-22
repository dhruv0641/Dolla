"""Fail-closed, provider-neutral contracts for local narration synthesis."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unicodedata
from typing import Protocol
from uuid import UUID
import wave

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from flowx_os.assets.service import AssetIngestService
from flowx_os.db.assets import AssetRecord
from flowx_os.domain.assets import AssetKind


class VoiceLicenseStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    REJECTED = "REJECTED"


class VoiceConsentStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    VERIFIED = "VERIFIED"
    MISSING = "MISSING"
    REVOKED = "REVOKED"


class VoiceSource(StrEnum):
    LOCAL_BUILTIN = "LOCAL_BUILTIN"


class VoiceProfile(BaseModel):
    """Immutable engine/voice selection owned by one brand."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    profile_id: UUID
    brand_id: UUID
    name: str = Field(min_length=1, max_length=120)
    engine_name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    engine_version: str = Field(min_length=1, max_length=120)
    voice_key: str = Field(min_length=1, max_length=160)
    language: str = Field(min_length=2, max_length=35, pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
    sample_rate_hz: int = Field(ge=8_000, le=96_000)
    channels: int = Field(ge=1, le=2)
    source: VoiceSource = VoiceSource.LOCAL_BUILTIN
    license_status: VoiceLicenseStatus
    license_reference: str | None = Field(default=None, max_length=500)
    consent_status: VoiceConsentStatus
    consent_reference: str | None = Field(default=None, max_length=500)
    active: bool = True
    config_ref: str | None = Field(default=None, max_length=500)

    @field_validator("name", "engine_version", "voice_key")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = unicodedata.normalize("NFC", value).strip()
        if not normalized or any(unicodedata.category(char) == "Cc" for char in normalized):
            raise ValueError("voice profile text is invalid")
        return normalized

    @field_validator("license_reference", "consent_reference", "config_ref")
    @classmethod
    def validate_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = unicodedata.normalize("NFC", value).strip()
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/\\-"
        if not normalized or len(normalized) > 500 or any(char not in allowed for char in normalized):
            raise ValueError("voice evidence/configuration reference is invalid")
        return normalized

    @model_validator(mode="after")
    def validate_evidence(self) -> "VoiceProfile":
        if self.license_status == VoiceLicenseStatus.VERIFIED and self.license_reference is None:
            raise ValueError("verified voice license requires a reference")
        if self.consent_status == VoiceConsentStatus.VERIFIED and self.consent_reference is None:
            raise ValueError("verified voice consent requires a reference")
        return self


class SynthesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    request_id: UUID
    asset_id: UUID
    profile_id: UUID
    brand_id: UUID
    content_id: UUID
    scene_id: UUID | None = None
    owner_user_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=12_000)

    @field_validator("owner_user_id")
    @classmethod
    def normalize_owner(cls, value: str) -> str:
        value = value.strip()
        if not value or any(unicodedata.category(char) == "Cc" for char in value):
            raise ValueError("owner identity is invalid")
        return value

    @field_validator("text")
    @classmethod
    def normalize_narration(cls, value: str) -> str:
        value = " ".join(unicodedata.normalize("NFC", value).split())
        if not value or any(unicodedata.category(char) == "Cc" for char in value):
            raise ValueError("narration text is invalid")
        return value


@dataclass(frozen=True, slots=True)
class SynthesisPolicy:
    timeout_seconds: float = 120.0
    max_output_bytes: int = 100_000_000
    max_duration_seconds: float = 180.0

    def __post_init__(self) -> None:
        if isinstance(self.timeout_seconds, bool) or not 0 < self.timeout_seconds <= 600:
            raise ValueError("synthesis timeout is invalid")
        if type(self.max_output_bytes) is not int or not 1_024 <= self.max_output_bytes <= 1_000_000_000:
            raise ValueError("synthesis output limit is invalid")
        if isinstance(self.max_duration_seconds, bool) or not 0 < self.max_duration_seconds <= 600:
            raise ValueError("synthesis duration limit is invalid")


@dataclass(frozen=True, slots=True)
class WavEvidence:
    duration_ms: int
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    request_id: UUID
    asset_id: UUID
    request_fingerprint: str
    evidence: WavEvidence
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class SynthesisClaim:
    is_new: bool
    completed: SynthesisResult | None = None

    def __post_init__(self) -> None:
        if self.is_new == (self.completed is not None):
            raise ValueError("synthesis claim state is invalid")


class LocalTtsProvider(Protocol):
    """Configured local adapter; it may write only to ``output_path``."""

    engine_name: str
    engine_version: str

    async def synthesize(self, *, profile: VoiceProfile, text: str, output_path: Path) -> None: ...


class SynthesisStore(Protocol):
    async def get_profile(self, *, profile_id: UUID, brand_id: UUID, owner_user_id: str) -> VoiceProfile: ...
    async def claim(self, *, request: SynthesisRequest, profile: VoiceProfile,
                    request_fingerprint: str) -> SynthesisClaim: ...
    async def complete(self, *, result: SynthesisResult) -> None: ...
    async def fail(self, *, request_id: UUID, error_code: str) -> None: ...


class AssetIngest(Protocol):
    async def ingest(self, **kwargs: object) -> AssetRecord: ...


class TtsSynthesisError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def synthesis_fingerprint(request: SynthesisRequest, profile: VoiceProfile) -> str:
    payload = {
        "schema": 1,
        "request_id": request.request_id.hex,
        "asset_id": request.asset_id.hex,
        "profile_id": profile.profile_id.hex,
        "brand_id": request.brand_id.hex,
        "content_id": request.content_id.hex,
        "scene_id": request.scene_id.hex if request.scene_id else None,
        "text": request.text,
        "engine": profile.engine_name,
        "engine_version": profile.engine_version,
        "voice_key": profile.voice_key,
        "language": profile.language,
        "sample_rate_hz": profile.sample_rate_hz,
        "channels": profile.channels,
        "config_ref": profile.config_ref,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def inspect_pcm_wav(path: Path, *, policy: SynthesisPolicy, profile: VoiceProfile) -> WavEvidence:
    try:
        file_stat = path.lstat()
        if (path.parent.is_symlink() or stat.S_ISLNK(file_stat.st_mode)
                or not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1):
            raise TtsSynthesisError("OUTPUT_UNSAFE", "synthesis output must be a regular file")
        if not 44 <= file_stat.st_size <= policy.max_output_bytes:
            raise TtsSynthesisError("OUTPUT_SIZE_INVALID", "synthesis output is outside the configured limit")
        with wave.open(os.fspath(path), "rb") as stream:
            if stream.getcomptype() != "NONE":
                raise TtsSynthesisError("OUTPUT_ENCODING_INVALID", "synthesis output must be uncompressed PCM WAV")
            sample_rate = stream.getframerate()
            channels = stream.getnchannels()
            sample_width = stream.getsampwidth()
            frames = stream.getnframes()
        if sample_rate != profile.sample_rate_hz or channels != profile.channels:
            raise TtsSynthesisError("OUTPUT_PROFILE_MISMATCH", "synthesis output does not match the voice profile")
        if sample_width not in {1, 2, 3, 4} or frames <= 0:
            raise TtsSynthesisError("OUTPUT_ENCODING_INVALID", "synthesis output PCM metadata is invalid")
        duration = frames / sample_rate
        if not 0 < duration <= policy.max_duration_seconds:
            raise TtsSynthesisError("OUTPUT_DURATION_INVALID", "synthesis output duration is outside the configured limit")
        return WavEvidence(max(1, round(duration * 1000)), sample_rate, channels, sample_width)
    except TtsSynthesisError:
        raise
    except (OSError, EOFError, wave.Error) as exc:
        raise TtsSynthesisError("OUTPUT_WAV_INVALID", "synthesis output is not a valid PCM WAV") from exc


class VoiceSynthesisService:
    """Claim, synthesize, validate and register one replay-safe narration asset."""

    def __init__(self, *, provider: LocalTtsProvider, store: SynthesisStore,
                 asset_ingest: AssetIngestService | AssetIngest, work_root: Path,
                 policy: SynthesisPolicy | None = None) -> None:
        self._provider = provider
        self._store = store
        self._asset_ingest = asset_ingest
        self._policy = policy or SynthesisPolicy()
        self._work_root = Path(work_root).expanduser()
        self._work_root.mkdir(parents=True, exist_ok=True)
        if self._work_root.is_symlink() or not self._work_root.is_dir():
            raise ValueError("synthesis work root must be a real directory")
        self._work_root = self._work_root.resolve()

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        if not isinstance(request, SynthesisRequest):
            raise ValueError("synthesis request is required")
        profile = await self._store.get_profile(
            profile_id=request.profile_id, brand_id=request.brand_id,
            owner_user_id=request.owner_user_id,
        )
        self._assert_profile_ready(profile)
        fingerprint = synthesis_fingerprint(request, profile)
        claim = await self._store.claim(
            request=request, profile=profile, request_fingerprint=fingerprint,
        )
        if not claim.is_new:
            assert claim.completed is not None
            return SynthesisResult(
                claim.completed.request_id, claim.completed.asset_id,
                claim.completed.request_fingerprint, claim.completed.evidence, True,
            )

        error_code = "SYNTHESIS_FAILED"
        asset_registered = False
        try:
            with tempfile.TemporaryDirectory(prefix=f"tts-{request.request_id.hex}-", dir=self._work_root) as directory:
                output = Path(directory) / "narration.wav"
                try:
                    await asyncio.wait_for(
                        self._provider.synthesize(profile=profile, text=request.text, output_path=output),
                        timeout=self._policy.timeout_seconds,
                    )
                except TimeoutError as exc:
                    raise TtsSynthesisError("PROVIDER_TIMEOUT", "local TTS provider timed out") from exc
                except TtsSynthesisError:
                    raise
                except Exception as exc:
                    raise TtsSynthesisError("PROVIDER_FAILED", "local TTS provider failed") from exc
                evidence = await asyncio.to_thread(
                    inspect_pcm_wav, output, policy=self._policy, profile=profile,
                )
                await self._asset_ingest.ingest(
                    asset_id=request.asset_id, source_path=output, mime_type="audio/wav",
                    brand_id=request.brand_id, content_id=request.content_id,
                    owner_user_id=request.owner_user_id, kind=AssetKind.NARRATION,
                    scene_id=request.scene_id,
                    media_metadata={
                        "duration_ms": evidence.duration_ms,
                        "sample_rate_hz": evidence.sample_rate_hz,
                        "channels": evidence.channels,
                        "sample_width_bytes": evidence.sample_width_bytes,
                        "voice_profile_id": profile.profile_id.hex,
                        "tts_engine": profile.engine_name,
                        "tts_engine_version": profile.engine_version,
                    },
                )
                asset_registered = True
            result = SynthesisResult(request.request_id, request.asset_id, fingerprint, evidence)
            await self._store.complete(result=result)
            return result
        except TtsSynthesisError as exc:
            error_code = exc.code
            await self._record_failure(request.request_id, error_code)
            raise
        except Exception as exc:
            if asset_registered:
                raise TtsSynthesisError(
                    "SYNTHESIS_RECONCILE_REQUIRED",
                    "narration asset exists but completion is uncertain; do not retry automatically",
                ) from exc
            await self._record_failure(request.request_id, error_code)
            raise TtsSynthesisError(error_code, "synthesis could not be completed safely") from exc

    async def _record_failure(self, request_id: UUID, error_code: str) -> None:
        try:
            await self._store.fail(request_id=request_id, error_code=error_code)
        except Exception as exc:
            raise TtsSynthesisError(
                "SYNTHESIS_RECONCILE_REQUIRED",
                "synthesis outcome could not be persisted; do not retry automatically",
            ) from exc

    def _assert_profile_ready(self, profile: VoiceProfile) -> None:
        if not profile.active:
            raise TtsSynthesisError("PROFILE_INACTIVE", "voice profile is inactive")
        if profile.source != VoiceSource.LOCAL_BUILTIN:
            raise TtsSynthesisError("VOICE_SOURCE_UNSUPPORTED", "only local built-in voices are supported")
        if profile.license_status != VoiceLicenseStatus.VERIFIED:
            raise TtsSynthesisError("LICENSE_UNVERIFIED", "voice license is not verified")
        if profile.consent_status not in {VoiceConsentStatus.NOT_REQUIRED, VoiceConsentStatus.VERIFIED}:
            raise TtsSynthesisError("CONSENT_UNVERIFIED", "voice consent is not verified")
        if (getattr(self._provider, "engine_name", None) != profile.engine_name
                or getattr(self._provider, "engine_version", None) != profile.engine_version):
            raise TtsSynthesisError("ENGINE_MISMATCH", "local TTS provider does not match the voice profile")
