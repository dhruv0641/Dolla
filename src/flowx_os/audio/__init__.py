"""Local audio capability contracts."""

from .tts_evaluation import (
    TtsEngineSpec,
    TtsEvaluation,
    TtsEvaluationPolicy,
    TtsEvaluator,
)
from .synthesis import (
    LocalTtsProvider,
    SynthesisClaim,
    SynthesisPolicy,
    SynthesisRequest,
    SynthesisResult,
    TtsSynthesisError,
    VoiceConsentStatus,
    VoiceLicenseStatus,
    VoiceProfile,
    VoiceSource,
    VoiceSynthesisService,
    WavEvidence,
    inspect_pcm_wav,
    synthesis_fingerprint,
)

__all__ = [
    "LocalTtsProvider", "SynthesisClaim", "SynthesisPolicy", "SynthesisRequest",
    "SynthesisResult", "TtsEngineSpec", "TtsEvaluation", "TtsEvaluationPolicy",
    "TtsEvaluator", "TtsSynthesisError", "VoiceConsentStatus", "VoiceLicenseStatus",
    "VoiceProfile", "VoiceSource", "VoiceSynthesisService", "WavEvidence",
    "inspect_pcm_wav", "synthesis_fingerprint",
]
