from __future__ import annotations

import json
import logging
from pathlib import Path

from app.observability import JsonFormatter, configure_logging


def _reset_meetingmind_logger() -> None:
    logger = logging.getLogger("meetingmind")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_json_formatter_redacts_credentials() -> None:
    formatter = JsonFormatter()
    credential_url = "redis://user:" + "password@localhost/0"
    record = logging.LogRecord(
        name="meetingmind.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Authorization: Bearer real-token MYSQL_PASSWORD=do-not-log %s",
        args=(credential_url,),
        exc_info=None,
    )
    record.api_key = "secret-value"
    record.context = {"token": "nested-secret", "safe": "visible"}

    payload = json.loads(formatter.format(record))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "real-token" not in serialized
    assert "do-not-log" not in serialized
    assert "secret-value" not in serialized
    assert "nested-secret" not in serialized
    assert credential_url not in serialized
    assert payload["context"]["safe"] == "visible"


def test_configure_logging_rotates_file_and_bounds_backups(tmp_path: Path) -> None:
    _reset_meetingmind_logger()
    log_file = tmp_path / "logs" / "api.jsonl"
    configure_logging("INFO", log_file=log_file, max_bytes=1024, backup_count=2)
    logger = logging.getLogger("meetingmind.rotation")

    for index in range(80):
        logger.info("rotation_event", extra={"index": index, "authorization": "Bearer never-write-this"})
    for handler in logging.getLogger("meetingmind").handlers:
        handler.flush()

    files = sorted(log_file.parent.glob("api.jsonl*"))
    assert log_file in files
    assert len(files) <= 3
    for path in files:
        assert path.stat().st_size <= 1400
        for line in path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            assert payload["message"] == "rotation_event"
            assert payload["authorization"] == "[REDACTED]"
            assert "never-write-this" not in line
    _reset_meetingmind_logger()
