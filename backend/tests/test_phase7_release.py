# -*- coding: utf-8 -*-
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.audio_processor import AudioProbeResult
from app.config import Settings
from app.db.store import SqlAlchemyStore
from app.main import create_app
from app.queueing import QueueUnavailableError, enqueue_processing_job


def test_rq_dispatch_fails_closed_when_redis_is_unavailable(tmp_path: Path) -> None:
    settings = replace(
        Settings.from_env(),
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'meetingmind.db'}",
        queue_backend="rq",
        redis_url="redis://127.0.0.1:6399/0",
    )
    try:
        enqueue_processing_job(settings=settings, meeting_id="meeting-7", internal_job_id="job-7")
    except QueueUnavailableError as exc:
        assert "Redis/RQ 不可用" in str(exc)
    else:
        raise AssertionError("Redis unavailable must not be reported as a queued job")


def test_upload_returns_stable_503_and_persists_failed_job_when_queue_is_down(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEETINGMIND_QUEUE_BACKEND", "rq")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/0")
    monkeypatch.setattr(main, "validate_audio_file", lambda *_args, **_kwargs: AudioProbeResult(1000, "wav", "pcm_s16le"))
    database_url = f"sqlite:///{tmp_path / 'meetingmind.db'}"
    schema_store = SqlAlchemyStore(tmp_path, database_url, create_schema=True)
    schema_store.close()
    app = create_app(tmp_path, database_url=database_url)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/meetings",
            files={"file": ("queue-down.wav", b"not-used-by-preflight", "audio/wav")},
            data={"title": "队列不可用验收"},
        )
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["code"] == "QUEUE_UNAVAILABLE"
        meetings = client.get("/api/v1/meetings").json()
        assert len(meetings) == 1
        assert meetings[0]["status"] == "FAILED"
        assert meetings[0]["job"]["error_code"] == "QUEUE_UNAVAILABLE"
        assert meetings[0]["job"]["stage"] == "FAILED"
