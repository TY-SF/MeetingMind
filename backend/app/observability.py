from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("meetingmind_request_id", default=None)

_SENSITIVE_KEY_PARTS = ("authorization", "api_key", "apikey", "password", "secret", "token", "credential")
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(OPENAI_API_KEY|LLM_API_KEY|HF_TOKEN|MYSQL_PASSWORD|MYSQL_ROOT_PASSWORD|MEETINGMIND_API_TOKEN)\s*[=:]\s*([^\s,;]+)"
)
_URL_CREDENTIAL_PATTERN = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^\s:/@]+:)([^\s@]+)(@)")


def _redact_text(value: str) -> str:
    value = _BEARER_PATTERN.sub(r"\1[REDACTED]", value)
    value = _ASSIGNMENT_PATTERN.sub(r"\1=[REDACTED]", value)
    return _URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]\3", value)


def _sanitize(value: Any, key: str | None = None) -> Any:
    if key and any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {str(item_key): _sanitize(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """Emit compact operational JSON without request bodies or known credentials."""

    reserved = frozenset(logging.makeLogRecord({}).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact_text(record.getMessage()),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in self.reserved and key not in {"message", "asctime", "exc_info", "exc_text", "stack_info"}:
                # Application code must never log transcripts or raw model payloads.
                # This layer additionally redacts credential-shaped fields and text.
                payload[key] = _sanitize(value, key)
        if record.exc_info:
            payload["exception"] = _redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def _make_stream_handler(formatter: logging.Formatter) -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler._meetingmind_kind = "stream"  # type: ignore[attr-defined]
    return handler


def _make_file_handler(
    log_file: Path,
    formatter: logging.Formatter,
    max_bytes: int,
    backup_count: int,
) -> logging.Handler:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_file,
        maxBytes=max(1024, max_bytes),
        backupCount=max(1, backup_count),
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    handler._meetingmind_kind = "file"  # type: ignore[attr-defined]
    handler._meetingmind_path = str(log_file.resolve())  # type: ignore[attr-defined]
    return handler


def configure_logging(
    level: str,
    *,
    log_file: Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure bounded JSON logs for the MeetingMind logger hierarchy.

    The file handler is intentionally process-local. API and RQ worker use separate
    files so Windows rotation does not require multi-process file locking.
    """

    logger = logging.getLogger("meetingmind")
    formatter = JsonFormatter()
    desired_path = str(log_file.expanduser().resolve()) if log_file else None

    stream_handlers = [
        handler for handler in logger.handlers if getattr(handler, "_meetingmind_kind", None) == "stream"
    ]
    if not stream_handlers:
        logger.addHandler(_make_stream_handler(formatter))
    else:
        for handler in stream_handlers:
            handler.setFormatter(formatter)

    for handler in list(logger.handlers):
        if getattr(handler, "_meetingmind_kind", None) != "file":
            continue
        if desired_path and getattr(handler, "_meetingmind_path", None) == desired_path:
            handler.setFormatter(formatter)
            if isinstance(handler, RotatingFileHandler):
                handler.maxBytes = max(1024, max_bytes)
                handler.backupCount = max(1, backup_count)
            break
        logger.removeHandler(handler)
        handler.close()
    else:
        if log_file is not None:
            logger.addHandler(_make_file_handler(log_file, formatter, max_bytes, backup_count))

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
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                },
            )
            return response
        except Exception:
            logger.exception(
                "http_request_failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                },
            )
            raise
        finally:
            request_id_var.reset(token)
