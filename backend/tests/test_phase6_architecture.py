from __future__ import annotations

import io
import time
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.audio_processor import AudioProcessingError, TranscriptionResult
from app.main import create_app, finish_failed_job
from app.db.store import MeetingDeletionError


def valid_wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)
    return buffer.getvalue()


def fake_transcribe(input_path: Path, working_dir: Path, results_dir: Path, model_name: str, language: str, stage_callback=None, **kwargs) -> TranscriptionResult:
    if stage_callback:
        stage_callback("TRANSCRIBING")
    working_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    normalized = working_dir / "normalized.wav"
    normalized.write_bytes(b"audio")
    transcript = results_dir / "transcript.json"
    transcript.write_text("{}", encoding="utf-8")
    return TranscriptionResult(normalized, transcript, 1000, [{"id": "s1", "speaker": "SPEAKER_00", "start_ms": 0, "end_ms": 1000, "text": "测试"}], model_name, "cpu", "int8", language, None)


def create_failed_meeting(client: TestClient, app, monkeypatch) -> dict:
    monkeypatch.setattr(main, "transcribe_audio", fake_transcribe)
    response = client.post("/api/v1/meetings", files={"file": ("valid.wav", valid_wav_bytes(), "audio/wav")}, data={"title": "可重试会议", "expected_speakers": "2"})
    assert response.status_code == 202
    payload = response.json()
    deadline = time.time() + 3
    while app.state.store.get_job(payload["job_id"])["stage"] != "SUCCEEDED" and time.time() < deadline:
        time.sleep(0.02)
    finish_failed_job(app.state.store, payload["meeting_id"], "模拟失败", error_code="SIMULATED_FAILURE")
    return payload


def test_upload_has_sha256_preflight_and_request_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "transcribe_audio", fake_transcribe)
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/meetings",
            files={"file": ("valid.wav", valid_wav_bytes(), "audio/wav")},
            data={"title": "媒体预检", "expected_speakers": "2"},
            headers={"X-Request-ID": "phase6-test-request"},
        )
        assert response.status_code == 202
        assert response.headers["x-request-id"] == "phase6-test-request"
        meeting = client.get(f"/api/v1/meetings/{response.json()['meeting_id']}").json()
    assert meeting["expected_speakers"] == 2
    assert len(app.state.store.get_meeting(meeting["id"])["sha256"]) == 64


def test_rejects_real_media_validation_failure_with_stable_code(tmp_path, monkeypatch) -> None:
    app = create_app(tmp_path / "runtime")
    monkeypatch.setattr(main, "validate_audio_file", lambda *_args, **_kwargs: (_ for _ in ()).throw(AudioProcessingError("无音频流", code="NO_AUDIO_STREAM")))
    with TestClient(app) as client:
        response = client.post("/api/v1/meetings", files={"file": ("invalid.wav", b"not audio", "audio/wav")}, data={"title": "无音频流"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "NO_AUDIO_STREAM"


def test_failed_job_can_retry_once_and_active_job_cannot_retry_again(tmp_path, monkeypatch) -> None:
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        payload = create_failed_meeting(client, app, monkeypatch)
        retry = client.post(f"/api/v1/jobs/{payload['job_id']}/retry")
        assert retry.status_code == 202
        assert retry.json()["retry_count"] == 1
        conflict = client.post(f"/api/v1/jobs/{payload['job_id']}/retry")
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "JOB_NOT_RETRYABLE"


def test_file_delete_failure_does_not_delete_database_record(tmp_path, monkeypatch) -> None:
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        payload = create_failed_meeting(client, app, monkeypatch)
        import app.db.store as store_module
        monkeypatch.setattr(store_module.shutil, "rmtree", lambda _path: (_ for _ in ()).throw(OSError("locked")))
        response = client.delete(f"/api/v1/meetings/{payload['meeting_id']}")
        assert response.status_code == 500
        assert response.json()["detail"]["code"] == "FILE_DELETE_FAILED"
        assert client.get(f"/api/v1/meetings/{payload['meeting_id']}").status_code == 200


def test_queue_health_reports_inline_test_backend_without_redis(tmp_path) -> None:
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        response = client.get("/api/v1/health/queue")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "disabled"
    assert payload["redis"] == "disabled"
    assert payload["worker_online"] is False


def test_queue_failure_reconciliation_closes_open_stage_and_makes_job_retryable(tmp_path, monkeypatch) -> None:
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        payload = create_failed_meeting(client, app, monkeypatch)
        meeting = app.state.store.get_meeting(payload["meeting_id"])
        assert meeting is not None
        meeting["status"] = "PROCESSING"
        meeting["job"].update({"stage": "QUEUED", "progress": 8, "message": "任务已进入队列", "error": None, "error_code": None})
        app.state.store.save_meeting(meeting)
        assert app.state.store.mark_job_failed_from_queue(payload["job_id"], "worker exited", "QUEUE_JOB_INTERRUPTED")
        failed = client.get(f"/api/v1/jobs/{payload['job_id']}").json()
        assert failed["stage"] == "FAILED"
        assert failed["error_code"] == "QUEUE_JOB_INTERRUPTED"
        assert failed["stage_events"][-1]["outcome"] == "INTERRUPTED"
