from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MeetingStatus(str, Enum):
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    SUCCEEDED_WITH_WARNINGS = "SUCCEEDED_WITH_WARNINGS"
    FAILED = "FAILED"


class JobStage(str, Enum):
    QUEUED = "QUEUED"
    PREPROCESSING = "PREPROCESSING"
    TRANSCRIBING = "TRANSCRIBING"
    ALIGNING = "ALIGNING"
    DIARIZING = "DIARIZING"
    ANALYZING = "ANALYZING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class DecisionStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    PROPOSED = "PROPOSED"
    DISPUTED = "DISPUTED"
    UNRESOLVED = "UNRESOLVED"


class AssigneeStatus(str, Enum):
    EXPLICIT = "EXPLICIT"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class DueDateStatus(str, Enum):
    EXPLICIT = "EXPLICIT"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"
    CONFIRMED = "CONFIRMED"


class ActionItemStatus(str, Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class DiarizationStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    SUCCEEDED = "SUCCEEDED"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


class StageEventOutcome(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class TranscriptSegment(BaseModel):
    id: str
    speaker: str
    speaker_label: str
    start_ms: int
    end_ms: int
    text: str


class SpeakerMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker_label: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    speaker_name: str = Field(min_length=1, max_length=100)


class UpdateSpeakersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mappings: list[SpeakerMapping] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_unique_labels(self) -> "UpdateSpeakersInput":
        labels = [item.speaker_label for item in self.mappings]
        if len(labels) != len(set(labels)):
            raise ValueError("同一说话人标签不能重复映射")
        return self


class Decision(BaseModel):
    id: str
    content: str
    status: DecisionStatus
    evidence_text: str | None
    evidence_start_ms: int | None


class DecisionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, max_length=36)
    content: str = Field(min_length=1)
    status: DecisionStatus
    evidence_text: str | None = None
    evidence_start_ms: int | None = Field(default=None, ge=0)


class ActionItem(BaseModel):
    id: str
    content: str
    assignee: str | None
    assignee_status: AssigneeStatus
    due_date_raw: str | None
    due_at: str | None
    due_precision: str | None
    due_date_status: DueDateStatus
    status: ActionItemStatus
    evidence_text: str | None
    evidence_start_ms: int | None


class ActionItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, max_length=36)
    content: str = Field(min_length=1)
    assignee: str | None = Field(default=None, max_length=100)
    assignee_status: AssigneeStatus
    due_date_raw: str | None = Field(default=None, max_length=100)
    due_at: datetime | None = None
    due_precision: str | None = Field(default=None, max_length=20)
    due_date_status: DueDateStatus
    status: ActionItemStatus
    evidence_text: str | None = None
    evidence_start_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_due_date_consistency(self) -> "ActionItemUpdate":
        if self.due_date_status == DueDateStatus.CONFIRMED and not self.due_at:
            raise ValueError("人工确认截止时间时必须提供 due_at")
        if self.due_at is not None and self.due_at.utcoffset() is None:
            raise ValueError("due_at 必须包含时区偏移")
        if self.due_date_status in {DueDateStatus.AMBIGUOUS, DueDateStatus.UNKNOWN} and self.due_at:
            raise ValueError("模糊或未知截止时间不能提供 due_at")
        return self


class MeetingAnalysis(BaseModel):
    summary: str
    decisions: list[Decision]
    action_items: list[ActionItem]
    version: int = Field(ge=1)
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None


class AnalysisSnapshotDecision(BaseModel):
    content: str
    status: DecisionStatus
    evidence_text: str | None = None
    evidence_start_ms: int | None = None


class AnalysisSnapshotActionItem(BaseModel):
    content: str
    assignee: str | None = None
    assignee_status: AssigneeStatus
    due_date_raw: str | None = None
    due_at: str | None = None
    due_precision: str | None = None
    due_date_status: DueDateStatus
    status: ActionItemStatus
    evidence_text: str | None = None
    evidence_start_ms: int | None = None


class AnalysisSnapshot(BaseModel):
    summary: str
    decisions: list[AnalysisSnapshotDecision]
    action_items: list[AnalysisSnapshotActionItem]


class AnalysisAudit(BaseModel):
    ai_original: AnalysisSnapshot | None
    current: AnalysisSnapshot
    changed_fields: list[str]
    has_changes: bool
    current_version: int = Field(ge=1)
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None


class UpdateAnalysisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    decisions: list[DecisionUpdate]
    action_items: list[ActionItemUpdate]
    version: int = Field(ge=1)


class ProcessingStageEvent(BaseModel):
    id: int
    stage: JobStage
    attempt: int = Field(ge=0)
    started_at: str
    finished_at: str | None = None
    duration_ms: int = Field(ge=0)
    outcome: StageEventOutcome


class ProcessingJob(BaseModel):
    id: str
    meeting_id: str
    stage: JobStage
    progress: int = Field(ge=0, le=100)
    message: str
    error: str | None = None
    error_code: str | None = None
    warning: str | None = None
    diarization_status: DiarizationStatus = DiarizationStatus.NOT_RUN
    speaker_count: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    stage_events: list[ProcessingStageEvent] = Field(default_factory=list)
    updated_at: str


class Meeting(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    original_filename: str
    mime_type: str
    file_size: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    meeting_started_at: str
    participants: list[str]
    context: str
    expected_speakers: int | None = Field(default=None, ge=2, le=10)
    status: MeetingStatus
    created_at: str
    updated_at: str
    transcript: list[TranscriptSegment]
    analysis: MeetingAnalysis | None
    job: ProcessingJob


class CreateMeetingResponse(BaseModel):
    meeting_id: str
    job_id: str
    status: JobStage


class HealthResponse(BaseModel):
    status: str
    service: str
    phase: str


class AuthStatusResponse(BaseModel):
    required: bool
    authenticated: bool
    storage: str = "session"


class QueueHealthResponse(BaseModel):
    status: str
    service: str
    phase: str
    redis: str
    worker_online: bool
    worker_count: int = Field(ge=0)
    queue_length: int = Field(ge=0)
    intermediate_job_count: int = Field(ge=0)
    started_job_count: int = Field(ge=0)
    reconciled_jobs: int = Field(ge=0, default=0)
