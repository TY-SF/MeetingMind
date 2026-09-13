from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.audio_processor import TranscriptionResult
from app.main import create_app


def interrupted_meeting(meeting_id: str = "meeting-recovery") -> dict:
    now = "2026-09-09T10:00:00+00:00"
    return {
        "id": meeting_id,
        "title": "中断恢复验证会议",
        "original_filename": "recovery.wav",
        "stored_filename": f"{meeting_id}/source/original.wav",
        "mime_type": "audio/wav",
        "file_size": 128,
        "duration_ms": 0,
        "meeting_started_at": now,
        "participants": [],
        "context": "",
        "status": "PROCESSING",
        "created_at": now,
        "updated_at": now,
        "transcript": [],
        "analysis": None,
        "job": {
            "id": f"job-{meeting_id}",
            "stage": "TRANSCRIBING",
            "progress": 48,
            "message": "服务中断前正在转录",
            "error": None,
            "error_code": None,
            "warning": None,
            "retry_count": 0,
            "updated_at": now,
        },
    }


def fake_transcribe(
    input_path: Path,
    working_dir: Path,
    results_dir: Path,
    model_name: str,
    language: str,
    stage_callback=None,
    **kwargs,
) -> TranscriptionResult:
    if stage_callback is not None:
        stage_callback("TRANSCRIBING")
    normalized = working_dir / "normalized.wav"
    transcript_path = results_dir / "transcript.json"
    normalized.write_bytes(b"normalized")
    transcript_path.write_text('{"segments": []}', encoding="utf-8")
    segments = [{
        "id": "segment-recovered",
        "speaker": "SPEAKER_00",
        "start_ms": 0,
        "end_ms": 1000,
        "text": "恢复后的转录",
    }]
    return TranscriptionResult(normalized, transcript_path, 1000, segments, model_name, "cpu", "int8", language, None)


def wait_until_terminal(client: TestClient, job_id: str, timeout: float = 5) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["stage"] in {"SUCCEEDED", "FAILED"}:
            return job
        time.sleep(0.03)
    return client.get(f"/api/v1/jobs/{job_id}").json()


def test_startup_recovers_interrupted_audio_job_from_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(main, "transcribe_audio", fake_transcribe)
    app = create_app(tmp_path / "runtime")
    meeting = interrupted_meeting()
    app.state.store.save_meeting(meeting)
    source = app.state.store.source_path(meeting["id"], ".wav")
    source.write_bytes(b"RIFF-recoverable")

    with TestClient(app) as client:
        job = wait_until_terminal(client, meeting["job"]["id"])
        assert job["stage"] == "SUCCEEDED"
        assert job["retry_count"] == 1
        assert "服务启动时自动恢复" in job["warning"]
        restored = client.get(f"/api/v1/meetings/{meeting['id']}").json()
        assert restored["transcript"][0]["text"] == "恢复后的转录"


def test_startup_marks_interrupted_job_failed_when_source_is_missing(tmp_path: Path) -> None:
    app = create_app(tmp_path / "runtime")
    meeting = interrupted_meeting("meeting-missing-source")
    app.state.store.save_meeting(meeting)

    with TestClient(app) as client:
        job = client.get(f"/api/v1/jobs/{meeting['job']['id']}").json()
        assert job["stage"] == "FAILED"
        assert job["error_code"] == "SOURCE_FILE_MISSING"
        assert "原始音频文件不存在" in job["error"]
