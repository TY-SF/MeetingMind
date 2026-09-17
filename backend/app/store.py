from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JsonStore:
    """Small atomic JSON store used until the MySQL repository is introduced."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or Path(
            os.getenv("MEETINGMIND_DATA_DIR", Path(__file__).parents[2] / "data")
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Keep every mutable runtime artifact below the configured data root.
        # Older releases used a sibling `<project>/meetings` directory; migrate it
        # explicitly with scripts/migrate_runtime_layout.py before upgrading.
        self.meetings_dir = self.data_dir / "meetings"
        self.meetings_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "meetings.json"
        self._lock = threading.RLock()

    def list_meetings(self) -> list[dict[str, Any]]:
        with self._lock:
            meetings = self._read()
        return sorted(meetings, key=lambda item: item["created_at"], reverse=True)

    def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        with self._lock:
            return next((item for item in self._read() if item["id"] == meeting_id), None)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            for meeting in self._read():
                if meeting["job"]["id"] == job_id:
                    return meeting["job"] | {"meeting_id": meeting["id"]}
        return None

    def mark_job_failed_from_queue(self, job_id: str, error: str, error_code: str) -> bool:
        now = datetime.now(timezone.utc)
        with self._lock:
            meetings = self._read()
            for meeting in meetings:
                job = meeting.get("job") or {}
                if job.get("id") != job_id or meeting.get("status") in {"SUCCEEDED", "SUCCEEDED_WITH_WARNINGS", "FAILED"}:
                    continue
                for event in reversed(job.get("stage_events", [])):
                    if event.get("finished_at") is None:
                        started = datetime.fromisoformat(event["started_at"])
                        event["finished_at"] = now.isoformat()
                        event["duration_ms"] = max(0, round((now - started).total_seconds() * 1000))
                        event["outcome"] = "INTERRUPTED"
                        break
                job.update({
                    "stage": "FAILED",
                    "progress": 0,
                    "message": "队列任务未完成，处理已中断；可以重新处理",
                    "error": error,
                    "error_code": error_code,
                    "finished_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                })
                meeting["status"] = "FAILED"
                meeting["updated_at"] = now.isoformat()
                self._write(meetings)
                return True
        return False

    def save_meeting(self, meeting: dict[str, Any]) -> None:
        with self._lock:
            meetings = self._read()
            for index, existing in enumerate(meetings):
                if existing["id"] == meeting["id"]:
                    meetings[index] = meeting
                    break
            else:
                meetings.append(meeting)
            self._write(meetings)

    def delete_meeting(self, meeting_id: str) -> bool:
        with self._lock:
            meetings = self._read()
            remaining = [item for item in meetings if item["id"] != meeting_id]
            if len(remaining) == len(meetings):
                return False
            self._write(remaining)
            return True

    def meeting_dir(self, meeting_id: str) -> Path:
        path = self.meetings_dir / meeting_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def source_path(self, meeting_id: str, suffix: str) -> Path:
        path = self.meeting_dir(meeting_id) / "source"
        path.mkdir(parents=True, exist_ok=True)
        return path / f"original{suffix}"

    def working_dir(self, meeting_id: str) -> Path:
        path = self.meeting_dir(meeting_id) / "working"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def results_dir(self, meeting_id: str) -> Path:
        path = self.meeting_dir(meeting_id) / "results"
        path.mkdir(parents=True, exist_ok=True)
        return path


    def exports_dir(self, meeting_id: str) -> Path:
        path = self.meeting_dir(meeting_id) / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return payload if isinstance(payload, list) else []

    def _write(self, meetings: list[dict[str, Any]]) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(meetings, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
