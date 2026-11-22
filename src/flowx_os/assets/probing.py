"""Local media inspection against immutable managed asset bytes."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import threading

from .storage import StoredAssetFile


_MEDIA_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:+-]{0,63}$")
_CONTAINER_TOKEN = re.compile(r"^[a-z0-9_]{1,32}$")


class MediaProbeError(RuntimeError):
    """Safe error without untrusted tool output or filesystem paths."""


@dataclass(frozen=True)
class ProbePolicy:
    expected_duration_seconds: float | None = None
    duration_tolerance_seconds: float = 0.25
    expected_aspect_ratio: float | None = None
    aspect_tolerance: float = 0.02
    require_video: bool = True
    require_audio: bool = False
    max_width: int = 7680
    max_height: int = 7680
    video_codecs: tuple[str, ...] = ("h264", "hevc", "vp8", "vp9", "av1")
    audio_codecs: tuple[str, ...] = ("aac", "opus", "vorbis", "mp3", "pcm_s16le", "pcm_s24le", "pcm_f32le")

    def __post_init__(self):
        for value in (self.expected_duration_seconds, self.expected_aspect_ratio):
            if value is not None and (isinstance(value, bool) or not math.isfinite(value) or value <= 0):
                raise ValueError("expected media values must be finite and positive")
        for value in (self.duration_tolerance_seconds, self.aspect_tolerance):
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError("media tolerances must be finite and nonnegative")
        for value in (self.max_width, self.max_height):
            if type(value) is not int or not 1 <= value <= 16384:
                raise ValueError("media dimensions are invalid")
        if type(self.require_video) is not bool or type(self.require_audio) is not bool:
            raise ValueError("media stream requirements must be boolean")
        for codecs in (self.video_codecs, self.audio_codecs):
            if not isinstance(codecs, tuple) or any(not isinstance(c, str) or not c for c in codecs):
                raise ValueError("codec allowlists must be tuples of codec names")


@dataclass(frozen=True)
class MediaStream:
    kind: str
    codec: str
    width: int | None = None
    height: int | None = None
    display_aspect_ratio: float | None = None
    frame_rate: float | None = None
    video_profile: str | None = None
    pixel_format: str | None = None
    sample_rate: int | None = None
    channels: int | None = None


@dataclass(frozen=True)
class MediaReport:
    sha256_hex: str
    duration_seconds: float
    streams: tuple[MediaStream, ...]
    decode_verified: bool
    violations: tuple[str, ...]
    decoded_duration_seconds: float | None = None
    container_names: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.decode_verified and not self.violations

    def to_metadata(self) -> dict:
        """JSON-compatible evidence for AssetIngestService.media_metadata."""
        return json.loads(json.dumps({"media_probe": {**asdict(self), "passed": self.passed, "version": 1}}))


def _positive(value) -> float:
    if isinstance(value, bool):
        raise ValueError("invalid number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("invalid number")
    return number


def _parse_probe_document(payload: bytes) -> tuple[float, tuple[MediaStream, ...], tuple[str, ...]]:
    """Reject absent/invalid duration, streams, container and stream fields."""
    try:
        raw = json.loads(payload)
        duration = _positive(raw["format"]["duration"])
        format_name = raw["format"].get("format_name")
        if format_name is None:
            containers: tuple[str, ...] = ()
        elif (not isinstance(format_name, str) or len(format_name) > 200
              or not all(_CONTAINER_TOKEN.fullmatch(part) for part in format_name.split(","))):
            raise ValueError("invalid container")
        else:
            containers = tuple(format_name.split(","))
        streams = []
        if not isinstance(raw["streams"], list) or not 1 <= len(raw["streams"]) <= 64:
            raise ValueError("invalid stream count")
        for stream in raw["streams"]:
            kind, codec = stream["codec_type"], stream["codec_name"]
            if kind not in {"video", "audio", "subtitle"}:
                continue
            if not isinstance(codec, str) or _MEDIA_TOKEN.fullmatch(codec) is None:
                raise ValueError("invalid codec")
            if kind == "video":
                width, height = stream["width"], stream["height"]
                if type(width) is not int or type(height) is not int or not 0 < width <= 65536 or not 0 < height <= 65536:
                    raise ValueError("invalid dimensions")
                sar = stream.get("sample_aspect_ratio", "1:1")
                if sar in {"N/A", "0:1"}:
                    sar = "1:1"
                ratio = width / height * _positive(Fraction(sar.replace(":", "/")))
                raw_rate = stream.get("avg_frame_rate")
                rate = None if raw_rate is None else _positive(Fraction(raw_rate))
                for side in stream.get("side_data_list", []):
                    if "rotation" in side:
                        rotation = float(side["rotation"])
                        if not math.isfinite(rotation) or rotation % 90 != 0:
                            raise ValueError("unsupported rotation")
                        if rotation % 180:
                            width, height, ratio = height, width, 1 / ratio
                profile, pixel_format = stream.get("profile"), stream.get("pix_fmt")
                for value in (profile, pixel_format):
                    if value is not None and (not isinstance(value, str) or _MEDIA_TOKEN.fullmatch(value) is None):
                        raise ValueError("invalid video profile")
                streams.append(MediaStream(
                    kind, codec, width, height, ratio, rate,
                    video_profile=profile, pixel_format=pixel_format,
                ))
            elif kind == "audio":
                rate = _positive(stream["sample_rate"])
                channels = stream["channels"]
                if rate != int(rate) or rate > 768000 or type(channels) is not int or not 1 <= channels <= 64:
                    raise ValueError("invalid audio properties")
                streams.append(MediaStream(kind, codec, sample_rate=int(rate), channels=channels))
            else:
                streams.append(MediaStream(kind, codec))
        if not streams:
            raise ValueError("no media streams")
        return duration, tuple(streams), containers
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, ZeroDivisionError, RecursionError) as exc:
        raise MediaProbeError("MEDIA_METADATA_INVALID") from exc


def parse_probe(payload: bytes) -> tuple[float, tuple[MediaStream, ...]]:
    """Backward-compatible public parser for duration and typed streams."""
    duration, streams, _ = _parse_probe_document(payload)
    return duration, streams


def _run(args: list[str], *, timeout: float, output_limit: int) -> bytes:
    """Drain both pipes, kill on output cap/timeout, and never expose stderr."""
    try:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    except OSError as exc:
        raise MediaProbeError("MEDIA_TOOL_UNAVAILABLE") from exc
    buffers = [bytearray(), bytearray()]
    exceeded = threading.Event()
    def drain(pipe, buffer):
        try:
            while block := pipe.read(8192):
                if len(buffer) + len(block) > output_limit:
                    exceeded.set()
                    process.kill()
                    break
                buffer.extend(block)
        finally:
            pipe.close()
    threads = [threading.Thread(target=drain, args=(pipe, buffer), daemon=True)
               for pipe, buffer in zip((process.stdout, process.stderr), buffers)]
    for thread in threads:
        thread.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise MediaProbeError("MEDIA_TOOL_TIMEOUT") from exc
    finally:
        for thread in threads:
            thread.join()
    if exceeded.is_set():
        raise MediaProbeError("MEDIA_TOOL_OUTPUT_LIMIT")
    if process.returncode != 0:
        raise MediaProbeError("MEDIA_TOOL_FAILED")
    return bytes(buffers[0])


def _violations(duration: float, streams: tuple[MediaStream, ...], policy: ProbePolicy) -> tuple[str, ...]:
    failures = []
    video = [s for s in streams if s.kind == "video"]
    audio = [s for s in streams if s.kind == "audio"]
    if policy.require_video and not video:
        failures.append("VIDEO_REQUIRED")
    if policy.require_audio and not audio:
        failures.append("AUDIO_REQUIRED")
    if policy.expected_duration_seconds is not None and abs(duration - policy.expected_duration_seconds) > policy.duration_tolerance_seconds:
        failures.append("DURATION_MISMATCH")
    for s in video:
        if s.codec not in policy.video_codecs:
            failures.append("VIDEO_CODEC_UNSUPPORTED")
        if s.width > policy.max_width or s.height > policy.max_height:
            failures.append("DIMENSIONS_EXCEEDED")
        if policy.expected_aspect_ratio is not None and abs(s.display_aspect_ratio - policy.expected_aspect_ratio) > policy.aspect_tolerance:
            failures.append("ASPECT_RATIO_MISMATCH")
    if any(s.codec not in policy.audio_codecs for s in audio):
        failures.append("AUDIO_CODEC_UNSUPPORTED")
    return tuple(dict.fromkeys(failures))


class MediaProbeService:
    """Inspect a bounded private snapshot of an authorized managed asset.

    Authorization belongs to the caller's owner-scoped asset repository. A
    successful report is technical evidence, not approval to publish.
    """
    _FORMATS = {"video/mp4": "mov", "video/webm": "matroska", "audio/wav": "wav", "audio/mpeg": "mp3", "audio/ogg": "ogg"}

    def __init__(self, storage_root: Path, *, ffprobe: str = "ffprobe", ffmpeg: str = "ffmpeg", timeout_seconds: float = 60, max_bytes: int = 2_000_000_000, output_limit: int = 1_000_000):
        if type(max_bytes) is not int or not 1 <= max_bytes <= 4_000_000_000 or type(output_limit) is not int or not 1024 <= output_limit <= 8_000_000:
            raise ValueError("media resource limits are invalid")
        if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 600:
            raise ValueError("media timeout is invalid")
        self.root = Path(storage_root).resolve() / "assets"
        self.ffprobe, self.ffmpeg = ffprobe, ffmpeg
        self.timeout, self.max_bytes, self.output_limit = timeout_seconds, max_bytes, output_limit

    def inspect(self, asset: StoredAssetFile, policy: ProbePolicy | None = None) -> MediaReport:
        policy = policy or ProbePolicy()
        if not isinstance(asset, StoredAssetFile) or not isinstance(policy, ProbePolicy):
            raise ValueError("asset and probe policy are required")
        demuxer = self._FORMATS.get(asset.mime_type)
        if demuxer is None:
            raise MediaProbeError("MEDIA_TYPE_UNSUPPORTED")
        expected = self.root / asset.asset_id.hex / "payload"
        try:
            if asset.path.absolute() != expected or any(p.is_symlink() for p in (self.root, expected.parent, expected)):
                raise MediaProbeError("MEDIA_PATH_UNSAFE")
            if not stat.S_ISREG(expected.lstat().st_mode):
                raise MediaProbeError("MEDIA_PATH_UNSAFE")
            with tempfile.TemporaryDirectory(prefix="flowx-probe-") as temporary:
                snapshot = Path(temporary) / "input"
                digest, size = hashlib.sha256(), 0
                with expected.open("rb") as incoming, snapshot.open("xb") as output:
                    if not stat.S_ISREG(os.fstat(incoming.fileno()).st_mode):
                        raise MediaProbeError("MEDIA_PATH_UNSAFE")
                    while block := incoming.read(1024 * 1024):
                        size += len(block)
                        if size > self.max_bytes:
                            raise MediaProbeError("MEDIA_SIZE_LIMIT")
                        digest.update(block)
                        output.write(block)
                if size <= 0 or size != asset.size_bytes or digest.hexdigest() != asset.sha256_hex:
                    raise MediaProbeError("MEDIA_INTEGRITY_MISMATCH")
                options = ["-protocol_whitelist", "file", "-format_whitelist", demuxer, "-f", demuxer]
                if demuxer == "mov":
                    options += ["-enable_drefs", "0", "-use_absolute_path", "0"]
                payload = _run([self.ffprobe, "-v", "error", "-max_alloc", "268435456", *options, "-show_entries", "format=format_name,duration:stream=codec_type,codec_name,profile,pix_fmt,width,height,sample_aspect_ratio,avg_frame_rate,sample_rate,channels:stream_side_data=rotation", "-of", "json", str(snapshot)], timeout=self.timeout, output_limit=self.output_limit)
                duration, streams, containers = _parse_probe_document(payload)
                violations = _violations(duration, streams, policy)
                if violations:
                    return MediaReport(asset.sha256_hex, duration, streams, False, violations, container_names=containers)
                progress = _run([self.ffmpeg, "-nostdin", "-max_alloc", "268435456", "-progress", "pipe:1", "-nostats", "-v", "error", "-xerror", "-err_detect", "explode", "-threads", "1", *options, "-i", str(snapshot), "-map", "0:v?", "-map", "0:a?", "-threads", "1", "-f", "null", "-"], timeout=self.timeout, output_limit=self.output_limit)
                values = dict(line.split("=", 1) for line in progress.decode("ascii", errors="replace").splitlines() if "=" in line)
                try:
                    decoded_duration = int(values.get("out_time_us", "0")) / 1_000_000
                    if values.get("progress") != "end" or not math.isfinite(decoded_duration) or decoded_duration <= 0:
                        raise ValueError("no decoded media")
                    if any(s.kind == "video" for s in streams) and int(values.get("frame", "0")) <= 0:
                        raise ValueError("no decoded frames")
                except ValueError as exc:
                    raise MediaProbeError("MEDIA_DECODE_EMPTY") from exc
        except MediaProbeError:
            raise
        except OSError as exc:
            raise MediaProbeError("MEDIA_FILE_UNAVAILABLE") from exc
        decoded_violations = []
        if abs(decoded_duration - duration) > policy.duration_tolerance_seconds:
            decoded_violations.append("DECODE_DURATION_MISMATCH")
        if policy.expected_duration_seconds is not None and abs(decoded_duration - policy.expected_duration_seconds) > policy.duration_tolerance_seconds:
            decoded_violations.append("DECODE_EXPECTED_DURATION_MISMATCH")
        return MediaReport(
            asset.sha256_hex, duration, streams, True, tuple(decoded_violations),
            decoded_duration, containers,
        )
