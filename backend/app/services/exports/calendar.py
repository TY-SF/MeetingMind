from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

EXPORTABLE_DUE_STATUSES = {"EXPLICIT", "CONFIRMED"}
EVENT_DURATION = timedelta(hours=1)


def render_ics(meeting: dict[str, Any], generated_at: datetime | None = None) -> str:
    """Create Outlook-compatible RFC 5545 VEVENT entries for reliable due dates.

    MeetingMind action items are represented as transparent one-hour calendar events
    ending at their due time. VEVENT is used instead of VTODO because Outlook's
    calendar importer does not reliably accept calendars containing task components.
    """
    analysis = meeting.get("analysis")
    if not analysis:
        raise ValueError("会议尚未生成分析结果")
    now = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = format_utc(now)
    components = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//MeetingMind//Meeting Action Items//ZH-CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_ics('MeetingMind 待办事项')}",
        f"X-WR-CALDESC:{escape_ics('由 MeetingMind 导出的会议待办日历')}",
    ]
    for index, item in enumerate(analysis.get("action_items") or []):
        if item.get("due_date_status") not in EXPORTABLE_DUE_STATUSES or not item.get("due_at"):
            continue
        due_at = parse_datetime(item["due_at"])
        starts_at = due_at - EVENT_DURATION
        digest = hashlib.sha256(
            f"{meeting['id']}:{analysis.get('version', 1)}:{item.get('id', index)}".encode("utf-8")
        ).hexdigest()[:24]
        description_parts = []
        if item.get("assignee"):
            description_parts.append(f"负责人：{item['assignee']}")
        if item.get("evidence_text"):
            description_parts.append(f"原文证据：{item['evidence_text']}")
        components.extend([
            "BEGIN:VEVENT",
            f"UID:{digest}@meetingmind.local",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{format_utc(starts_at)}",
            f"DTEND:{format_utc(due_at)}",
            f"SUMMARY:{escape_ics('【待办】' + item['content'])}",
            f"DESCRIPTION:{escape_ics('；'.join(description_parts))}",
            f"STATUS:{ics_status(item.get('status', 'TODO'))}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ])
    components.append("END:VCALENDAR")
    return "\r\n".join(fold_line(line) for line in components) + "\r\n"


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("待办 due_at 必须包含时区")
    return parsed.astimezone(timezone.utc)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def escape_ics(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\r\n", "\\n").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def ics_status(status: str) -> str:
    """Map MeetingMind task states to values allowed on VEVENT."""
    return {
        "DONE": "CONFIRMED",
        "CANCELLED": "CANCELLED",
        "IN_PROGRESS": "TENTATIVE",
    }.get(status, "TENTATIVE")


def fold_line(line: str, limit: int = 75) -> str:
    """Fold content lines to at most 75 UTF-8 octets, including continuation space."""
    chunks: list[str] = []
    current = ""
    current_bytes = 0
    chunk_limit = limit
    for character in line:
        width = len(character.encode("utf-8"))
        if current and current_bytes + width > chunk_limit:
            chunks.append(current)
            current = character
            current_bytes = width
            # A folded continuation line starts with one whitespace octet.
            chunk_limit = limit - 1
        else:
            current += character
            current_bytes += width
    chunks.append(current)
    return "\r\n ".join(chunks)
