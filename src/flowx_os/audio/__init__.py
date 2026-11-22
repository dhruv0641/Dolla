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
from .normalization import (
    AudioNormalizationError,
    AudioNormalizationPolicy,
    AudioNormalizationRequest,
    AudioNormalizationResult,
    AudioNormalizationService,
    NarrationTiming,
    normalization_fingerprint,
)
from .captions import (
    CaptionAlignmentError,
    CaptionAlignmentService,
    CaptionCue,
    CaptionPolicy,
    CaptionRequest,
    CaptionResult,
    build_caption_cues,
    caption_fingerprint,
    render_srt,
)

__all__ = [
    "LocalTtsProvider", "SynthesisClaim", "SynthesisPolicy", "SynthesisRequest",
    "SynthesisResult", "TtsEngineSpec", "TtsEvaluation", "TtsEvaluationPolicy",
    "TtsEvaluator", "TtsSynthesisError", "VoiceConsentStatus", "VoiceLicenseStatus",
    "VoiceProfile", "VoiceSource", "VoiceSynthesisService", "WavEvidence",
    "inspect_pcm_wav", "synthesis_fingerprint",
    "AudioNormalizationError", "AudioNormalizationPolicy", "AudioNormalizationRequest",
    "AudioNormalizationResult", "AudioNormalizationService", "NarrationTiming",
    "normalization_fingerprint",
    "CaptionAlignmentError", "CaptionAlignmentService", "CaptionCue", "CaptionPolicy",
    "CaptionRequest", "CaptionResult", "build_caption_cues", "caption_fingerprint",
    "render_srt",
]
