from __future__ import annotations

import io
import time
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.audio_processor import TranscriptionResult
from app.main import create_app


def valid_wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)
    return buffer.getvalue()


def fake_transcribe(input_path: Path, working_dir: Path, results_dir: Path, model_name: str, language: str, stage_callback=None, **kwargs) -> TranscriptionResult:
    if stage_callback is not None:
        stage_callback("TRANSCRIBING")
    working_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    normalized = working_dir / "normalized.wav"
    normalized.write_bytes(b"normalized")
    transcript_path = results_dir / "transcript.json"
    segments = [{"id": "segment-0001", "speaker": "SPEAKER_00", "start_ms": 0, "end_ms": 1200, "text": "测试转录"}]
    transcript_path.write_text('{"segments": []}', encoding="utf-8")
    return TranscriptionResult(normalized, transcript_path, 1200, segments, model_name, "cpu", "int8", language, None)


def wait_for_stage(client: TestClient, job_id: str, stage: str, timeout: float = 5) -> dict:
    deadline = time.time() + timeout
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    while job["stage"] != stage and time.time() < deadline:
        time.sleep(0.03)
        job = client.get(f"/api/v1/jobs/{job_id}").json()
    return job


def test_create_meeting_runs_transcription_boundary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(main, "transcribe_audio", fake_transcribe)
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/meetings",
            files={"file": ("sample.wav", valid_wav_bytes(), "audio/wav")},
            data={"data_processing_confirmed": "true", "title": "阶段二验证会议", "meeting_started_at": "2026-09-08T10:00:00+08:00", "participants": '["张三", "李四"]', "context": "验证真实处理边界。"},
        )
        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "QUEUED"
        job = wait_for_stage(client, payload["job_id"], "SUCCEEDED")
        assert job["progress"] == 100
        meeting = client.get(f"/api/v1/meetings/{payload['meeting_id']}").json()
        assert meeting["duration_ms"] == 1200
        assert meeting["transcript"][0]["text"] == "测试转录"
        assert meeting["status"] == "SUCCEEDED_WITH_WARNINGS"
        assert meeting["job"]["diarization_status"] == "DEGRADED"
        assert meeting["job"]["speaker_count"] == 1
        assert "说话人分离未完成" in meeting["job"]["warning"]
    assert len(list((tmp_path / "runtime" / "meetings").glob("*/source/original.wav"))) == 1
    assert len(list((tmp_path / "runtime" / "meetings").glob("*/working/normalized.wav"))) == 1
    assert len(list((tmp_path / "runtime" / "meetings").glob("*/results/transcript.json"))) == 1


def test_requires_recording_processing_confirmation(tmp_path: Path) -> None:
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/meetings",
            files={"file": ("sample.wav", valid_wav_bytes(), "audio/wav")},
            data={"title": "未确认隐私边界"},
        )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "DATA_PROCESSING_CONFIRMATION_REQUIRED"
    assert not list((tmp_path / "runtime" / "meetings").glob("*/source/original.wav"))


def test_rejects_unsupported_extension(tmp_path: Path) -> None:
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        response = client.post("/api/v1/meetings", files={"file": ("notes.txt", b"not audio", "text/plain")}, data={"data_processing_confirmed": "true", "title": "非法文件"})
    assert response.status_code == 415


def test_health_endpoints(tmp_path: Path) -> None:
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["phase"] == "phase-8"
        assert client.get("/api/v1/health/ready").json()["status"] == "ready"




def test_allows_configured_frontend_origin(tmp_path: Path) -> None:
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/meetings",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_configured_upload_limit_is_enforced(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "upload-limit.env"
    env_file.write_text("MAX_UPLOAD_SIZE_MB=1\n", encoding="utf-8")
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(env_file))
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/meetings",
            files={"file": ("too-large.wav", b"0" * (1024 * 1024 + 1), "audio/wav")},
            data={"data_processing_confirmed": "true", "title": "上传上限验证"},
        )
    assert response.status_code == 413
    assert "1 MB" in response.json()["detail"]
    assert not list((tmp_path / "runtime" / "meetings").glob("*/source/original.wav"))


def test_accepts_browser_m4a_mime_type(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(main, "transcribe_audio", fake_transcribe)
    app = create_app(tmp_path / "runtime")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/meetings",
            files={"file": ("sample.m4a", valid_wav_bytes(), "audio/x-m4a")},
            data={"data_processing_confirmed": "true", "title": "M4A MIME 验证"},
        )
        assert response.status_code == 202
        payload = response.json()
        job = wait_for_stage(client, payload["job_id"], "SUCCEEDED")
        assert job["stage"] == "SUCCEEDED"
