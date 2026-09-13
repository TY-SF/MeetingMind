from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from .models import ActionItemRecord, DecisionRecord, MeetingAnalysisRecord, MeetingRecord, ProcessingJobRecord, ProcessingStageEventRecord, TranscriptSegmentRecord


class MeetingRepository(Protocol):
    """Persistence contract shared by JSON and SQL repositories."""

    def list_meetings(self) -> list[dict[str, Any]]: ...
    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None: ...
    def save_meeting(self, meeting: dict[str, Any]) -> None: ...
    def get_job(self, job_id: str) -> dict[str, Any] | None: ...
    def mark_job_failed_from_queue(self, job_id: str, error: str, error_code: str, now: datetime) -> bool: ...
    def delete_meeting(self, meeting_id: str) -> bool: ...
    def get_analysis(self, meeting_id: str) -> dict[str, Any] | None: ...
    def get_analysis_raw_result(self, meeting_id: str) -> dict[str, Any] | None: ...
    def save_analysis(self, meeting_id: str, analysis: dict[str, Any], **metadata: Any) -> dict[str, Any]: ...
    def update_speaker_names(self, meeting_id: str, mappings: dict[str, str]) -> int: ...


class OptimisticLockError(RuntimeError):
    """Raised when an analysis update is based on an old version."""


class SqlAlchemyMeetingRepository:
    """SQL repository for phase 3; does not decide how the Session is created."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_meetings(self) -> list[dict[str, Any]]:
        records = self.session.scalars(
            select(MeetingRecord)
            .options(
                selectinload(MeetingRecord.jobs).selectinload(ProcessingJobRecord.stage_events),
                selectinload(MeetingRecord.transcript_segments),
                selectinload(MeetingRecord.analysis).selectinload(MeetingAnalysisRecord.decisions),
                selectinload(MeetingRecord.analysis).selectinload(MeetingAnalysisRecord.action_items),
            )
            .order_by(MeetingRecord.created_at.desc())
        ).all()
        return [meeting_to_dict(record) for record in records]

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        record = self.session.scalar(
            select(MeetingRecord)
            .where(MeetingRecord.id == meeting_id)
            .options(
                selectinload(MeetingRecord.jobs).selectinload(ProcessingJobRecord.stage_events),
                selectinload(MeetingRecord.transcript_segments),
                selectinload(MeetingRecord.analysis).selectinload(MeetingAnalysisRecord.decisions),
                selectinload(MeetingRecord.analysis).selectinload(MeetingAnalysisRecord.action_items),
            )
        )
        return meeting_to_dict(record) if record else None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        record = self.session.scalar(
            select(ProcessingJobRecord)
            .where(ProcessingJobRecord.id == job_id)
            .options(selectinload(ProcessingJobRecord.stage_events))
        )
        return job_to_dict(record) if record else None

    def delete_meeting(self, meeting_id: str) -> bool:
        record = self.session.get(MeetingRecord, meeting_id)
        if record is None:
            return False
        self.session.delete(record)
        return True

    def mark_job_failed_from_queue(self, job_id: str, error: str, error_code: str, now: datetime) -> bool:
        """Reconcile an RQ failure that happened outside the audio coroutine."""
        job = self.session.scalar(
            select(ProcessingJobRecord)
            .where(ProcessingJobRecord.id == job_id)
            .options(selectinload(ProcessingJobRecord.meeting), selectinload(ProcessingJobRecord.stage_events))
            .with_for_update()
        )
        if job is None or job.status in {"SUCCEEDED", "SUCCEEDED_WITH_WARNINGS", "FAILED"}:
            return False
        open_event = next((event for event in reversed(job.stage_events) if event.finished_at is None), None)
        if open_event is not None:
            open_event.finished_at = now
            open_event.duration_ms = max(0, round((now - open_event.started_at).total_seconds() * 1000))
            open_event.outcome = "INTERRUPTED"
        job.status = "FAILED"
        job.current_stage = "FAILED"
        job.progress = 0
        job.error_code = error_code
        job.error_message = error
        job.status_message = "队列任务未完成，处理已中断；可以重新处理"
        job.finished_at = now
        job.updated_at = now
        if job.meeting is not None:
            job.meeting.status = "FAILED"
            job.meeting.updated_at = now
        self.session.flush()
        return True

    def retry_job(self, job_id: str, now: datetime) -> dict[str, Any] | None:
        """Atomically claim a failed job for retry; one row exists per meeting."""
        job = self.session.scalar(
            select(ProcessingJobRecord)
            .where(ProcessingJobRecord.id == job_id)
            .options(selectinload(ProcessingJobRecord.meeting), selectinload(ProcessingJobRecord.stage_events))
            .with_for_update()
        )
        if job is None:
            return None
        if job.current_stage != "FAILED" or job.status != "FAILED":
            raise ValueError("JOB_NOT_RETRYABLE")
        meeting = job.meeting
        job.retry_count += 1
        job.status = "PROCESSING"
        job.current_stage = "QUEUED"
        job.progress = 8
        job.rq_job_id = None
        job.error_code = None
        job.error_message = None
        job.warning_message = "任务正在人工重试；将从原始音频重新执行。"
        job.status_message = "任务已重新进入队列"
        job.updated_at = now
        job.finished_at = None
        job.stage_events.append(ProcessingStageEventRecord(stage="QUEUED", attempt=job.retry_count, started_at=now, outcome="RUNNING"))
        meeting.status = "PROCESSING"
        meeting.updated_at = now
        self.session.flush()
        return meeting_to_dict(meeting)

    def get_analysis(self, meeting_id: str) -> dict[str, Any] | None:
        record = self.session.scalar(
            select(MeetingAnalysisRecord)
            .where(MeetingAnalysisRecord.meeting_id == meeting_id)
            .options(
                selectinload(MeetingAnalysisRecord.decisions),
                selectinload(MeetingAnalysisRecord.action_items),
            )
        )
        return analysis_to_dict(record) if record else None

    def get_analysis_raw_result(self, meeting_id: str) -> dict[str, Any] | None:
        record = self.session.scalar(
            select(MeetingAnalysisRecord).where(MeetingAnalysisRecord.meeting_id == meeting_id)
        )
        return record.ai_raw_result if record else None

    def save_analysis(
        self,
        meeting_id: str,
        analysis: dict[str, Any],
        *,
        raw_result: dict[str, Any] | None = None,
        provider: str | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        expected_version: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = now or datetime.now(timezone.utc).replace(tzinfo=None)
        query = (
            select(MeetingAnalysisRecord)
            .where(MeetingAnalysisRecord.meeting_id == meeting_id)
            .options(
                selectinload(MeetingAnalysisRecord.decisions),
                selectinload(MeetingAnalysisRecord.action_items),
            )
        )
        # Human-review PATCH operations lock the analysis row so two concurrent
        # requests cannot both pass the same version check on MySQL.
        if expected_version is not None:
            query = query.with_for_update()
        record = self.session.scalar(query)
        if record is None and expected_version is not None:
            raise OptimisticLockError(f"分析结果不存在：expected={expected_version}")
        if record is not None and expected_version is not None and record.version != expected_version:
            raise OptimisticLockError(f"分析版本已变更：expected={expected_version}, actual={record.version}")
        if record is None:
            record = MeetingAnalysisRecord(
                meeting_id=meeting_id,
                summary=analysis.get("summary", ""),
                ai_raw_result=raw_result,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
                version=1,
                created_at=timestamp,
                updated_at=timestamp,
            )
            self.session.add(record)
            self.session.flush()
        else:
            record.summary = analysis.get("summary", "")
            # PATCH from a human reviewer must not destroy the original AI audit snapshot.
            if raw_result is not None:
                record.ai_raw_result = raw_result
            if provider is not None:
                record.provider = provider
            if model is not None:
                record.model = model
            if prompt_version is not None:
                record.prompt_version = prompt_version
            record.version += 1
            record.updated_at = timestamp
            record.decisions.clear()
            record.action_items.clear()
            self.session.flush()

        for sort_order, item in enumerate(analysis.get("decisions", [])):
            record.decisions.append(
                DecisionRecord(
                    id=item.get("id") or uuid_string(),
                    content=item["content"],
                    decision_status=item["status"],
                    evidence_text=item.get("evidence_text"),
                    evidence_start_ms=item.get("evidence_start_ms"),
                    sort_order=sort_order,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        for sort_order, item in enumerate(analysis.get("action_items", [])):
            record.action_items.append(
                ActionItemRecord(
                    id=item.get("id") or uuid_string(),
                    content=item["content"],
                    assignee=item.get("assignee"),
                    assignee_status=item["assignee_status"],
                    due_date_raw=item.get("due_date_raw"),
                    due_at=parse_datetime(item["due_at"]) if item.get("due_at") else None,
                    due_precision=item.get("due_precision"),
                    due_date_status=item["due_date_status"],
                    task_status=item.get("status", "TODO"),
                    evidence_text=item.get("evidence_text"),
                    evidence_start_ms=item.get("evidence_start_ms"),
                    sort_order=sort_order,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        self.session.flush()
        return analysis_to_dict(record)


    def update_speaker_names(self, meeting_id: str, mappings: dict[str, str]) -> int:
        """Apply display names to existing speaker labels without changing raw labels."""
        if not mappings:
            return 0
        records = self.session.scalars(
            select(TranscriptSegmentRecord).where(
                TranscriptSegmentRecord.meeting_id == meeting_id,
                TranscriptSegmentRecord.speaker_label.in_(mappings),
            )
        ).all()
        found_labels = {record.speaker_label for record in records}
        missing_labels = set(mappings) - found_labels
        if missing_labels:
            missing = ", ".join(sorted(missing_labels))
            raise ValueError(f"转录中不存在说话人标签：{missing}")
        for record in records:
            record.speaker_name = mappings[record.speaker_label]
        self.session.flush()
        return len(records)

    def save_meeting(self, meeting: dict[str, Any]) -> None:
        """Upsert the meeting shell and its current job in one transaction."""
        now = parse_datetime(meeting.get("updated_at"))
        record = self.session.get(MeetingRecord, meeting["id"])
        if record is None:
            record = MeetingRecord(
                id=meeting["id"],
                title=meeting["title"],
                original_filename=meeting["original_filename"],
                stored_filename=meeting.get("stored_filename", meeting["original_filename"]),
                mime_type=meeting["mime_type"],
                file_size=meeting["file_size"],
                meeting_started_at=parse_datetime(meeting["meeting_started_at"]),
                created_at=parse_datetime(meeting.get("created_at")),
                updated_at=now,
                status=meeting["status"],
            )
            self.session.add(record)
        for field in (
            "title", "original_filename", "stored_filename", "mime_type", "file_size", "sha256",
            "duration_ms", "participants_json", "context", "expected_speakers", "status",
        ):
            if field in meeting:
                setattr(record, field, meeting[field])
        if "meeting_started_at" in meeting:
            record.meeting_started_at = parse_datetime(meeting["meeting_started_at" ])
        if "participants" in meeting:
            record.participants_json = meeting["participants"]
        if "created_at" in meeting:
            record.created_at = parse_datetime(meeting["created_at"])
        record.updated_at = now

        job_data = meeting.get("job")
        if job_data:
            job = self.session.scalar(
                select(ProcessingJobRecord)
                .where(ProcessingJobRecord.id == job_data["id"])
                .options(selectinload(ProcessingJobRecord.stage_events))
            )
            event_at = parse_datetime(job_data.get("updated_at", meeting.get("updated_at")))
            incoming_stage = job_data["stage"]
            incoming_attempt = int(job_data.get("retry_count", 0))
            is_new_job = job is None
            previous_stage = None if is_new_job else job.current_stage
            previous_attempt = 0 if is_new_job else job.retry_count
            if job is None:
                job = ProcessingJobRecord(
                    id=job_data["id"],
                    meeting_id=meeting["id"],
                    created_at=parse_datetime(meeting.get("created_at")),
                )
                self.session.add(job)

            if is_new_job:
                if incoming_stage not in {"SUCCEEDED", "FAILED"}:
                    job.stage_events.append(
                        ProcessingStageEventRecord(
                            stage=incoming_stage,
                            attempt=incoming_attempt,
                            started_at=event_at,
                            outcome="RUNNING",
                        )
                    )
            elif incoming_stage != previous_stage or incoming_attempt != previous_attempt:
                open_event = next((event for event in reversed(job.stage_events) if event.finished_at is None), None)
                if open_event is not None:
                    open_event.finished_at = event_at
                    open_event.duration_ms = max(0, round((event_at - open_event.started_at).total_seconds() * 1000))
                    if incoming_stage == "FAILED":
                        open_event.outcome = "FAILED"
                    elif incoming_attempt != previous_attempt:
                        open_event.outcome = "INTERRUPTED"
                    else:
                        open_event.outcome = "COMPLETED"
                if incoming_stage not in {"SUCCEEDED", "FAILED"}:
                    job.stage_events.append(
                        ProcessingStageEventRecord(
                            stage=incoming_stage,
                            attempt=incoming_attempt,
                            started_at=event_at,
                            outcome="RUNNING",
                        )
                    )

            job.rq_job_id = job_data.get("rq_job_id", job.rq_job_id)
            job.status = meeting["status"]
            job.current_stage = incoming_stage
            job.progress = job_data["progress"]
            job.retry_count = incoming_attempt
            job.error_code = job_data.get("error_code")
            job.error_message = job_data.get("error")
            job.status_message = job_data.get("message")
            job.warning_message = job_data.get("warning")
            job.diarization_status = job_data.get("diarization_status", job.diarization_status or "NOT_RUN")
            job.speaker_count = int(job_data.get("speaker_count", job.speaker_count or 0))
            job.updated_at = event_at
            if job.started_at is None and job.current_stage != "QUEUED":
                job.started_at = job.updated_at
            if job.current_stage in {"SUCCEEDED", "FAILED"}:
                job.finished_at = job.updated_at
            else:
                job.finished_at = None

    def replace_transcript(self, meeting_id: str, segments: Iterable[dict[str, Any]], created_at: datetime) -> None:
        self.session.execute(delete(TranscriptSegmentRecord).where(TranscriptSegmentRecord.meeting_id == meeting_id))
        self.session.add_all(
            TranscriptSegmentRecord(
                meeting_id=meeting_id,
                segment_index=index,
                speaker_label=segment.get("speaker_label", segment.get("speaker", "SPEAKER_00")),
                speaker_name=segment.get("speaker_name") or (
                    segment.get("speaker") if segment.get("speaker_label") and segment.get("speaker") != segment.get("speaker_label") else None
                ),
                start_ms=segment.get("start_ms", 0),
                end_ms=segment.get("end_ms", 0),
                text=segment.get("text", ""),
                created_at=created_at,
            )
            for index, segment in enumerate(segments)
        )


def parse_datetime(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    return datetime.now(timezone.utc).replace(tzinfo=None)


def meeting_to_dict(record: MeetingRecord) -> dict[str, Any]:
    latest_job = max(record.jobs, key=lambda job: job.created_at) if record.jobs else None
    return {
        "id": record.id,
        "title": record.title,
        "original_filename": record.original_filename,
        "stored_filename": record.stored_filename,
        "mime_type": record.mime_type,
        "file_size": record.file_size,
        "sha256": record.sha256,
        "duration_ms": record.duration_ms or 0,
        "meeting_started_at": record.meeting_started_at.isoformat(),
        "participants": record.participants_json or [],
        "context": record.context or "",
        "expected_speakers": record.expected_speakers,
        "status": record.status,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "transcript": [
            {
                "id": str(segment.id),
                "speaker": segment.speaker_name or segment.speaker_label,
                "speaker_label": segment.speaker_label,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "text": segment.text,
            }
            for segment in sorted(record.transcript_segments, key=lambda item: item.segment_index)
        ],
        "analysis": analysis_to_dict(record.analysis) if record.analysis else None,
        "job": job_to_dict(latest_job) if latest_job else None,
    }


def job_to_dict(record: ProcessingJobRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "meeting_id": record.meeting_id,
        "stage": record.current_stage,
        "progress": record.progress,
        "message": record.status_message or record.error_message or f"任务阶段：{record.current_stage}",
        "error": record.error_message,
        "error_code": record.error_code,
        "warning": record.warning_message,
        "diarization_status": record.diarization_status or "NOT_RUN",
        "speaker_count": record.speaker_count or 0,
        "retry_count": record.retry_count,
        "stage_events": [stage_event_to_dict(event) for event in record.stage_events],
        "updated_at": format_stored_datetime(record.updated_at),
    }


def stage_event_to_dict(record: ProcessingStageEventRecord) -> dict[str, Any]:
    finished_at = record.finished_at
    duration_ms = record.duration_ms
    if finished_at is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        duration_ms = max(0, round((now - record.started_at).total_seconds() * 1000))
    return {
        "id": record.id,
        "stage": record.stage,
        "attempt": record.attempt,
        "started_at": format_stored_datetime(record.started_at),
        "finished_at": format_stored_datetime(finished_at) if finished_at else None,
        "duration_ms": duration_ms or 0,
        "outcome": record.outcome,
    }




def uuid_string() -> str:
    import uuid
    return str(uuid.uuid4())


def format_stored_datetime(value: datetime) -> str:
    """Database DateTime is stored in UTC without timezone metadata."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


def analysis_to_dict(record: MeetingAnalysisRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "id": record.id,
        "summary": record.summary,
        "decisions": [
            {
                "id": item.id,
                "content": item.content,
                "status": item.decision_status,
                "evidence_text": item.evidence_text,
                "evidence_start_ms": item.evidence_start_ms,
            }
            for item in sorted(record.decisions, key=lambda value: value.sort_order)
        ],
        "action_items": [
            {
                "id": item.id,
                "content": item.content,
                "assignee": item.assignee,
                "assignee_status": item.assignee_status,
                "due_date_raw": item.due_date_raw,
                "due_at": format_stored_datetime(item.due_at) if item.due_at else None,
                "due_precision": item.due_precision,
                "due_date_status": item.due_date_status,
                "status": item.task_status,
                "evidence_text": item.evidence_text,
                "evidence_start_ms": item.evidence_start_ms,
            }
            for item in sorted(record.action_items, key=lambda value: value.sort_order)
        ],
        "version": record.version,
        "provider": record.provider,
        "model": record.model,
        "prompt_version": record.prompt_version,
    }
