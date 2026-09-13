from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BIGINT, BigInteger, JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def uuid_string() -> str:
    return str(uuid.uuid4())


class MeetingRecord(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(BIGINT, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    meeting_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    participants_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    context: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expected_speakers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    jobs: Mapped[list["ProcessingJobRecord"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")
    transcript_segments: Mapped[list["TranscriptSegmentRecord"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")
    analysis: Mapped["MeetingAnalysisRecord | None"] = relationship(back_populates="meeting", cascade="all, delete-orphan", uselist=False)


class ProcessingJobRecord(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    rq_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    current_stage: Mapped[str] = mapped_column(String(40), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    diarization_status: Mapped[str] = mapped_column(String(20), nullable=False, default="NOT_RUN")
    speaker_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    meeting: Mapped[MeetingRecord] = relationship(back_populates="jobs")
    stage_events: Mapped[list["ProcessingStageEventRecord"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="ProcessingStageEventRecord.started_at"
    )

    __table_args__ = (Index("ix_processing_jobs_meeting_active", "meeting_id", "status"),)


class ProcessingStageEventRecord(Base):
    __tablename__ = "processing_stage_events"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")

    job: Mapped[ProcessingJobRecord] = relationship(back_populates="stage_events")

    __table_args__ = (Index("ix_stage_events_job_started", "job_id", "started_at"),)


class TranscriptSegmentRecord(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker_label: Mapped[str] = mapped_column(String(50), nullable=False)
    speaker_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_ms: Mapped[int] = mapped_column(BIGINT, nullable=False)
    end_ms: Mapped[int] = mapped_column(BIGINT, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    meeting: Mapped[MeetingRecord] = relationship(back_populates="transcript_segments")

    __table_args__ = (
        UniqueConstraint("meeting_id", "segment_index", name="uq_transcript_meeting_segment"),
        Index("ix_transcript_segments_meeting_start", "meeting_id", "start_ms"),
    )


class MeetingAnalysisRecord(Base):
    __tablename__ = "meeting_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, unique=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    ai_raw_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    meeting: Mapped[MeetingRecord] = relationship(back_populates="analysis")
    decisions: Mapped[list["DecisionRecord"]] = relationship(back_populates="analysis", cascade="all, delete-orphan")
    action_items: Mapped[list["ActionItemRecord"]] = relationship(back_populates="analysis", cascade="all, delete-orphan")


class DecisionRecord(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("meeting_analyses.id", ondelete="CASCADE"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    decision_status: Mapped[str] = mapped_column(String(30), nullable=False)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_start_ms: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    analysis: Mapped[MeetingAnalysisRecord] = relationship(back_populates="decisions")


class ActionItemRecord(Base):
    __tablename__ = "action_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("meeting_analyses.id", ondelete="CASCADE"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(100), nullable=True)
    assignee_status: Mapped[str] = mapped_column(String(30), nullable=False)
    due_date_raw: Mapped[str | None] = mapped_column(String(100), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_precision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    due_date_status: Mapped[str] = mapped_column(String(30), nullable=False)
    task_status: Mapped[str] = mapped_column(String(30), nullable=False)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_start_ms: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    analysis: Mapped[MeetingAnalysisRecord] = relationship(back_populates="action_items")




