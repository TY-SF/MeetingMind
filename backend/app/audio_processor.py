from __future__ import annotations

import hashlib
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
    resumed_from_stage: str | None = None


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


CHECKPOINT_VERSION = 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value: object) -> object:
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        temporary.replace(path)
    except (OSError, TypeError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        raise AudioProcessingError(f"无法保存阶段检查点: {path.name}", code="STORAGE_ERROR") from exc


def _load_checkpoint(path: Path, *, stage: str, signature: dict) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("checkpoint_version") != CHECKPOINT_VERSION:
        return None
    if payload.get("stage") != stage or payload.get("signature") != signature:
        return None
    return payload


def _segments_from_result(result: dict) -> list[dict]:
    segments: list[dict] = []
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
    return segments


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
    resume: bool = False,
    source_sha256: str | None = None,
) -> TranscriptionResult:
    """Run the audio pipeline and resume from the latest valid stage checkpoint.

    Stage outputs are written atomically below ``working_dir``. A retry only reuses
    a checkpoint when its source hash and processing configuration match, so a
    corrupt, stale, or foreign artifact can never silently skip required work.
    """
    ffmpeg_bin = find_ffmpeg_bin()
    configure_runtime(ffmpeg_bin)

    working_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = working_dir / "normalized.wav"
    preprocessing_checkpoint = working_dir / "preprocessing.checkpoint.json"
    transcription_checkpoint = working_dir / "transcribing.checkpoint.json"
    alignment_checkpoint = working_dir / "aligning.checkpoint.json"
    transcript_path = results_dir / "transcript.json"

    signature = {
        "source_sha256": source_sha256 or _sha256_file(input_path),
        "model": model_name,
        "language": language,
        "diarization_enabled": diarization_enabled,
        "diarization_model": diarization_model if diarization_enabled else None,
        "num_speakers": num_speakers,
    }
    resumed_from_stage: str | None = None

    final_checkpoint = _load_checkpoint(transcript_path, stage="SUCCEEDED", signature=signature) if resume else None
    if final_checkpoint is not None:
        segments = final_checkpoint.get("segments")
        if isinstance(segments, list) and int(final_checkpoint.get("duration_ms") or 0) > 0:
            return TranscriptionResult(
                normalized_audio=normalized_path,
                transcript_path=transcript_path,
                duration_ms=int(final_checkpoint["duration_ms"]),
                segments=segments,
                model=str(final_checkpoint.get("model") or model_name),
                device=str(final_checkpoint.get("device") or "unknown"),
                compute_type=str(final_checkpoint.get("compute_type") or "unknown"),
                language=final_checkpoint.get("language") or language,
                ffmpeg_bin=str(ffmpeg_bin) if ffmpeg_bin else None,
                diarization_applied=bool(final_checkpoint.get("diarization_applied")),
                diarization_warning=final_checkpoint.get("diarization_warning"),
                speaker_count=int(final_checkpoint.get("speaker_count") or 1),
                resumed_from_stage="SUCCEEDED",
            )

    preprocessing = _load_checkpoint(preprocessing_checkpoint, stage="PREPROCESSING", signature=signature) if resume else None
    if preprocessing is not None and normalized_path.is_file():
        duration_ms = int(preprocessing.get("duration_ms") or 0)
        normalized_sha256 = str(preprocessing.get("normalized_sha256") or "")
        if duration_ms <= 0 or not normalized_sha256 or _sha256_file(normalized_path) != normalized_sha256:
            preprocessing = None
    if preprocessing is None:
        if stage_callback is not None:
            stage_callback("PREPROCESSING")
        duration_ms = normalize_audio(input_path, normalized_path, ffmpeg_bin)
        if max_audio_duration_minutes is not None and duration_ms > max_audio_duration_minutes * 60 * 1000:
            raise AudioProcessingError(f"音频时长不能超过 {max_audio_duration_minutes} 分钟", code="AUDIO_TOO_LONG")
        _write_json_atomic(
            preprocessing_checkpoint,
            {
                "checkpoint_version": CHECKPOINT_VERSION,
                "stage": "PREPROCESSING",
                "signature": signature,
                "duration_ms": duration_ms,
                "normalized_sha256": _sha256_file(normalized_path),
            },
        )
    else:
        resumed_from_stage = "TRANSCRIBING"

    try:
        import torch
        import whisperx
    except ImportError as exc:
        raise AudioProcessingError("当前虚拟环境未安装 torch 或 whisperx") from exc

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    audio = whisperx.load_audio(str(normalized_path))

    transcription = _load_checkpoint(transcription_checkpoint, stage="TRANSCRIBING", signature=signature) if resume else None
    result = transcription.get("result") if transcription is not None else None
    if not isinstance(result, dict):
        if stage_callback is not None:
            stage_callback("TRANSCRIBING")
        try:
            model = whisperx.load_model(model_name, device=device, compute_type=compute_type, language=language)
            result = model.transcribe(audio, batch_size=batch_size, language=language)
        except Exception as exc:
            raise AudioProcessingError(f"WhisperX 转录失败: {exc}") from exc
        _write_json_atomic(
            transcription_checkpoint,
            {
                "checkpoint_version": CHECKPOINT_VERSION,
                "stage": "TRANSCRIBING",
                "signature": signature,
                "result": result,
            },
        )
    elif resumed_from_stage is None or resumed_from_stage == "TRANSCRIBING":
        resumed_from_stage = "ALIGNING"

    alignment = _load_checkpoint(alignment_checkpoint, stage="ALIGNING", signature=signature) if resume else None
    aligned_result = alignment.get("result") if alignment is not None else None
    if not isinstance(aligned_result, dict):
        if stage_callback is not None:
            stage_callback("ALIGNING")
        try:
            align_model, align_metadata = whisperx.load_align_model(language_code=result.get("language") or language, device=device)
            aligned_result = whisperx.align(
                result.get("segments", []), align_model, align_metadata, audio, device,
                return_char_alignments=False,
            )
        except Exception as exc:
            raise AudioProcessingError(f"WhisperX 时间对齐失败: {exc}", code="WHISPERX_ALIGNMENT_FAILED") from exc
        _write_json_atomic(
            alignment_checkpoint,
            {
                "checkpoint_version": CHECKPOINT_VERSION,
                "stage": "ALIGNING",
                "signature": signature,
                "result": aligned_result,
            },
        )
    else:
        resumed_from_stage = "DIARIZING"
    result = aligned_result

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

    segments = _segments_from_result(result)
    payload = {
        "checkpoint_version": CHECKPOINT_VERSION,
        "stage": "SUCCEEDED",
        "signature": signature,
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
    _write_json_atomic(transcript_path, payload)
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
        resumed_from_stage=resumed_from_stage,
    )
