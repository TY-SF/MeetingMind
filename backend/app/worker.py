from __future__ import annotations

import asyncio
import logging

from .config import Settings
from .db import SqlAlchemyStore
from .main import run_transcription_job
from .observability import configure_logging


def process_meeting_job(meeting_id: str) -> None:
    """RQ entry point. Must stay synchronous so RQ workers can invoke it."""
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    logger = logging.getLogger("meetingmind.worker")
    store = SqlAlchemyStore(settings.data_dir, settings.database_url)
    logger.info("rq_worker_job_started", extra={"meeting_id": meeting_id})
    try:
        asyncio.run(run_transcription_job(store, meeting_id, settings))
    finally:
        store.close()
