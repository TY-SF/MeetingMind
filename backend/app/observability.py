from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("meetingmind_request_id", default=None)


class JsonFormatter(logging.Formatter):
    """Emit compact, machine-readable operational logs without request bodies."""

    reserved = frozenset(logging.makeLogRecord({}).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in self.reserved and key not in {"message", "asctime", "exc_info", "exc_text", "stack_info"}:
                # Never use this logger for transcript or raw model payloads.
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    logger = logging.getLogger("meetingmind")
    if getattr(logger, "_meetingmind_configured", False):
        logger.setLevel(level.upper())
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False
    logger._meetingmind_configured = True  # type: ignore[attr-defined]


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):  # type: ignore[override]
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        logger = logging.getLogger("meetingmind.http")
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "http_request_completed",
                extra={"method": request.method, "path": request.url.path, "status_code": response.status_code, "duration_ms": round((time.perf_counter() - started) * 1000)},
            )
            return response
        except Exception:
            logger.exception("http_request_failed", extra={"method": request.method, "path": request.url.path, "duration_ms": round((time.perf_counter() - started) * 1000)})
            raise
        finally:
            request_id_var.reset(token)
