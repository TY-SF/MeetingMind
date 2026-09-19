from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from app import audio_processor
from app.audio_processor import AudioProcessingError, transcribe_audio


class _FakeModel:
    def __init__(self, calls: dict[str, int]) -> None:
        self.calls = calls

    def transcribe(self, audio, *, batch_size: int, language: str) -> dict:
        self.calls["transcribe"] += 1
        return {
            "language": language,
            "segments": [{"start": 0.0, "end": 1.0, "text": "检查点恢复"}],
        }


def test_retry_resumes_from_latest_valid_stage_checkpoint(tmp_path, monkeypatch) -> None:
    calls = {"normalize": 0, "transcribe": 0, "align": 0}
    source = tmp_path / "source.wav"
    source.write_bytes(b"immutable-source")
    working = tmp_path / "working"
    results = tmp_path / "results"

    def fake_normalize(input_path, normalized_path, ffmpeg_bin) -> int:
        calls["normalize"] += 1
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_path.write_bytes(b"normalized-audio")
        return 1_000

    def fake_load_align_model(*, language_code: str, device: str):
        return object(), {"language": language_code}

    def fake_align(segments, model, metadata, audio, device, *, return_char_alignments: bool):
        calls["align"] += 1
        if calls["align"] == 1:
            raise RuntimeError("simulated interruption during alignment")
        return {"language": "zh", "segments": segments}

    fake_whisperx = SimpleNamespace(
        load_audio=lambda path: {"path": path},
        load_model=lambda *args, **kwargs: _FakeModel(calls),
        load_align_model=fake_load_align_model,
        align=fake_align,
    )
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, "whisperx", fake_whisperx)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(audio_processor, "normalize_audio", fake_normalize)
    monkeypatch.setattr(audio_processor, "find_ffmpeg_bin", lambda: None)
    monkeypatch.setattr(audio_processor, "configure_runtime", lambda value: None)

    with pytest.raises(AudioProcessingError, match="时间对齐失败"):
        transcribe_audio(
            source,
            working,
            results,
            diarization_enabled=False,
            source_sha256="source-hash",
        )

    assert calls == {"normalize": 1, "transcribe": 1, "align": 1}
    raw_checkpoint = json.loads((working / "transcribing.checkpoint.json").read_text(encoding="utf-8"))
    assert raw_checkpoint["stage"] == "TRANSCRIBING"
    assert not (working / "aligning.checkpoint.json").exists()

    resumed = transcribe_audio(
        source,
        working,
        results,
        diarization_enabled=False,
        source_sha256="source-hash",
        resume=True,
    )

    assert calls == {"normalize": 1, "transcribe": 1, "align": 2}
    assert resumed.resumed_from_stage == "ALIGNING"
    assert resumed.segments[0]["text"] == "检查点恢复"
    assert (working / "aligning.checkpoint.json").exists()
    assert json.loads((results / "transcript.json").read_text(encoding="utf-8"))["stage"] == "SUCCEEDED"


def test_retry_rejects_checkpoint_from_different_source(tmp_path, monkeypatch) -> None:
    calls = {"normalize": 0, "transcribe": 0, "align": 0}
    source = tmp_path / "source.wav"
    source.write_bytes(b"immutable-source")
    working = tmp_path / "working"
    results = tmp_path / "results"

    def fake_normalize(input_path, normalized_path, ffmpeg_bin) -> int:
        calls["normalize"] += 1
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_path.write_bytes(b"normalized-audio")
        return 1_000

    fake_whisperx = SimpleNamespace(
        load_audio=lambda path: {"path": path},
        load_model=lambda *args, **kwargs: _FakeModel(calls),
        load_align_model=lambda **kwargs: (object(), {}),
        align=lambda segments, *args, **kwargs: calls.__setitem__("align", calls["align"] + 1) or {"language": "zh", "segments": segments},
    )
    monkeypatch.setitem(sys.modules, "whisperx", fake_whisperx)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setattr(audio_processor, "normalize_audio", fake_normalize)
    monkeypatch.setattr(audio_processor, "find_ffmpeg_bin", lambda: None)
    monkeypatch.setattr(audio_processor, "configure_runtime", lambda value: None)

    transcribe_audio(source, working, results, diarization_enabled=False, source_sha256="old-hash")
    transcribe_audio(source, working, results, diarization_enabled=False, source_sha256="new-hash", resume=True)

    assert calls == {"normalize": 2, "transcribe": 2, "align": 2}
