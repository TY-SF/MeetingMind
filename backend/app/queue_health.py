from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .store import JsonStore

logger = logging.getLogger("meetingmind.queue_health")
ACTIVE_STAGES = {"QUEUED", "PREPROCESSING", "TRANSCRIBING", "ALIGNING", "DIARIZING", "ANALYZING"}


@dataclass(frozen=True)
class QueueSnapshot:
    redis: str
    worker_online: bool
    worker_count: int
    queue_length: int
    intermediate_job_count: int
    started_job_count: int
    failed_job_ids: tuple[str, ...] = ()
    stale_intermediate_job_ids: tuple[str, ...] = ()


def _rq_objects(settings: Settings):
    from redis import Redis
    from rq import Queue, Worker

    connection = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=5)
    connection.ping()
    queue = Queue(settings.rq_queue_name, connection=connection)
    return connection, queue, Worker


def _online_workers(queue: Any, worker_class: Any) -> list[Any]:
    now = datetime.now(timezone.utc)
    online: list[Any] = []
    for worker in worker_class.all(connection=queue.connection, queue=queue):
        heartbeat = getattr(worker, "last_heartbeat", None)
        age = (now - heartbeat).total_seconds() if heartbeat else float("inf")
        # RQ refreshes the heartbeat primarily around dequeue/execution.
        # An idle SimpleWorker can legitimately be quiet for longer than 120s;
        # use its own TTL window rather than declaring a live worker dead.
        heartbeat_window = int(getattr(worker, "worker_ttl", 420)) + 60
        if worker.get_state() in {"starting", "idle", "busy"} and age <= heartbeat_window:
            online.append(worker)
    return online


def read_queue_snapshot(settings: Settings) -> QueueSnapshot:
    connection, queue, worker_class = _rq_objects(settings)
    online = _online_workers(queue, worker_class)
    intermediate_ids = queue.intermediate_queue.get_job_ids()
    stale_ids: list[str] = []
    for job_id in intermediate_ids:
        first_seen = queue.intermediate_queue.get_first_seen(job_id)
        if first_seen is not None:
            age = (datetime.now(timezone.utc) - first_seen).total_seconds()
            if age >= settings.rq_stale_job_seconds:
                stale_ids.append(job_id)
    return QueueSnapshot(
        redis="ok",
        worker_online=bool(online),
        worker_count=len(online),
        queue_length=len(queue),
        intermediate_job_count=len(intermediate_ids),
        started_job_count=len(queue.started_job_registry.get_job_ids()),
        failed_job_ids=tuple(queue.failed_job_registry.get_job_ids()),
        stale_intermediate_job_ids=tuple(stale_ids),
    )


def handle_rq_failure(job: Any, connection: Any, exc_type: Any, exc_value: Any, traceback: Any) -> None:
    """RQ callback that persists terminal failures outside the worker coroutine."""
    settings = Settings.from_env()
    if getattr(job, "retries_left", 0):
        return
    from .db import SqlAlchemyStore
    store = SqlAlchemyStore(settings.data_dir, settings.database_url)
    try:
        store.mark_job_failed_from_queue(
            job.id,
            f"RQ Worker 任务失败：{exc_value}",
            "QUEUE_JOB_FAILED",
        )
    finally:
        store.close()


def reconcile_queue_jobs(store: JsonStore, settings: Settings) -> int:
    """Make persisted job state agree with terminal RQ failures.

    RQ owns execution state; MySQL/JSON owns the user-facing state. When a
    worker dies before the application can persist FAILED, this bridge closes
    the open stage as INTERRUPTED and makes the public retry API available.
    """
    if settings.queue_backend != "rq":
        return 0
    try:
        connection, queue, _ = _rq_objects(settings)
        snapshot = read_queue_snapshot(settings)
        job_ids = set(snapshot.failed_job_ids)
        job_ids.update(snapshot.stale_intermediate_job_ids)
        # A worker can disappear before RQ writes its first_seen marker. In
        # that case use the durable business timestamp as the fallback clock.
        for job_id in queue.intermediate_queue.get_job_ids():
            business_job = store.get_job(job_id)
            if not business_job or business_job.get("stage") not in ACTIVE_STAGES:
                continue
            try:
                updated = datetime.fromisoformat(str(business_job["updated_at"]).replace("Z", "+00:00"))
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - updated).total_seconds() >= settings.rq_stale_job_seconds:
                    job_ids.add(job_id)
            except (KeyError, TypeError, ValueError):
                continue
        if not snapshot.worker_online:
            for job_id in queue.started_job_registry.get_job_ids():
                rq_job = queue.fetch_job(job_id)
                started_at = getattr(rq_job, "started_at", None) if rq_job else None
                if started_at and (datetime.now(timezone.utc) - started_at).total_seconds() >= settings.rq_stale_job_seconds:
                    job_ids.add(job_id)
        reconciled = 0
        for job_id in job_ids:
            business_job = store.get_job(job_id)
            if not business_job or business_job.get("stage") not in ACTIVE_STAGES:
                continue
            if store.mark_job_failed_from_queue(
                job_id,
                "RQ Worker 未完成任务，任务已中断；请重新启动 Worker 后重试",
                "QUEUE_JOB_INTERRUPTED",
            ):
                reconciled += 1
            queue.intermediate_queue.remove(job_id)
            try:
                queue.started_job_registry.remove(job_id, delete_job=False)
            except Exception:
                logger.debug("started_job_cleanup_failed", exc_info=True)
        return reconciled
    except Exception:
        logger.warning("queue_reconciliation_failed", exc_info=True)
        return 0
