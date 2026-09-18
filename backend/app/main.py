from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from dataclasses import replace
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import Response

from .audio_processor import AudioProcessingError, transcribe_audio, validate_audio_file
from .auth import AccessTokenMiddleware, PUBLIC_API_PATHS, SecurityHeadersMiddleware, token_matches
from .config import Settings
from .db import MeetingDeletionError, OptimisticLockError, SqlAlchemyStore
from .schemas import AnalysisAudit, AuthStatusResponse, CreateMeetingResponse, HealthResponse, Meeting, MeetingAnalysis, ProcessingJob, QueueHealthResponse, UpdateAnalysisInput, UpdateSpeakersInput
from .services.analysis import AnalysisInputTooLong, AnalysisProviderError, MeetingAnalysisDraft, MeetingAnalysisService, OpenAIAnalysisProvider, normalize_draft
from .services.exports import render_ics, render_markdown
from .observability import RequestIdMiddleware, configure_logging
from .queue_health import QueueSnapshot, read_queue_snapshot, reconcile_queue_jobs
from .queueing import QueueUnavailableError, enqueue_processing_job
from .store import JsonStore

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a"}
ALLOWED_MIME_TYPES = {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/m4a", "audio/x-m4a"}
OPENAPI_TAGS = [
    {
        "name": "健康检查",
        "description": "服务存活与数据库就绪检查。部署编排应使用 `/health/ready` 判断是否接收业务流量。",
    },
    {
        "name": "会议与处理任务",
        "description": "上传本地音频、读取会议数据、跟踪异步处理任务，以及删除会议及其本地文件。",
    },
    {
        "name": "AI 分析与审核",
        "description": "以已保存的转录为输入生成结构化草稿，并通过版本号进行人工审核的并发保护。",
    },
    {
        "name": "说话人与导出",
        "description": "维护显示名称映射，并导出人工审核后的 Markdown 或 Outlook 兼容 ICS。",
    },
]

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_meeting_started_at(value: str | None) -> str:
    if not value:
        return utc_now()
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="meeting_started_at 必须是 ISO 8601 日期时间") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def parse_participants(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="participants 必须是 JSON 字符串数组") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) and item.strip() for item in parsed):
        raise HTTPException(status_code=422, detail="participants 必须是非空字符串数组")
    if len(parsed) > 10:
        raise HTTPException(status_code=422, detail="participants 最多支持 10 人")
    return [item.strip() for item in parsed]


async def save_upload(upload: UploadFile, target: Path, max_size_bytes: int) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    try:
        with target.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_size_bytes:
                    max_size_mb = max_size_bytes // (1024 * 1024)
                    raise HTTPException(status_code=413, detail=f"音频文件不能超过 {max_size_mb} MB")
                output.write(chunk)
                digest.update(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return size, digest.hexdigest()


def update_job(
    store: JsonStore | SqlAlchemyStore,
    meeting_id: str,
    *,
    stage: str,
    progress: int,
    message: str,
    warning: str | None = None,
    error: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any] | None:
    meeting = store.get_meeting(meeting_id)
    if meeting is None:
        return None
    now = utc_now()
    meeting["job"].update({
        "stage": stage,
        "progress": progress,
        "message": message,
        "warning": warning,
        "error": error,
        "error_code": error_code,
        "updated_at": now,
    })
    meeting["updated_at"] = now
    store.save_meeting(meeting)
    return meeting


def finish_failed_job(
    store: JsonStore | SqlAlchemyStore,
    meeting_id: str,
    error: str,
    *,
    error_code: str = "AUDIO_PROCESSING_FAILED",
) -> None:
    meeting = update_job(
        store,
        meeting_id,
        stage="FAILED",
        progress=0,
        message="音频处理失败",
        error=error,
        error_code=error_code,
    )
    if meeting is not None:
        meeting["status"] = "FAILED"
        meeting["updated_at"] = utc_now()
        store.save_meeting(meeting)


RECOVERABLE_JOB_STAGES = {"QUEUED", "PREPROCESSING", "TRANSCRIBING", "ALIGNING", "DIARIZING"}


def enqueue_job(app: FastAPI, store: JsonStore | SqlAlchemyStore, meeting_id: str, settings: Settings) -> str | None:
    meeting = store.get_meeting(meeting_id)
    if meeting is None:
        raise QueueUnavailableError("会议不存在，无法进入队列")
    internal_job_id = meeting["job"]["id"]

    def submit_inline() -> asyncio.Task[Any]:
        task = asyncio.create_task(run_transcription_job(store, meeting_id, settings))
        track_background_task(app, task)
        return task

    rq_job_id = enqueue_processing_job(
        settings=settings,
        meeting_id=meeting_id,
        internal_job_id=internal_job_id,
        inline_submit=submit_inline,
    )
    if rq_job_id:
        current = store.get_meeting(meeting_id)
        if current is not None:
            current["job"]["rq_job_id"] = rq_job_id
            current["updated_at"] = utc_now()
            store.save_meeting(current)
    return rq_job_id


def track_background_task(app: FastAPI, task: asyncio.Task[Any]) -> None:
    app.state.tasks.add(task)
    task.add_done_callback(app.state.tasks.discard)


def recover_interrupted_jobs(app: FastAPI, store: JsonStore | SqlAlchemyStore, settings: Settings) -> int:
    """Restart interrupted audio jobs from their immutable source file.

    The audio pipeline is deterministic from the uploaded source. Re-running it is
    safer than guessing which partially written intermediate artifact is complete.
    """
    recovered = 0
    for meeting in store.list_meetings():
        job = meeting.get("job") or {}
        if meeting.get("status") != "PROCESSING" or job.get("stage") not in RECOVERABLE_JOB_STAGES:
            continue
        suffix = Path(meeting.get("original_filename", "")).suffix.lower()
        source = store.source_path(meeting["id"], suffix)
        if not suffix or not source.is_file():
            finish_failed_job(
                store,
                meeting["id"],
                "检测到中断任务，但原始音频文件不存在，无法自动恢复",
                error_code="SOURCE_FILE_MISSING",
            )
            continue
        now = utc_now()
        job.update({
            "stage": "QUEUED",
            "progress": 8,
            "message": "检测到上次处理中断，正在从原始音频重新开始",
            "warning": "任务由服务启动恢复；为保证产物一致性，将重新执行音频处理。",
            "error": None,
            "error_code": None,
            "retry_count": int(job.get("retry_count", 0)) + 1,
            "updated_at": now,
        })
        meeting["job"] = job
        meeting["updated_at"] = now
        store.save_meeting(meeting)

        try:
            enqueue_job(app, store, meeting["id"], settings)
        except QueueUnavailableError as exc:
            finish_failed_job(store, meeting["id"], str(exc), error_code="QUEUE_UNAVAILABLE")
        recovered += 1
    return recovered


def require_exportable_meeting(store: SqlAlchemyStore, meeting_id: str) -> dict[str, Any]:
    meeting = store.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在或已被删除")
    if not meeting.get("analysis"):
        raise HTTPException(
            status_code=409,
            detail={"code": "ANALYSIS_NOT_READY", "message": "会议尚未生成分析结果"},
        )
    return meeting


def extract_parsed_model_draft(raw_result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extract only the parsed structured payload from a stored provider response."""
    if not isinstance(raw_result, dict):
        return None
    for output in raw_result.get("output", []):
        if not isinstance(output, dict):
            continue
        for content in output.get("content", []):
            if not isinstance(content, dict):
                continue
            parsed = content.get("parsed")
            if isinstance(parsed, dict):
                return parsed
            text = content.get("text")
            if isinstance(text, str):
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    return value
    return None


def analysis_snapshot(analysis: dict[str, Any]) -> dict[str, Any]:
    """Drop identifiers/provider metadata so human edits can be compared semantically."""
    return {
        "summary": str(analysis.get("summary", "")).strip(),
        "decisions": [
            {
                "content": item.get("content", ""),
                "status": item.get("status"),
                "evidence_text": item.get("evidence_text"),
                "evidence_start_ms": item.get("evidence_start_ms"),
            }
            for item in analysis.get("decisions", [])
        ],
        "action_items": [
            {
                "content": item.get("content", ""),
                "assignee": item.get("assignee"),
                "assignee_status": item.get("assignee_status"),
                "due_date_raw": item.get("due_date_raw"),
                "due_at": item.get("due_at"),
                "due_precision": item.get("due_precision"),
                "due_date_status": item.get("due_date_status"),
                "status": item.get("status", "TODO"),
                "evidence_text": item.get("evidence_text"),
                "evidence_start_ms": item.get("evidence_start_ms"),
            }
            for item in analysis.get("action_items", [])
        ],
    }


def analysis_changed_fields(original: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    if original is None:
        return []
    labels = {"summary": "摘要", "decisions": "结论", "action_items": "待办"}
    return [labels[key] for key in labels if original.get(key) != current.get(key)]


def download_response(content: bytes, title: str, suffix: str, media_type: str) -> Response:
    filename = f"{title}{suffix}"
    disposition = f"attachment; filename=meetingmind{suffix}; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff"},
    )


def create_app(data_dir: Path | None = None, database_url: str | None = None) -> FastAPI:
    settings = Settings.from_env()
    # Tests can pass a data directory and get an isolated SQLite database.
    # Production uses the configured MySQL URL from the local env file.
    if data_dir is not None and database_url is None:
        database_url = f"sqlite:///{data_dir / 'meetingmind.db'}"
        # Test apps intentionally opt into the explicit inline backend; production
        # uses Redis/RQ from the environment and never silently falls back.
        settings = replace(settings, queue_backend="inline")
        store = SqlAlchemyStore(data_dir, database_url, create_schema=True)
    else:
        store = SqlAlchemyStore(data_dir or settings.data_dir, database_url or settings.database_url)
    @asynccontextmanager
    async def lifespan(current_app: FastAPI):
        recover_interrupted_jobs(current_app, store, settings)
        reconcile_queue_jobs(store, settings)
        monitor: asyncio.Task[Any] | None = None
        stop = asyncio.Event()

        async def monitor_queue() -> None:
            while not stop.is_set():
                await asyncio.sleep(max(5, settings.rq_reconciliation_interval_seconds))
                if stop.is_set():
                    break
                await asyncio.to_thread(reconcile_queue_jobs, store, settings)

        if settings.queue_backend == "rq":
            monitor = asyncio.create_task(monitor_queue())
        try:
            yield
        finally:
            stop.set()
            if monitor is not None:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)

    app = FastAPI(
        title="MeetingMind API",
        version="0.5.0",
        summary="本地优先的中文会议音频整理 API",
        description=(
            "MeetingMind 在本机执行音频规范化、WhisperX 转录和 pyannote 说话人分离。"
            "只有在调用 AI 分析接口时，已保存的转录文本才会发送至配置的模型服务；原始音频不会发送。"
            "系统不会自动脱敏，上传前必须确认已获得录音处理授权，调用 AI 前必须确认转录内容适合外发。"
            "部署者可通过 `MEETINGMIND_API_TOKEN` 为业务 API 启用 Bearer 访问令牌。\n\n"
            "处理任务为异步任务：上传接口返回 `202 Accepted` 后，请轮询任务接口直到阶段为 "
            "`SUCCEEDED` 或 `FAILED`。若说话人分离不可用，转录会保留，任务以 "
            "`SUCCEEDED_WITH_WARNINGS` 和 `diarization_status=DEGRADED` 标识降级。"
        ),
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    allowed_origins = [origin.strip() for origin in settings.frontend_origin.split(",") if origin.strip()]
    configure_logging(
        settings.log_level,
        log_file=(data_dir or settings.data_dir) / "logs" / "api.jsonl",
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    app.add_middleware(AccessTokenMiddleware, access_token=settings.api_access_token)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    app.state.store = store
    app.state.settings = settings
    app.state.tasks: set[asyncio.Task[Any]] = set()

    @app.get("/api/v1/health", response_model=HealthResponse, tags=["健康检查"], summary="检查 API 存活")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="meetingmind-backend", phase="phase-8")

    @app.get(
        "/api/v1/auth/status",
        response_model=AuthStatusResponse,
        tags=["健康检查"],
        summary="检查业务 API 是否启用访问令牌",
        description="该端点不返回令牌本身，只告知当前请求是否已经通过部署级 Bearer 令牌认证。",
    )
    async def auth_status(request: Request) -> AuthStatusResponse:
        return AuthStatusResponse(
            required=bool(settings.api_access_token),
            authenticated=token_matches(request.headers.get("Authorization"), settings.api_access_token),
        )

    @app.get("/api/v1/health/ready", response_model=HealthResponse, tags=["健康检查"], summary="检查数据库是否就绪", responses={503: {"description": "数据库尚未就绪"}})
    async def readiness() -> HealthResponse:
        if not store.check_ready():
            raise HTTPException(status_code=503, detail="数据库尚未就绪")
        return HealthResponse(status="ready", service="meetingmind-backend", phase="phase-8")

    @app.get("/api/v1/health/queue", response_model=QueueHealthResponse, tags=["健康检查"], summary="检查 Redis 与 RQ Worker 状态", responses={503: {"description": "Redis 不可用"}})
    async def queue_health() -> QueueHealthResponse:
        if settings.queue_backend != "rq":
            return QueueHealthResponse(
                status="disabled", service="meetingmind-backend", phase="phase-8", redis="disabled",
                worker_online=False, worker_count=0, queue_length=0, intermediate_job_count=0,
                started_job_count=0, reconciled_jobs=0,
            )
        reconciled = await asyncio.to_thread(reconcile_queue_jobs, store, settings)
        try:
            snapshot = await asyncio.to_thread(read_queue_snapshot, settings)
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"code": "REDIS_UNAVAILABLE", "message": "Redis 不可用"}) from exc
        status_value = "ready" if snapshot.worker_online else "degraded"
        return QueueHealthResponse(
            status=status_value, service="meetingmind-backend", phase="phase-8", redis=snapshot.redis,
            worker_online=snapshot.worker_online, worker_count=snapshot.worker_count,
            queue_length=snapshot.queue_length, intermediate_job_count=snapshot.intermediate_job_count,
            started_job_count=snapshot.started_job_count, reconciled_jobs=reconciled,
        )

    @app.post(
        "/api/v1/meetings",
        response_model=CreateMeetingResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["会议与处理任务"],
        summary="上传音频并创建异步处理任务",
        description=(
            f"支持 MP3、WAV、M4A，文件最大 {settings.max_upload_size_mb} MB。音频保存在本机并在本机处理；"
            "系统不会自动脱敏。调用方必须确认已获得录音处理授权并理解数据边界。"
            "返回后请轮询 `GET /api/v1/jobs/{job_id}`。"
        ),
        responses={415: {"description": "不支持的文件扩展名或 MIME 类型"}, 422: {"description": "表单字段校验失败"}},
    )
    async def create_meeting(
        file: UploadFile = File(..., description=f"MP3、WAV 或 M4A 音频文件（最大 {settings.max_upload_size_mb} MB）"),
        title: str = Form(..., description="会议标题，最多 200 个字符"),
        meeting_started_at: str | None = Form(None, description="可选 ISO 8601 会议发生时间，需包含时区"),
        participants: str = Form("[]", description="参会人 JSON 字符串数组，最多 10 人，例如 [\"张三\", \"李四\"]"),
        context: str = Form("", description="可选会议背景，最多 500 个字符"),
        expected_speakers: int | None = Form(None, description="可选预计说话人数，范围 2 到 10"),
        data_processing_confirmed: bool = Form(
            False,
            description="确认已获得录音处理授权，并理解本地处理、外部模型调用和无自动脱敏的数据边界",
        ),
    ) -> CreateMeetingResponse:
        if not data_processing_confirmed:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "DATA_PROCESSING_CONFIRMATION_REQUIRED",
                    "message": "请确认已获得录音处理授权，并理解系统不会自动脱敏",
                },
            )
        title = title.strip()
        context = context.strip()
        if not title:
            raise HTTPException(status_code=422, detail="title 不能为空")
        if len(title) > 200:
            raise HTTPException(status_code=422, detail="title 不能超过 200 个字符")
        if len(context) > 500:
            raise HTTPException(status_code=422, detail="context 不能超过 500 个字符")
        if expected_speakers is not None and not 2 <= expected_speakers <= 10:
            raise HTTPException(status_code=422, detail={"code": "INVALID_EXPECTED_SPEAKERS", "message": "预计说话人数必须在 2 到 10 之间"})

        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=415, detail={"code": "UNSUPPORTED_AUDIO_FORMAT", "message": "仅支持 MP3、WAV、M4A 音频文件"})
        if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=415, detail={"code": "UNSUPPORTED_AUDIO_MIME", "message": "上传文件的 MIME 类型不是支持的音频类型"})

        meeting_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        created_at = utc_now()
        target = store.source_path(meeting_id, suffix)
        try:
            file_size, sha256 = await save_upload(file, target, settings.max_upload_size_mb * 1024 * 1024)
            try:
                probe = await asyncio.to_thread(
                    validate_audio_file,
                    target,
                    max_audio_duration_minutes=settings.max_audio_duration_minutes,
                )
            except AudioProcessingError as exc:
                raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc
            meeting = {
                "id": meeting_id,
                "title": title,
                "original_filename": file.filename or f"original{suffix}",
                "stored_filename": f"{meeting_id}/source/original{suffix}",
                "mime_type": file.content_type or "application/octet-stream",
                "file_size": file_size,
                "sha256": sha256,
                "duration_ms": probe.duration_ms,
                "meeting_started_at": parse_meeting_started_at(meeting_started_at),
                "participants": parse_participants(participants),
                "context": context,
                "expected_speakers": expected_speakers,
                "status": "PROCESSING",
                "created_at": created_at,
                "updated_at": created_at,
                "transcript": [],
                "analysis": None,
                "job": {
                    "id": job_id,
                    "meeting_id": meeting_id,
                    "stage": "QUEUED",
                    "progress": 8,
                    "message": "任务已进入队列",
                    "error": None,
                    "error_code": None,
                    "warning": None,
                    "retry_count": 0,
                    "updated_at": created_at,
                },
            }
            store.save_meeting(meeting)
        except Exception:
            target.unlink(missing_ok=True)
            raise

        try:
            enqueue_job(app, store, meeting_id, settings)
        except QueueUnavailableError as exc:
            finish_failed_job(store, meeting_id, str(exc), error_code="QUEUE_UNAVAILABLE")
            raise HTTPException(status_code=503, detail={"code": "QUEUE_UNAVAILABLE", "message": "Redis/RQ 不可用，会议已保存但尚未开始处理，可稍后重试"}) from exc
        return CreateMeetingResponse(meeting_id=meeting_id, job_id=job_id, status="QUEUED")

    @app.get("/api/v1/meetings", response_model=list[Meeting], tags=["会议与处理任务"], summary="获取会议列表")
    async def list_meetings() -> list[Meeting]:
        return [Meeting.model_validate(item) for item in store.list_meetings()]

    @app.get("/api/v1/meetings/{meeting_id}", response_model=Meeting, tags=["会议与处理任务"], summary="获取会议详情", responses={404: {"description": "会议不存在或已删除"}})
    async def get_meeting(meeting_id: str) -> Meeting:
        meeting = store.get_meeting(meeting_id)
        if meeting is None:
            raise HTTPException(status_code=404, detail="会议不存在或已被删除")
        return Meeting.model_validate(meeting)

    @app.get("/api/v1/jobs/{job_id}", response_model=ProcessingJob, tags=["会议与处理任务"], summary="查询异步处理进度", description="读取当前阶段、进度、说话人分离结果和各阶段真实耗时。", responses={404: {"description": "任务不存在"}})
    async def get_job(job_id: str) -> ProcessingJob:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return ProcessingJob.model_validate(job)

    @app.post(
        "/api/v1/jobs/{job_id}/retry",
        response_model=ProcessingJob,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["会议与处理任务"],
        summary="重新排队失败的音频处理任务",
        responses={404: {"description": "任务不存在"}, 409: {"description": "只有失败任务可以重试"}, 503: {"description": "Redis/RQ 不可用"}},
    )
    async def retry_job(job_id: str) -> ProcessingJob:
        try:
            meeting = store.retry_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "JOB_NOT_RETRYABLE", "message": "只有失败的任务可以重新处理"}) from exc
        if meeting is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        try:
            enqueue_job(app, store, meeting["id"], settings)
        except QueueUnavailableError as exc:
            finish_failed_job(store, meeting["id"], str(exc), error_code="QUEUE_UNAVAILABLE")
            raise HTTPException(status_code=503, detail={"code": "QUEUE_UNAVAILABLE", "message": "Redis/RQ 不可用，稍后可再次重试"}) from exc
        current = store.get_job(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return ProcessingJob.model_validate(current)

    @app.get("/api/v1/meetings/{meeting_id}/analysis", response_model=MeetingAnalysis, tags=["AI 分析与审核"], summary="读取当前会议分析", responses={404: {"description": "会议或分析不存在"}})
    async def get_analysis(meeting_id: str) -> MeetingAnalysis:
        if store.get_meeting(meeting_id) is None:
            raise HTTPException(status_code=404, detail="会议不存在或已被删除")
        analysis = store.get_analysis(meeting_id)
        if analysis is None:
            raise HTTPException(status_code=404, detail="会议尚未生成分析结果")
        return MeetingAnalysis.model_validate(analysis)

    @app.get("/api/v1/meetings/{meeting_id}/analysis/audit", response_model=AnalysisAudit, tags=["AI 分析与审核"], summary="比较 AI 原始草稿与当前审核结果", responses={404: {"description": "会议或分析不存在"}})
    async def get_analysis_audit(meeting_id: str) -> AnalysisAudit:
        meeting = store.get_meeting(meeting_id)
        if meeting is None:
            raise HTTPException(status_code=404, detail="会议不存在或已被删除")
        current_analysis = store.get_analysis(meeting_id)
        if current_analysis is None:
            raise HTTPException(status_code=404, detail="会议尚未生成分析结果")
        current_snapshot = analysis_snapshot(current_analysis)
        original_snapshot = None
        parsed = extract_parsed_model_draft(store.get_analysis_raw_result(meeting_id))
        if parsed is not None:
            try:
                draft = MeetingAnalysisDraft.model_validate(parsed)
                normalized = normalize_draft(draft, meeting["meeting_started_at"])
                original_snapshot = analysis_snapshot({
                    "summary": normalized.summary,
                    "decisions": normalized.decisions,
                    "action_items": normalized.action_items,
                })
            except (ValueError, TypeError):
                original_snapshot = None
        changed_fields = analysis_changed_fields(original_snapshot, current_snapshot)
        return AnalysisAudit.model_validate({
            "ai_original": original_snapshot,
            "current": current_snapshot,
            "changed_fields": changed_fields,
            "has_changes": bool(changed_fields),
            "current_version": current_analysis["version"],
            "provider": current_analysis.get("provider"),
            "model": current_analysis.get("model"),
            "prompt_version": current_analysis.get("prompt_version"),
        })

    @app.post(
        "/api/v1/meetings/{meeting_id}/analysis",
        response_model=MeetingAnalysis,
        tags=["AI 分析与审核"],
        summary="生成或重新生成 AI 分析草稿",
        description=(
            "只向已配置的模型服务提交带时间戳的转录文本和会议背景；原始音频不会发送。"
            "系统不会自动脱敏，调用方必须在每次生成或重新生成前确认内容适合外发。"
            "需要后端本机配置 OpenAI API Key。"
        ),
        responses={409: {"description": "转录尚未就绪"}, 422: {"description": "未确认外部模型数据传输"}, 503: {"description": "未配置模型服务凭据"}},
    )
    async def analyze_meeting(
        meeting_id: str,
        analysis_data_confirmed: bool = Body(
            False,
            embed=True,
            description="确认转录文本和会议背景适合发送至已配置的模型服务，并理解系统不会自动脱敏",
        ),
    ) -> MeetingAnalysis:
        if not analysis_data_confirmed:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "ANALYSIS_DATA_CONFIRMATION_REQUIRED",
                    "message": "请确认转录内容适合发送至已配置的模型服务，并理解系统不会自动脱敏",
                },
            )
        meeting = store.get_meeting(meeting_id)
        if meeting is None:
            raise HTTPException(status_code=404, detail="会议不存在或已被删除")
        transcript = meeting.get("transcript", [])
        if not transcript:
            raise HTTPException(status_code=409, detail={"code": "TRANSCRIPT_NOT_READY", "message": "会议尚未生成转录"})
        if not settings.llm_api_key:
            raise HTTPException(status_code=503, detail={"code": "MODEL_AUTH_ERROR", "message": "未配置 OpenAI API Key；请配置后再执行分析"})

        provider = OpenAIAnalysisProvider(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        service = MeetingAnalysisService(provider, max_input_chars=settings.llm_max_input_chars)
        update_job(store, meeting_id, stage="ANALYZING", progress=88, message="正在请求结构化会议分析")
        try:
            result, normalized = await asyncio.to_thread(
                service.analyze,
                transcript=transcript,
                meeting_started_at=meeting["meeting_started_at"],
                context=meeting.get("context", ""),
            )
            analysis_payload = {
                "summary": normalized.summary,
                "decisions": normalized.decisions,
                "action_items": normalized.action_items,
            }
            store.save_analysis(
                meeting_id,
                analysis_payload,
                raw_result=result.raw_result,
                provider=result.provider,
                model=result.model,
                prompt_version=result.prompt_version,
            )
        except AnalysisInputTooLong as exc:
            update_job(store, meeting_id, stage="FAILED", progress=88, message="转录文本超过 AI 输入上限", error=str(exc), error_code=exc.code)
            current = store.get_meeting(meeting_id)
            if current:
                current["status"] = "FAILED"
                store.save_meeting(current)
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc
        except AnalysisProviderError as exc:
            update_job(store, meeting_id, stage="FAILED", progress=88, message="AI 分析失败", error=str(exc), error_code=exc.code)
            current = store.get_meeting(meeting_id)
            if current:
                current["status"] = "FAILED"
                store.save_meeting(current)
            error_status = {
                "MODEL_AUTH_ERROR": 503,
                "MODEL_RATE_LIMITED": 429,
                "MODEL_TIMEOUT": 504,
                "MODEL_REQUEST_INVALID": 422,
            }.get(exc.code, 502)
            raise HTTPException(status_code=error_status, detail={"code": exc.code, "message": str(exc)}) from exc
        except OptimisticLockError as exc:
            raise HTTPException(status_code=409, detail={"code": "ANALYSIS_VERSION_CONFLICT", "message": str(exc)}) from exc

        current = store.get_meeting(meeting_id)
        if current is None or current.get("analysis") is None:
            raise HTTPException(status_code=500, detail="分析结果保存后无法读取")
        now = utc_now()
        warning = current.get("job", {}).get("warning")
        current["status"] = "SUCCEEDED_WITH_WARNINGS" if warning else "SUCCEEDED"
        current["job"].update({
            "stage": "SUCCEEDED",
            "progress": 100,
            "message": "会议分析完成",
            "warning": warning,
            "error": None,
            "error_code": None,
            "updated_at": now,
        })
        current["updated_at"] = now
        store.save_meeting(current)
        saved = store.get_analysis(meeting_id)
        if saved is None:
            raise HTTPException(status_code=500, detail="分析结果保存后无法读取")
        return MeetingAnalysis.model_validate(saved)

    @app.patch("/api/v1/meetings/{meeting_id}/analysis", response_model=MeetingAnalysis, tags=["AI 分析与审核"], summary="保存人工审核后的分析", description="请求体必须携带当前 `version`。版本冲突时返回 `409 ANALYSIS_VERSION_CONFLICT`。", responses={409: {"description": "分析版本冲突"}})
    async def update_analysis(meeting_id: str, payload: UpdateAnalysisInput) -> MeetingAnalysis:
        if store.get_meeting(meeting_id) is None:
            raise HTTPException(status_code=404, detail="会议不存在或已被删除")
        if store.get_analysis(meeting_id) is None:
            raise HTTPException(status_code=404, detail="会议尚未生成分析结果")
        try:
            saved = store.save_analysis(
                meeting_id,
                payload.model_dump(mode="json", exclude={"version"}),
                expected_version=payload.version,
            )
        except OptimisticLockError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "ANALYSIS_VERSION_CONFLICT", "message": str(exc)},
            ) from exc
        return MeetingAnalysis.model_validate(saved)

    @app.patch("/api/v1/meetings/{meeting_id}/speakers", response_model=Meeting, tags=["说话人与导出"], summary="映射说话人标签到显示姓名", description="原始 `speaker_label` 不变，只更新前端显示的说话人姓名。")
    async def update_speakers(meeting_id: str, payload: UpdateSpeakersInput) -> Meeting:
        meeting = store.get_meeting(meeting_id)
        if meeting is None:
            raise HTTPException(status_code=404, detail="会议不存在或已被删除")
        if not meeting.get("transcript"):
            raise HTTPException(
                status_code=409,
                detail={"code": "TRANSCRIPT_NOT_READY", "message": "会议尚未生成转录"},
            )
        mappings = {item.speaker_label: item.speaker_name.strip() for item in payload.mappings}
        try:
            store.update_speaker_names(meeting_id, mappings)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "UNKNOWN_SPEAKER_LABEL", "message": str(exc)},
            ) from exc
        updated = store.get_meeting(meeting_id)
        if updated is None:
            raise HTTPException(status_code=500, detail="说话人映射保存后无法读取")
        return Meeting.model_validate(updated)

    @app.get("/api/v1/meetings/{meeting_id}/exports/markdown", tags=["说话人与导出"], summary="下载会议 Markdown", responses={409: {"description": "尚未生成可导出的分析结果"}})
    async def export_markdown(meeting_id: str) -> Response:
        meeting = require_exportable_meeting(store, meeting_id)
        content = render_markdown(meeting)
        return download_response(content.encode("utf-8"), meeting["title"], ".md", "text/markdown; charset=utf-8")

    @app.get("/api/v1/meetings/{meeting_id}/exports/calendar", tags=["说话人与导出"], summary="下载 Outlook 兼容 ICS", description="只导出带明确或人工确认截止时间的待办；文件使用 UTF-8 BOM、CRLF 和字节级折行。", responses={409: {"description": "尚无可导出的待办或分析结果"}})
    async def export_calendar(meeting_id: str) -> Response:
        meeting = require_exportable_meeting(store, meeting_id)
        action_items = meeting["analysis"].get("action_items", [])
        exportable = [
            item for item in action_items
            if item.get("due_at") and item.get("due_date_status") in {"EXPLICIT", "CONFIRMED"}
        ]
        if not exportable:
            raise HTTPException(
                status_code=409,
                detail={"code": "NO_EXPORTABLE_ACTION_ITEMS", "message": "没有具有明确或人工确认截止时间的待办"},
            )
        content = render_ics(meeting)
        # Outlook's preview and calendar-import paths use different decoders.  A UTF-8
        # BOM makes the downloaded local file unambiguous to its import path while
        # keeping the iCalendar payload itself UTF-8 and CRLF-normalized.
        return download_response(content.encode("utf-8-sig"), meeting["title"], ".ics", "text/calendar; charset=utf-8")

    @app.delete("/api/v1/meetings/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None, tags=["会议与处理任务"], summary="永久删除会议及本地文件", responses={404: {"description": "会议不存在或已删除"}})
    async def delete_meeting(meeting_id: str) -> None:
        try:
            deleted = store.delete_meeting(meeting_id)
        except MeetingDeletionError as exc:
            raise HTTPException(status_code=500, detail={"code": "FILE_DELETE_FAILED", "message": str(exc)}) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="会议不存在或已被删除")

    if settings.api_access_token:
        def secured_openapi() -> dict[str, Any]:
            if app.openapi_schema:
                return app.openapi_schema
            schema = get_openapi(
                title=app.title,
                version=app.version,
                summary=app.summary,
                description=app.description,
                routes=app.routes,
                tags=app.openapi_tags,
            )
            schema.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "opaque deployment token",
                "description": "在后端 MEETINGMIND_API_TOKEN 中配置的部署级访问令牌。",
            }
            for path, path_item in schema.get("paths", {}).items():
                if path in PUBLIC_API_PATHS:
                    continue
                for method, operation in path_item.items():
                    if method.lower() not in {"get", "post", "patch", "put", "delete"}:
                        continue
                    operation["security"] = [{"BearerAuth": []}]
                    operation.setdefault("responses", {})["401"] = {"description": "缺少或提供了无效的访问令牌"}
            app.openapi_schema = schema
            return schema

        app.openapi = secured_openapi  # type: ignore[method-assign]

    return app


async def run_transcription_job(
    store: JsonStore | SqlAlchemyStore,
    meeting_id: str,
    settings: Settings,
) -> None:
    """Normalize, transcribe, and optionally diarize one uploaded meeting."""
    meeting = store.get_meeting(meeting_id)
    if meeting is None:
        return
    input_path = store.source_path(meeting_id, Path(meeting["original_filename"]).suffix.lower())
    model_name = os.getenv("MEETINGMIND_WHISPER_MODEL", "small")
    language = os.getenv("MEETINGMIND_WHISPER_LANGUAGE", "zh")

    def report_stage(stage: str) -> None:
        if stage == "DIARIZING":
            update_job(store, meeting_id, stage=stage, progress=78, message="WhisperX 对齐完成，正在执行说话人分离")
        elif stage == "ALIGNING":
            update_job(store, meeting_id, stage=stage, progress=67, message="WhisperX 转录完成，正在进行词级时间对齐")
        else:
            update_job(store, meeting_id, stage="TRANSCRIBING", progress=48, message="FFmpeg 规范化完成，正在执行 WhisperX 转录")

    try:
        update_job(store, meeting_id, stage="PREPROCESSING", progress=22, message="正在使用 FFmpeg 规范化音频")
        result = await asyncio.to_thread(
            transcribe_audio,
            input_path,
            store.working_dir(meeting_id),
            store.results_dir(meeting_id),
            model_name,
            language,
            stage_callback=report_stage,
            diarization_enabled=settings.diarization_enabled,
            hf_token=settings.hf_token,
            diarization_model=settings.diarization_model,
            num_speakers=meeting.get("expected_speakers"),
            max_audio_duration_minutes=settings.max_audio_duration_minutes,
        )
        current = store.get_meeting(meeting_id)
        if current is None:
            return
        current["duration_ms"] = result.duration_ms
        current["transcript"] = result.segments

        warnings: list[str] = []
        if int(current.get("job", {}).get("retry_count", 0)) > 0:
            warnings.append("该任务曾在服务启动时自动恢复；为保证产物一致性，已从原始音频重新执行。")
        if settings.diarization_enabled:
            if result.diarization_applied:
                diarization_status = "SUCCEEDED"
            else:
                diarization_status = "DEGRADED"
                warnings.append(result.diarization_warning or "说话人分离未完成，已保留转录并使用默认说话人标签。")
        else:
            diarization_status = "DISABLED"

        warning = " ".join(warnings) or None
        current["status"] = "SUCCEEDED_WITH_WARNINGS" if warning else "SUCCEEDED"
        current["job"].update({
            "stage": "SUCCEEDED",
            "progress": 100,
            "message": f"转录及说话人处理完成，共 {len(result.segments)} 个片段、{result.speaker_count} 位说话人",
            "warning": warning,
            "diarization_status": diarization_status,
            "speaker_count": result.speaker_count,
            "error": None,
            "error_code": None,
            "updated_at": utc_now(),
        })
        current["updated_at"] = utc_now()
        store.save_meeting(current)
    except AudioProcessingError as exc:
        finish_failed_job(store, meeting_id, str(exc), error_code=exc.code)
    except Exception as exc:
        finish_failed_job(store, meeting_id, f"未预期的音频处理错误: {exc}", error_code="UNEXPECTED_AUDIO_ERROR")


app = create_app()

