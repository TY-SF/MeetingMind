from __future__ import annotations

import io
import sys
import wave
import time
import types
from pathlib import Path

from fastapi.testclient import TestClient

from app import audio_processor, main
from app.audio_processor import TranscriptionResult, apply_speaker_diarization
from app.main import create_app


def valid_wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)
    return buffer.getvalue()


def test_apply_speaker_diarization_normalizes_labels_by_first_appearance(tmp_path, monkeypatch) -> None:
    class FakePipeline:
        def __init__(self, **kwargs):
            assert kwargs["token"] == "test-token"

        def __call__(self, audio, num_speakers=None):
            assert audio.endswith("normalized.wav")
            return object()

    def fake_assign(_diarize_df, transcript, fill_nearest=False):
        assert fill_nearest is True
        return {
            **transcript,
            "segments": [
                {"speaker": "SPEAKER_B", "words": [{"speaker": "SPEAKER_B"}]},
                {"speaker": "SPEAKER_A", "words": [{"speaker": "SPEAKER_A"}]},
                {"speaker": "SPEAKER_B", "words": []},
            ],
        }

    fake_diarize = types.ModuleType("whisperx.diarize")
    fake_diarize.DiarizationPipeline = FakePipeline
    fake_whisperx = types.ModuleType("whisperx")
    fake_whisperx.assign_word_speakers = fake_assign
    monkeypatch.setitem(sys.modules, "whisperx", fake_whisperx)
    monkeypatch.setitem(sys.modules, "whisperx.diarize", fake_diarize)

    assigned, count = apply_speaker_diarization(
        tmp_path / "normalized.wav",
        {"segments": []},
        hf_token="test-token",
        device="cpu",
    )
    assert count == 2
    assert [segment["speaker"] for segment in assigned["segments"]] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]
    assert assigned["segments"][1]["words"][0]["speaker"] == "SPEAKER_01"


def _fake_success(input_path, working_dir, results_dir, model_name, language, stage_callback=None, **kwargs):
    stage_callback("TRANSCRIBING")
    stage_callback("DIARIZING")
    working_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    normalized = working_dir / "normalized.wav"
    transcript_path = results_dir / "transcript.json"
    normalized.write_bytes(b"audio")
    transcript_path.write_text("{}", encoding="utf-8")
    segments = [
        {"id": "s1", "speaker": "SPEAKER_00", "start_ms": 0, "end_ms": 500, "text": "甲"},
        {"id": "s2", "speaker": "SPEAKER_01", "start_ms": 500, "end_ms": 1000, "text": "乙"},
    ]
    return TranscriptionResult(normalized, transcript_path, 1000, segments, model_name, "cpu", "int8", language, None, True, None, 2)


def test_pipeline_persists_successful_diarization(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(tmp_path / "settings.env"))
    (tmp_path / "settings.env").write_text("HF_TOKEN=test-token\nMEETINGMIND_DIARIZATION_ENABLED=true\n", encoding="utf-8")
    monkeypatch.setattr(main, "transcribe_audio", _fake_success)
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/meetings",
            files={"file": ("sample.wav", valid_wav_bytes(), "audio/wav")},
            data={"title": "说话人分离测试"},
        ).json()
        deadline = time.time() + 5
        while time.time() < deadline:
            job = client.get(f"/api/v1/jobs/{created['job_id']}").json()
            if job["stage"] == "SUCCEEDED":
                break
            time.sleep(0.03)
    assert job["diarization_status"] == "SUCCEEDED"
    assert job["speaker_count"] == 2
    assert job["warning"] is None
    assert [event["stage"] for event in job["stage_events"]] == ["QUEUED", "PREPROCESSING", "TRANSCRIBING", "DIARIZING"]


def test_transcription_rejects_audio_over_configured_duration_before_model_load(tmp_path, monkeypatch) -> None:
    fake_torch = types.ModuleType("torch")
    fake_whisperx = types.ModuleType("whisperx")
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "whisperx", fake_whisperx)
    monkeypatch.setattr(audio_processor, "find_ffmpeg_bin", lambda: None)
    monkeypatch.setattr(audio_processor, "configure_runtime", lambda _path: None)
    monkeypatch.setattr(audio_processor, "normalize_audio", lambda *_args: 60_001)

    with __import__("pytest").raises(audio_processor.AudioProcessingError, match="不能超过 1 分钟"):
        audio_processor.transcribe_audio(
            tmp_path / "source.wav",
            tmp_path / "working",
            tmp_path / "results",
            max_audio_duration_minutes=1,
        )
