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


def test_compose_env_overrides_legacy_backend_mysql_values(tmp_path, monkeypatch) -> None:
    from app.config import Settings

    project_root = tmp_path / "project"
    backend_root = project_root / "backend"
    backend_root.mkdir(parents=True)
    env_file = backend_root / ".env" / "meetingmind.env"
    env_file.parent.mkdir()
    env_file.write_text(
        "MEETINGMIND_DATABASE_URL=sqlite:///legacy-backend.db\n"
        "REDIS_URL=redis://127.0.0.1:6380/0\n"
        "MYSQL_HOST=127.0.0.1\n"
        "MYSQL_PORT=3306\n"
        "MYSQL_DATABASE=old_database\n"
        "MYSQL_USER=root\n"
        "MYSQL_PASSWORD=old-password\n"
        "MEETINGMIND_INFRA_ENV_FILE=.env.compose\n",
        encoding="utf-8",
    )
    (project_root / ".env.compose").write_text(
        "MYSQL_HOST=127.0.0.1\n"
        "MYSQL_PORT=3307\n"
        "MYSQL_DATABASE=meetingmind\n"
        "MYSQL_USER=meetingmind\n"
        "MYSQL_PASSWORD=compose-password\n"
        "REDIS_PORT=6379\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(env_file))
    for name in ("MEETINGMIND_DATABASE_URL", "MYSQL_HOST", "MYSQL_PORT", "MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env(base_dir=backend_root)

    assert "meetingmind:compose-password@127.0.0.1:3307/meetingmind" in settings.database_url
    assert "root" not in settings.database_url
    assert ":3306/" not in settings.database_url
    assert settings.redis_url == "redis://127.0.0.1:6379/0"


def test_process_environment_overrides_compose_mysql_values(tmp_path, monkeypatch) -> None:
    from app.config import Settings

    project_root = tmp_path / "project"
    backend_root = project_root / "backend"
    backend_root.mkdir(parents=True)
    env_file = backend_root / ".env" / "meetingmind.env"
    env_file.parent.mkdir()
    env_file.write_text("MEETINGMIND_INFRA_ENV_FILE=.env.compose\n", encoding="utf-8")
    (project_root / ".env.compose").write_text(
        "MYSQL_HOST=compose-host\n"
        "MYSQL_PORT=3307\n"
        "MYSQL_DATABASE=compose-db\n"
        "MYSQL_USER=compose-user\n"
        "MYSQL_PASSWORD=compose-password\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(env_file))
    monkeypatch.setenv("MYSQL_HOST", "process-host")
    monkeypatch.setenv("MYSQL_PORT", "3310")
    monkeypatch.setenv("MYSQL_DATABASE", "process-db")
    monkeypatch.setenv("MYSQL_USER", "process-user")
    monkeypatch.setenv("MYSQL_PASSWORD", "process-password")

    settings = Settings.from_env(base_dir=backend_root)

    assert "process-user:process-password@process-host:3310/process-db" in settings.database_url


def test_process_environment_can_select_infra_file_and_override_its_redis_url(tmp_path, monkeypatch) -> None:
    from app.config import Settings

    project_root = tmp_path / "project"
    backend_root = project_root / "backend"
    backend_root.mkdir(parents=True)
    env_file = backend_root / ".env" / "meetingmind.env"
    env_file.parent.mkdir()
    env_file.write_text(
        "MEETINGMIND_DATABASE_URL=sqlite:///legacy-process-selection.db\n"
        "REDIS_URL=redis://127.0.0.1:6380/0\n",
        encoding="utf-8",
    )
    infra_file = project_root / ".env.compose"
    infra_file.write_text(
        "MYSQL_HOST=127.0.0.1\n"
        "MYSQL_PORT=3307\n"
        "MYSQL_DATABASE=meetingmind\n"
        "MYSQL_USER=meetingmind\n"
        "MYSQL_PASSWORD=compose-password\n"
        "REDIS_PORT=6381\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(env_file))
    monkeypatch.setenv("MEETINGMIND_INFRA_ENV_FILE", str(infra_file))
    monkeypatch.setenv("REDIS_URL", "redis://process-host:6390/1")
    monkeypatch.delenv("MEETINGMIND_DATABASE_URL", raising=False)

    settings = Settings.from_env(base_dir=backend_root)

    assert "meetingmind:compose-password@127.0.0.1:3307/meetingmind" in settings.database_url
    assert settings.redis_url == "redis://process-host:6390/1"


def test_default_data_dir_uses_project_root(tmp_path, monkeypatch) -> None:
    from app.config import Settings

    project_root = tmp_path / "project"
    backend_root = project_root / "backend"
    backend_root.mkdir(parents=True)
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(project_root / "missing.env"))
    monkeypatch.delenv("MEETINGMIND_DATA_DIR", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)

    settings = Settings.from_env(base_dir=backend_root)

    assert settings.data_dir.resolve() == (project_root / "data").resolve()


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
