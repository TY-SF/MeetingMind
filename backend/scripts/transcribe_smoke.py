from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_ffmpeg_bin() -> Path | None:
    configured = os.environ.get("MEETINGMIND_FFMPEG_BIN")
    if configured:
        path = Path(configured)
        if (path / "ffmpeg.exe").exists() and (path / "ffprobe.exe").exists():
            return path
    if os.name == "nt":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        candidates = sorted(local_app_data.glob("Microsoft/WinGet/Packages/BtbN.FFmpeg.GPL.Shared.7.1_*/ffmpeg-*/bin"), reverse=True)
        for path in candidates:
            if (path / "ffmpeg.exe").exists() and (path / "ffprobe.exe").exists():
                return path
    ffmpeg = shutil.which("ffmpeg")
    return Path(ffmpeg).parent if ffmpeg else None


def configure_runtime() -> Path | None:
    ffmpeg_bin = find_ffmpeg_bin()
    if ffmpeg_bin is None:
        return None
    if os.name == "nt":
        for directory in [ffmpeg_bin, Path(sys.prefix) / "Lib/site-packages/torch/lib", Path(sys.prefix) / "Lib/site-packages/torchcodec"]:
            if directory.exists():
                os.add_dll_directory(str(directory))
    os.environ["PATH"] = str(ffmpeg_bin) + os.pathsep + os.environ.get("PATH", "")
    return ffmpeg_bin


FFMPEG_BIN = configure_runtime()

import torch  # noqa: E402
import whisperx  # noqa: E402


def run_ffmpeg(input_path: Path, normalized_path: Path) -> None:
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    executable = str(FFMPEG_BIN / "ffmpeg.exe") if FFMPEG_BIN else "ffmpeg"
    subprocess.run([executable, "-y", "-i", str(input_path), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(normalized_path)], check=True, capture_output=True, text=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="MeetingMind FFmpeg + WhisperX smoke test")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("backend/data/smoke_results/transcript.json"))
    parser.add_argument("--model", default="tiny.en")
    parser.add_argument("--language", default="en")
    args = parser.parse_args()

    normalized_path = args.output.with_name("normalized.wav")
    run_ffmpeg(args.input, normalized_path)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    audio = whisperx.load_audio(str(normalized_path))
    model = whisperx.load_model(args.model, device=device, compute_type=compute_type, language=args.language)
    result = model.transcribe(audio, batch_size=8, language=args.language)
    payload = {"input": str(args.input), "normalized_audio": str(normalized_path), "ffmpeg_bin": str(FFMPEG_BIN) if FFMPEG_BIN else None, "model": args.model, "device": device, "compute_type": compute_type, "language": result.get("language"), "segments": result.get("segments", [])}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "ffmpeg_bin": str(FFMPEG_BIN) if FFMPEG_BIN else None, "device": device, "language": result.get("language"), "segment_count": len(payload["segments"]), "text": " ".join(segment.get("text", "").strip() for segment in payload["segments"]).strip()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
