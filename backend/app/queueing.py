from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from .config import Settings

logger = logging.getLogger("meetingmind.queue")


class QueueUnavailableError(RuntimeError):
    """Raised when the required Redis/RQ dispatch path is not available."""


def enqueue_processing_job(
    *,
    settings: Settings,
    meeting_id: str,
    internal_job_id: str,
    inline_submit: Callable[[], asyncio.Task[Any]] | None = None,
) -> str | None:
    """Dispatch one durable processing job.

    Redis/RQ is the normal execution path. The explicit `inline` backend exists
    only for isolated test runs and short-lived local troubleshooting; it is
    never selected implicitly when Redis cannot be reached.
    """
    if settings.queue_backend == "inline":
        if inline_submit is None:
            raise QueueUnavailableError("inline 队列缺少本地任务执行器")
        inline_submit()
        return None
    if settings.queue_backend != "rq":
        raise QueueUnavailableError(f"不支持的队列后端：{settings.queue_backend}")
    try:
        from redis import Redis
        from rq import Queue, Retry

        connection = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=5)
        connection.ping()
        queue = Queue(settings.rq_queue_name, connection=connection, default_timeout=settings.rq_job_timeout_seconds)
        job = queue.enqueue(
            "app.worker.process_meeting_job",
            meeting_id,
            job_id=internal_job_id,
            job_timeout=settings.rq_job_timeout_seconds,
            result_ttl=settings.rq_result_ttl_seconds,
            failure_ttl=settings.rq_failure_ttl_seconds,
            retry=Retry(max=2, interval=[30, 120]),
            # RQ invokes this callback after terminal failures (including
            # worker-abandonment cleanup), allowing the durable DB state to
            # become FAILED instead of remaining indefinitely QUEUED.
            on_failure="app.queue_health.handle_rq_failure",
        )
        logger.info("rq_job_enqueued", extra={"meeting_id": meeting_id, "job_id": internal_job_id, "rq_job_id": job.id, "queue": settings.rq_queue_name})
        return job.id
    except QueueUnavailableError:
        raise
    except Exception as exc:
        logger.warning("rq_dispatch_failed", extra={"meeting_id": meeting_id, "job_id": internal_job_id, "error_type": type(exc).__name__})
        raise QueueUnavailableError("Redis/RQ 不可用，任务未进入队列") from exc


