from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import URL


def load_env_file(path: Path) -> dict[str, str]:
    """Load simple KEY=VALUE pairs without printing or logging secrets."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_value(name: str, file_values: dict[str, str], default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is not None and value != "":
        return value
    value = file_values.get(name)
    return value if value not in (None, "") else default


def env_bool(name: str, file_values: dict[str, str], default: bool = False) -> bool:
    value = env_value(name, file_values)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_database_url(file_values: dict[str, str], data_dir: Path) -> str:
    explicit = env_value("MEETINGMIND_DATABASE_URL", file_values)
    if explicit and "请填写" not in explicit:
        return explicit
    mysql_database = env_value("MYSQL_DATABASE", file_values)
    mysql_user = env_value("MYSQL_USER", file_values)
    mysql_password = env_value("MYSQL_PASSWORD", file_values)
    placeholders = ("请填写", "change-me", "your-")
    if mysql_database and mysql_user and mysql_password and not any(
        marker in value.lower() for value in (mysql_database, mysql_user, mysql_password) for marker in placeholders
    ):
        return URL.create(
            "mysql+pymysql",
            username=mysql_user,
            password=mysql_password,
            host=env_value("MYSQL_HOST", file_values, "127.0.0.1"),
            port=int(env_value("MYSQL_PORT", file_values, "3306") or "3306"),
            database=mysql_database,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)
    return f"sqlite:///{data_dir / 'runtime' / 'meetingmind.db'}"


@dataclass(frozen=True)
class Settings:
    """Runtime configuration. No database connection is opened during construction."""

    database_url: str
    data_dir: Path
    max_upload_size_mb: int
    max_audio_duration_minutes: int
    llm_api_key: str | None
    llm_base_url: str | None
    llm_model: str
    llm_timeout_seconds: float
    llm_max_input_chars: int
    hf_token: str | None
    diarization_enabled: bool
    diarization_model: str
    frontend_origin: str
    redis_url: str
    rq_queue_name: str
    rq_job_timeout_seconds: int
    rq_result_ttl_seconds: int
    rq_failure_ttl_seconds: int
    rq_stale_job_seconds: int
    rq_reconciliation_interval_seconds: int
    queue_backend: str
    log_level: str

    @classmethod
    def from_env(cls, base_dir: Path | None = None) -> "Settings":
        root = base_dir or Path(__file__).parents[1]
        env_file = Path(os.getenv("MEETINGMIND_ENV_FILE", root / ".env" / "meetingmind.env"))
        file_values = load_env_file(env_file)
        # Allow local Docker credentials to live in the ignored compose file.
        infra_file_value = env_value("MEETINGMIND_INFRA_ENV_FILE", file_values)
        if infra_file_value:
            infra_file = Path(infra_file_value)
            if not infra_file.is_absolute():
                infra_file = root.parent / infra_file
            infra_values = load_env_file(infra_file)
            mysql_values = {key: value for key, value in infra_values.items() if key.startswith("MYSQL_")}
            if mysql_values:
                file_values.update(mysql_values)
                # Selecting an infrastructure file must replace a legacy URL from
                # the backend env file. A process-level URL still wins via env_value.
                file_values["MEETINGMIND_DATABASE_URL"] = ""
            redis_port = infra_values.get("REDIS_PORT")
            if redis_port:
                # Docker Compose publishes Redis on the local host. Preserve an
                # explicit process REDIS_URL, but replace a stale backend-file URL.
                file_values["REDIS_URL"] = f"redis://127.0.0.1:{redis_port}/0"
        data_dir_value = env_value("MEETINGMIND_DATA_DIR", file_values) or env_value("DATA_DIR", file_values)
        if data_dir_value:
            configured_data_dir = Path(data_dir_value)
            data_dir = configured_data_dir if configured_data_dir.is_absolute() else root.parent / configured_data_dir
        else:
            data_dir = root / "data"
        return cls(
            database_url=resolve_database_url(file_values, data_dir),
            data_dir=data_dir,
            max_upload_size_mb=int(env_value("MAX_UPLOAD_SIZE_MB", file_values, "200") or "200"),
            max_audio_duration_minutes=int(env_value("MAX_AUDIO_DURATION_MINUTES", file_values, "60") or "60"),
            llm_api_key=env_value("OPENAI_API_KEY", file_values) or env_value("LLM_API_KEY", file_values),
            llm_base_url=env_value("LLM_BASE_URL", file_values),
            llm_model=env_value("LLM_MODEL", file_values, "gpt-5.6-terra") or "gpt-5.6-terra",
            llm_timeout_seconds=float(env_value("LLM_TIMEOUT_SECONDS", file_values, "120") or "120"),
            llm_max_input_chars=int(env_value("LLM_MAX_INPUT_CHARS", file_values, "120000") or "120000"),
            hf_token=env_value("HF_TOKEN", file_values),
            diarization_enabled=env_bool("MEETINGMIND_DIARIZATION_ENABLED", file_values, True),
            diarization_model=env_value(
                "MEETINGMIND_DIARIZATION_MODEL", file_values, "pyannote/speaker-diarization-community-1"
            ) or "pyannote/speaker-diarization-community-1",
            frontend_origin=env_value("FRONTEND_ORIGIN", file_values, "http://localhost:5173") or "http://localhost:5173",
            redis_url=env_value("REDIS_URL", file_values, "redis://127.0.0.1:6379/0") or "redis://127.0.0.1:6379/0",
            rq_queue_name=env_value("RQ_QUEUE_NAME", file_values, "meetingmind") or "meetingmind",
            rq_job_timeout_seconds=int(env_value("RQ_JOB_TIMEOUT_SECONDS", file_values, "7200") or "7200"),
            rq_result_ttl_seconds=int(env_value("RQ_RESULT_TTL_SECONDS", file_values, "86400") or "86400"),
            rq_failure_ttl_seconds=int(env_value("RQ_FAILURE_TTL_SECONDS", file_values, "604800") or "604800"),
            rq_stale_job_seconds=int(env_value("RQ_STALE_JOB_SECONDS", file_values, "300") or "300"),
            rq_reconciliation_interval_seconds=int(
                env_value("RQ_RECONCILIATION_INTERVAL_SECONDS", file_values, "30") or "30"
            ),
            # `inline` is deliberately opt-in for isolated tests and emergency local
            # debugging. Normal development and deployment use Redis + RQ.
            queue_backend=(env_value("MEETINGMIND_QUEUE_BACKEND", file_values, "rq") or "rq").strip().lower(),
            log_level=env_value("LOG_LEVEL", file_values, "INFO") or "INFO",
        )
