from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect

from app.db import Base, SqlAlchemyMeetingRepository, create_db_engine, create_session_factory


def sample_meeting() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": "meeting-db-1",
        "title": "数据库设计验证",
        "original_filename": "meeting.mp3",
        "mime_type": "audio/mpeg",
        "file_size": 1024,
        "duration_ms": 42121,
        "meeting_started_at": now,
        "participants": ["张三"],
        "context": "验证 SQL Repository",
        "status": "PROCESSING",
        "created_at": now,
        "updated_at": now,
        "job": {
            "id": "job-db-1",
            "stage": "QUEUED",
            "progress": 8,
            "error": None,
            "warning": None,
            "updated_at": now,
        },
    }


def test_schema_contains_six_domain_tables(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'meetingmind.db'}")
    Base.metadata.create_all(engine)
    assert set(inspect(engine).get_table_names()) == {
        "meetings", "processing_jobs", "processing_stage_events", "transcript_segments", "meeting_analyses", "decisions", "action_items"
    }


def test_repository_persists_meeting_job_and_replaces_transcript(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'meetingmind.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with sessions.begin() as session:
        repository = SqlAlchemyMeetingRepository(session)
        meeting = sample_meeting()
        repository.save_meeting(meeting)
        repository.replace_transcript("meeting-db-1", [{"speaker": "SPEAKER_00", "start_ms": 0, "end_ms": 1000, "text": "第一版"}], now)

    with sessions() as session:
        repository = SqlAlchemyMeetingRepository(session)
        saved = repository.get_meeting("meeting-db-1")
        assert saved is not None
        assert saved["participants"] == ["张三"]
        assert saved["duration_ms"] == 42121
        assert saved["transcript"][0]["text"] == "第一版"
        assert repository.get_job("job-db-1")["stage"] == "QUEUED"
        assert repository.delete_meeting("meeting-db-1") is True
        session.commit()




def test_env_template_allows_mysql_fields_to_take_effect(tmp_path, monkeypatch) -> None:
    from app.config import Settings

    env_file = tmp_path / "meetingmind.env"
    env_file.write_text(
        "MEETINGMIND_DATABASE_URL=\n"
        "MYSQL_HOST=db.local\n"
        "MYSQL_PORT=3307\n"
        "MYSQL_DATABASE=meetingmind\n"
        "MYSQL_USER=release_user\n"
        "MYSQL_PASSWORD=release_password\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(env_file))
    settings = Settings.from_env(base_dir=tmp_path)
    assert settings.database_url.startswith("mysql+pymysql://release_user:")
    assert "@db.local:3307/meetingmind" in settings.database_url


def test_relative_data_dir_is_stable_across_working_directories(tmp_path, monkeypatch) -> None:
    from app.config import Settings

    backend_root = tmp_path / "backend"
    backend_root.mkdir()
    env_file = tmp_path / "meetingmind.env"
    env_file.write_text("MEETINGMIND_DATA_DIR=data\n", encoding="utf-8")
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(env_file))

    first_cwd = tmp_path / "cwd-a"
    second_cwd = tmp_path / "cwd-b"
    first_cwd.mkdir()
    second_cwd.mkdir()
    monkeypatch.chdir(first_cwd)
    first = Settings.from_env(base_dir=backend_root).data_dir.resolve()
    monkeypatch.chdir(second_cwd)
    second = Settings.from_env(base_dir=backend_root).data_dir.resolve()

    assert first == second == (tmp_path / "data").resolve()
