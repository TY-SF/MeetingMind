from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from datetime import datetime, timezone


class MeetingDeletionError(RuntimeError):
    """The database row was intentionally retained because local files were not removed."""


from sqlalchemy import text

from ..store import JsonStore
from .database import Base, create_db_engine, create_session_factory
from .models import MeetingRecord
from .repository import OptimisticLockError, SqlAlchemyMeetingRepository, parse_datetime


class SqlAlchemyStore(JsonStore):
    """Meeting persistence backed by SQLAlchemy, with the existing file layout."""

    def __init__(self, data_dir: Path, database_url: str, create_schema: bool = False) -> None:
        super().__init__(data_dir)
        self.engine = create_db_engine(database_url)
        self.session_factory = create_session_factory(self.engine)
        if create_schema:
            Base.metadata.create_all(self.engine)

    def list_meetings(self) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            return SqlAlchemyMeetingRepository(session).list_meetings()

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            return SqlAlchemyMeetingRepository(session).get_meeting(meeting_id)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            return SqlAlchemyMeetingRepository(session).get_job(job_id)

    def mark_job_failed_from_queue(self, job_id: str, error: str, error_code: str) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.session_factory.begin() as session:
            return SqlAlchemyMeetingRepository(session).mark_job_failed_from_queue(job_id, error, error_code, now)

    def save_meeting(self, meeting: dict[str, Any]) -> None:
        with self.session_factory.begin() as session:
            repository = SqlAlchemyMeetingRepository(session)
            repository.save_meeting(meeting)
            if "transcript" in meeting:
                repository.replace_transcript(
                    meeting["id"],
                    meeting["transcript"],
                    parse_datetime(meeting.get("updated_at")),
                )

    def delete_meeting(self, meeting_id: str) -> bool:
        # Delete files first. Returning success after silently retaining a recording
        # violates the privacy contract, so any cleanup failure aborts the operation
        # and leaves the database record available for a later retry.
        with self.session_factory() as session:
            exists = session.get(MeetingRecord, meeting_id) is not None
        if not exists:
            return False
        meeting_path = self.meetings_dir / meeting_id
        try:
            if meeting_path.exists():
                shutil.rmtree(meeting_path)
        except OSError as exc:
            raise MeetingDeletionError("本地会议文件删除失败；数据库记录已保留，请重试") from exc
        with self.session_factory.begin() as session:
            return SqlAlchemyMeetingRepository(session).delete_meeting(meeting_id)

    def retry_job(self, job_id: str) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.session_factory.begin() as session:
            return SqlAlchemyMeetingRepository(session).retry_job(job_id, now)

    def get_analysis(self, meeting_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            return SqlAlchemyMeetingRepository(session).get_analysis(meeting_id)

    def get_analysis_raw_result(self, meeting_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            return SqlAlchemyMeetingRepository(session).get_analysis_raw_result(meeting_id)

    def save_analysis(self, meeting_id: str, analysis: dict[str, Any], **metadata: Any) -> dict[str, Any]:
        with self.session_factory.begin() as session:
            return SqlAlchemyMeetingRepository(session).save_analysis(meeting_id, analysis, **metadata)


    def update_speaker_names(self, meeting_id: str, mappings: dict[str, str]) -> int:
        with self.session_factory.begin() as session:
            return SqlAlchemyMeetingRepository(session).update_speaker_names(meeting_id, mappings)

    def check_ready(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def close(self) -> None:
        self.engine.dispose()
