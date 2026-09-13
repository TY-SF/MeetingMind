from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


@dataclass(frozen=True)
class ParsedDueDate:
    due_at: datetime | None
    precision: str | None
    status: str


def parse_due_date(raw: str | None, meeting_started_at: str | datetime) -> ParsedDueDate:
    if not raw or not raw.strip():
        return ParsedDueDate(None, None, "UNKNOWN")
    anchor = _as_shanghai(meeting_started_at)
    value = raw.strip().replace("星期", "周")
    target: date | None = None

    full = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if full:
        try:
            target = date(*map(int, full.groups()))
        except ValueError:
            return ParsedDueDate(None, None, "AMBIGUOUS")
    elif match := re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?", value):
        month, day = map(int, match.groups())
        year = anchor.year
        try:
            target = date(year, month, day)
        except ValueError:
            return ParsedDueDate(None, None, "AMBIGUOUS")
    elif value in {"今天", "今日"}:
        target = anchor.date()
    elif value == "明天":
        target = anchor.date() + timedelta(days=1)
    elif value == "后天":
        target = anchor.date() + timedelta(days=2)
    elif match := re.search(r"(本周|这周|下周)\s*([一二三四五六日天])", value):
        prefix, weekday = match.groups()
        week_start = anchor.date() - timedelta(days=anchor.weekday())
        offset = 7 if prefix == "下周" else 0
        target = week_start + timedelta(days=offset + WEEKDAYS[weekday])
    elif "月底" in value:
        last_day = calendar.monthrange(anchor.year, anchor.month)[1]
        target = date(anchor.year, anchor.month, last_day)
    else:
        return ParsedDueDate(None, None, "AMBIGUOUS")

    local_due = datetime.combine(target, time(23, 59, 59), tzinfo=SHANGHAI)
    return ParsedDueDate(local_due.astimezone(timezone.utc), "DAY", "CONFIRMED")


def _as_shanghai(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)
