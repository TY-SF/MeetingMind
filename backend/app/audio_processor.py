from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable


class AudioProcessingError(RuntimeError):
    """Raised when audio validation, normalization, or transcription cannot complete."""

    def __init__(self, message: str, *, code: str = "AUDIO_PROCESSING_FAILED") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AudioProbeResult:
    duration_ms: int
    format_name: str
    codec_name: str | None


class SpeakerDiarizationError(RuntimeError):
    """Raised when optional speaker diarization cannot complete."""


@dataclass(frozen=True)
class TranscriptionResult:
    normalized_audio: Path
    transcript_path: Path
    duration_ms: int
    segments: list[dict]
    model: str
    device: str
    compute_type: str
    language: str | None
    ffmpeg_bin: str | None
    diarization_applied: bool = False
    diarization_warning: str | None = None
    speaker_count: int = 1


def find_ffmpeg_bin() -> Path | None:
    configured = os.environ.get("MEETINGMIND_FFMPEG_BIN")
    if configured:
        path = Path(configured)
        if (path / "ffmpeg.exe").exists() and (path / "ffprobe.exe").exists():
            return path
    if os.name == "nt":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        candidates = sorted(
            local_app_data.glob("Microsoft/WinGet/Packages/BtbN.FFmpeg.GPL.Shared.7.1_*/ffmpeg-*/bin"),
            reverse=True,
        )
        for path in candidates:
            if (path / "ffmpeg.exe").exists() and (path / "ffprobe.exe").exists():
                return path
    ffmpeg = shutil.which("ffmpeg")
    return Path(ffmpeg).parent if ffmpeg else None


def configure_runtime(ffmpeg_bin: Path | None) -> None:
    if ffmpeg_bin is None:
        return
    if os.name == "nt":
        for directory in (
            ffmpeg_bin,
            Path(sys.prefix) / "Lib/site-packages/torch/lib",
            Path(sys.prefix) / "Lib/site-packages/torchcodec",
        ):
            if directory.exists():
                os.add_dll_directory(str(directory))
    os.environ["PATH"] = str(ffmpeg_bin) + os.pathsep + os.environ.get("PATH", "")


def _executable(ffmpeg_bin: Path | None, name: str) -> str:
    filename = f"{name}.exe" if os.name == "nt" else name
    return str(ffmpeg_bin / filename) if ffmpeg_bin else name


def probe_audio(input_path: Path, ffmpeg_bin: Path | None) -> AudioProbeResult:
    """Validate a real audio stream before a meeting record is accepted.

    Extension and browser-supplied MIME values are only hints. ffprobe is the
    authoritative boundary: it must find at least one audio stream and a usable
    duration before we create a durable job.
    """
    try:
        result = subprocess.run(
            [
                _executable(ffmpeg_bin, "ffprobe"), "-v", "error",
                "-show_entries", "format=format_name,duration:stream=codec_type,codec_name,duration",
                "-of", "json", str(input_path),
            ],
            check=True, capture_output=True, text=True,
        )
        payload = json.loads(result.stdout or "{}")
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise AudioProcessingError("文件不是可读取的音频媒体", code="INVALID_AUDIO") from exc

    streams = payload.get("streams") if isinstance(payload, dict) else None
    audio_streams = [stream for stream in (streams or []) if isinstance(stream, dict) and stream.get("codec_type") == "audio"]
    if not audio_streams:
        raise AudioProcessingError("文件中未检测到音频流", code="NO_AUDIO_STREAM")
    format_info = payload.get("format") if isinstance(payload, dict) else {}
    raw_duration = (format_info or {}).get("duration") or audio_streams[0].get("duration")
    try:
        duration_ms = round(float(raw_duration) * 1000)
    except (TypeError, ValueError) as exc:
        raise AudioProcessingError("音频缺少可用时长信息", code="INVALID_AUDIO") from exc
    if duration_ms <= 0:
        raise AudioProcessingError("音频时长必须大于 0", code="INVALID_AUDIO")
    return AudioProbeResult(
        duration_ms=duration_ms,
        format_name=str((format_info or {}).get("format_name") or "unknown"),
        codec_name=str(audio_streams[0].get("codec_name")) if audio_streams[0].get("codec_name") else None,
    )


def validate_audio_file(input_path: Path, *, max_audio_duration_minutes: int | None = None) -> AudioProbeResult:
    ffmpeg_bin = find_ffmpeg_bin()
    probe = probe_audio(input_path, ffmpeg_bin)
    if max_audio_duration_minutes is not None and probe.duration_ms > max_audio_duration_minutes * 60 * 1000:
        raise AudioProcessingError(
            f"音频时长不能超过 {max_audio_duration_minutes} 分钟",
            code="AUDIO_TOO_LONG",
        )
    return probe


def probe_duration(input_path: Path, ffmpeg_bin: Path | None) -> int:
    try:
        result = subprocess.run(
            [
                _executable(ffmpeg_bin, "ffprobe"),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(input_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return max(0, round(float(result.stdout.strip()) * 1000))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise AudioProcessingError(f"无法读取音频时长: {detail[-500:]}", code="INVALID_AUDIO") from exc


def normalize_audio(input_path: Path, normalized_path: Path, ffmpeg_bin: Path | None) -> int:
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                _executable(ffmpeg_bin, "ffmpeg"),
                "-y",
                "-i",
                str(input_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(normalized_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise AudioProcessingError(f"FFmpeg 音频规范化失败: {detail[-1000:]}", code="AUDIO_NORMALIZATION_FAILED") from exc
    return probe_duration(normalized_path, ffmpeg_bin)


def apply_speaker_diarization(
    normalized_path: Path,
    transcript_result: dict,
    *,
    hf_token: str,
    device: str,
    model_name: str = "pyannote/speaker-diarization-community-1",
    num_speakers: int | None = None,
) -> tuple[dict, int]:
    """Assign stable speaker labels to WhisperX segments using local pyannote inference."""
    if not hf_token:
        raise SpeakerDiarizationError("未配置 HF_TOKEN")
    try:
        import whisperx
        from whisperx.diarize import DiarizationPipeline

        pipeline = DiarizationPipeline(model_name=model_name, token=hf_token, device=device)
        diarize_df = pipeline(str(normalized_path), num_speakers=num_speakers)
        assigned = whisperx.assign_word_speakers(diarize_df, transcript_result, fill_nearest=True)
    except Exception as exc:
        message = str(exc).strip()
        if any(value in message.lower() for value in ("401", "403", "gated", "unauthorized", "forbidden")):
            detail = "Hugging Face 令牌无权访问说话人分离模型"
        else:
            detail = message[-500:] or type(exc).__name__
        raise SpeakerDiarizationError(f"说话人分离失败: {detail}") from exc

    segments = assigned.get("segments", []) if isinstance(assigned, dict) else []
    labels = list(dict.fromkeys(str(segment.get("speaker")) for segment in segments if segment.get("speaker")))
    if not labels:
        raise SpeakerDiarizationError("说话人分离未返回可用的说话人标签")
    stable_labels = {label: f"SPEAKER_{index:02d}" for index, label in enumerate(labels)}
    for segment in segments:
        speaker = segment.get("speaker")
        segment["speaker"] = stable_labels.get(str(speaker), "SPEAKER_00") if speaker else "SPEAKER_00"
        for word in segment.get("words", []):
            word_speaker = word.get("speaker")
            if word_speaker:
                word["speaker"] = stable_labels.get(str(word_speaker), "SPEAKER_00")
    return assigned, len(stable_labels)


def transcribe_audio(
    input_path: Path,
    working_dir: Path,
    results_dir: Path,
    model_name: str = "small",
    language: str = "zh",
    batch_size: int = 8,
    stage_callback: Callable[[str], None] | None = None,
    *,
    diarization_enabled: bool = True,
    hf_token: str | None = None,
    diarization_model: str = "pyannote/speaker-diarization-community-1",
    num_speakers: int | None = None,
    max_audio_duration_minutes: int | None = None,
) -> TranscriptionResult:
    """Normalize and transcribe one file with the already validated WhisperX chain."""
    ffmpeg_bin = find_ffmpeg_bin()
    configure_runtime(ffmpeg_bin)
    try:
        import torch
        import whisperx
    except ImportError as exc:
        raise AudioProcessingError("当前虚拟环境未安装 torch 或 whisperx") from exc

    normalized_path = working_dir / "normalized.wav"
    transcript_path = results_dir / "transcript.json"
    duration_ms = normalize_audio(input_path, normalized_path, ffmpeg_bin)
    if max_audio_duration_minutes is not None and duration_ms > max_audio_duration_minutes * 60 * 1000:
        raise AudioProcessingError(f"音频时长不能超过 {max_audio_duration_minutes} 分钟", code="AUDIO_TOO_LONG")
    if stage_callback is not None:
        stage_callback("TRANSCRIBING")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    try:
        audio = whisperx.load_audio(str(normalized_path))
        model = whisperx.load_model(model_name, device=device, compute_type=compute_type, language=language)
        result = model.transcribe(audio, batch_size=batch_size, language=language)
    except Exception as exc:
        raise AudioProcessingError(f"WhisperX 转录失败: {exc}") from exc

    # WhisperX alignment refines word/segment timing and is required before
    # assigning diarization labels. If a language alignment model is unavailable,
    # retain the original transcript rather than losing a successful ASR result.
    try:
        if stage_callback is not None:
            stage_callback("ALIGNING")
        align_model, align_metadata = whisperx.load_align_model(language_code=result.get("language") or language, device=device)
        result = whisperx.align(
            result.get("segments", []), align_model, align_metadata, audio, device,
            return_char_alignments=False,
        )
    except Exception as exc:
        raise AudioProcessingError(f"WhisperX 时间对齐失败: {exc}", code="WHISPERX_ALIGNMENT_FAILED") from exc

    diarization_applied = False
    diarization_warning = None
    speaker_count = 1
    if diarization_enabled:
        if stage_callback is not None:
            stage_callback("DIARIZING")
        if not hf_token:
            diarization_warning = "未配置 HF_TOKEN，已保留转录并使用默认说话人标签"
        else:
            try:
                result, speaker_count = apply_speaker_diarization(
                    normalized_path,
                    result,
                    hf_token=hf_token,
                    device=device,
                    model_name=diarization_model,
                    num_speakers=num_speakers,
                )
                diarization_applied = True
            except SpeakerDiarizationError as exc:
                diarization_warning = str(exc)

    segments = []
    for index, segment in enumerate(result.get("segments", []), start=1):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        segments.append(
            {
                "id": f"segment-{index:04d}",
                "speaker": str(segment.get("speaker") or "SPEAKER_00"),
                "start_ms": max(0, round(float(segment.get("start", 0)) * 1000)),
                "end_ms": max(0, round(float(segment.get("end", 0)) * 1000)),
                "text": text,
            }
        )

    payload = {
        "input": str(input_path),
        "normalized_audio": str(normalized_path),
        "model": model_name,
        "device": device,
        "compute_type": compute_type,
        "language": result.get("language") or language,
        "duration_ms": duration_ms,
        "diarization_applied": diarization_applied,
        "diarization_warning": diarization_warning,
        "speaker_count": speaker_count,
        "segments": segments,
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return TranscriptionResult(
        normalized_audio=normalized_path,
        transcript_path=transcript_path,
        duration_ms=duration_ms,
        segments=segments,
        model=model_name,
        device=device,
        compute_type=compute_type,
        language=result.get("language") or language,
        ffmpeg_bin=str(ffmpeg_bin) if ffmpeg_bin else None,
        diarization_applied=diarization_applied,
        diarization_warning=diarization_warning,
        speaker_count=speaker_count,
    )
