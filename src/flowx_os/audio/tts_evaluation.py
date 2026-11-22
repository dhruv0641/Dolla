"""Bounded, offline evaluation of explicitly configured local TTS engines.

This module discovers executable capability only. It does not synthesize audio,
download models, call a network service, or claim licensing from an executable
name. Synthesis belongs to a later task after an operator selects a verified
engine and voice profile.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time


class TtsEvaluationError(ValueError):
    """Invalid evaluator configuration."""


@dataclass(frozen=True, slots=True)
class TtsEngineSpec:
    name: str
    executable: str
    version_args: tuple[str, ...] = ("--version",)
    voices_args: tuple[str, ...] | None = None
    output_formats: tuple[str, ...] = ("wav",)
    license_reference: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not 1 <= len(self.name) <= 80 or any(ord(c) < 32 for c in self.name):
            raise TtsEvaluationError("engine name is invalid")
        if not isinstance(self.executable, str) or not self.executable.strip() or any(ord(c) < 32 for c in self.executable):
            raise TtsEvaluationError("engine executable is invalid")
        for args in (self.version_args, self.voices_args):
            if args is not None and (not isinstance(args, tuple) or any(not isinstance(x, str) or not x or len(x) > 200 for x in args)):
                raise TtsEvaluationError("engine arguments are invalid")
        if not isinstance(self.output_formats, tuple) or not self.output_formats or any(
            not isinstance(x, str) or not 1 <= len(x) <= 16 or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in x)
            for x in self.output_formats
        ):
            raise TtsEvaluationError("engine output formats are invalid")
        if self.license_reference is not None and (not isinstance(self.license_reference, str) or len(self.license_reference) > 300 or any(ord(c) < 32 for c in self.license_reference)):
            raise TtsEvaluationError("license reference is invalid")


@dataclass(frozen=True, slots=True)
class TtsEvaluationPolicy:
    engines: tuple[TtsEngineSpec, ...]
    timeout_seconds: float = 3.0
    output_limit_bytes: int = 32_768

    def __post_init__(self) -> None:
        if not isinstance(self.engines, tuple) or len(self.engines) > 32 or any(not isinstance(x, TtsEngineSpec) for x in self.engines):
            raise TtsEvaluationError("engine list is invalid")
        if isinstance(self.timeout_seconds, bool) or not 0 < self.timeout_seconds <= 30:
            raise TtsEvaluationError("TTS timeout is invalid")
        if type(self.output_limit_bytes) is not int or not 1024 <= self.output_limit_bytes <= 1_000_000:
            raise TtsEvaluationError("TTS output limit is invalid")


@dataclass(frozen=True, slots=True)
class TtsEngineEvidence:
    name: str
    available: bool
    executable_path: str | None
    version: str | None
    voices: tuple[str, ...]
    output_formats: tuple[str, ...]
    license_status: str
    latency_ms: int | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class TtsEvaluation:
    engines: tuple[TtsEngineEvidence, ...]
    recommended_engine: str | None
    synthesis_performed: bool = False


def _bounded_run(args: list[str], *, timeout: float, output_limit: int) -> tuple[int, bytes, int]:
    started = time.perf_counter()
    try:
        process = subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, close_fds=(os.name != "nt"),
        )
    except OSError as exc:
        raise OSError("TTS executable unavailable") from exc
    buffers = [bytearray(), bytearray()]
    overflow = threading.Event()

    def drain(pipe, buffer) -> None:
        try:
            while block := pipe.read(8192):
                if len(buffer) + len(block) > output_limit:
                    overflow.set()
                    try:
                        process.kill()
                    except OSError:
                        pass
                    return
                buffer.extend(block)
        finally:
            pipe.close()

    readers = [
        threading.Thread(target=drain, args=(pipe, buffer), daemon=True)
        for pipe, buffer in zip((process.stdout, process.stderr), buffers)
    ]
    for reader in readers:
        reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise TimeoutError("TTS capability probe timed out") from exc
    finally:
        for reader in readers:
            reader.join()
    if overflow.is_set():
        raise OverflowError("TTS capability probe output exceeded limit")
    return process.returncode, bytes(buffers[0]), max(1, int((time.perf_counter() - started) * 1000))


class TtsEvaluator:
    """Evaluate local engines named by the caller, without network access."""

    def __init__(self, policy: TtsEvaluationPolicy) -> None:
        if not isinstance(policy, TtsEvaluationPolicy):
            raise TtsEvaluationError("TTS policy is required")
        self._policy = policy

    def evaluate(self) -> TtsEvaluation:
        evidence: list[TtsEngineEvidence] = []
        for spec in self._policy.engines:
            evidence.append(self._evaluate_one(spec))
        available = [item for item in evidence if item.available]
        # Stable recommendation: preserve configured order among equally capable engines.
        recommended = max(available, key=lambda item: (len(item.voices) > 0, item.version is not None), default=None)
        return TtsEvaluation(tuple(evidence), recommended.name if recommended else None)

    def _evaluate_one(self, spec: TtsEngineSpec) -> TtsEngineEvidence:
        executable = shutil.which(spec.executable)
        if executable is None and Path(spec.executable).is_file():
            executable = str(Path(spec.executable).resolve())
        if executable is None:
            return TtsEngineEvidence(spec.name, False, None, None, (), spec.output_formats, "UNVERIFIED", None, "EXECUTABLE_UNAVAILABLE")
        try:
            code, output, latency = _bounded_run([executable, *spec.version_args], timeout=self._policy.timeout_seconds, output_limit=self._policy.output_limit_bytes)
            if code != 0:
                return TtsEngineEvidence(spec.name, False, executable, None, (), spec.output_formats, "UNVERIFIED", latency, "VERSION_PROBE_FAILED")
            version = output.decode("utf-8", "replace").strip().splitlines()[0][:500] if output.strip() else None
            if not version:
                return TtsEngineEvidence(spec.name, False, executable, None, (), spec.output_formats, "UNVERIFIED", latency, "VERSION_UNAVAILABLE")
            voices: tuple[str, ...] = ()
            voice_error: str | None = None
            if spec.voices_args is not None:
                try:
                    voice_code, voice_output, _ = _bounded_run([executable, *spec.voices_args], timeout=self._policy.timeout_seconds, output_limit=self._policy.output_limit_bytes)
                    if voice_code == 0:
                        voices = tuple(line.strip()[:120] for line in voice_output.decode("utf-8", "replace").splitlines() if line.strip())[:256]
                    else:
                        voice_error = "VOICE_PROBE_FAILED"
                except TimeoutError:
                    voice_error = "VOICE_PROBE_TIMEOUT"
                except OverflowError:
                    voice_error = "VOICE_PROBE_OUTPUT_LIMIT"
                except OSError:
                    voice_error = "VOICE_PROBE_UNAVAILABLE"
            return TtsEngineEvidence(spec.name, True, executable, version, voices, spec.output_formats, "UNVERIFIED", latency, voice_error)
        except TimeoutError:
            return TtsEngineEvidence(spec.name, False, executable, None, (), spec.output_formats, "UNVERIFIED", None, "PROBE_TIMEOUT")
        except OverflowError:
            return TtsEngineEvidence(spec.name, False, executable, None, (), spec.output_formats, "UNVERIFIED", None, "PROBE_OUTPUT_LIMIT")
        except OSError:
            return TtsEngineEvidence(spec.name, False, executable, None, (), spec.output_formats, "UNVERIFIED", None, "PROBE_UNAVAILABLE")
