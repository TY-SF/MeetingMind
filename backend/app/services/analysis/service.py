from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any

from .date_parser import parse_due_date
from .provider import AnalysisProvider, AnalysisProviderError, AnalysisProviderResult, MeetingAnalysisDraft


class AnalysisInputTooLong(ValueError):
    code = "TRANSCRIPT_TOO_LONG"


@dataclass(frozen=True)
class NormalizedAnalysis:
    summary: str
    decisions: list[dict[str, Any]]
    action_items: list[dict[str, Any]]


class MeetingAnalysisService:
    def __init__(self, provider: AnalysisProvider, max_input_chars: int = 120_000) -> None:
        self.provider = provider
        self.max_input_chars = max_input_chars

    def analyze(self, *, transcript: list[dict[str, Any]], meeting_started_at: str, context: str = "") -> tuple[AnalysisProviderResult, NormalizedAnalysis]:
        serialized = "\n".join(str(segment.get("text", "")) for segment in transcript)
        if len(serialized) > self.max_input_chars:
            raise AnalysisInputTooLong(f"转录文本长度 {len(serialized)} 超过上限 {self.max_input_chars}")
        logger = logging.getLogger("meetingmind.analysis")
        last_error: AnalysisProviderError | None = None
        # At most two normal calls. Only transient provider failures are retried.
        for attempt in range(1, 3):
            try:
                result = self.provider.analyze(transcript=transcript, meeting_started_at=meeting_started_at, context=context)
                return result, normalize_draft(result.draft, meeting_started_at)
            except AnalysisProviderError as exc:
                last_error = exc
                if exc.code == "INVALID_MODEL_OUTPUT":
                    break
                if not exc.retryable or attempt == 2:
                    raise
                logger.warning("analysis_attempt_retrying", extra={"attempt": attempt, "error_code": exc.code})
                time.sleep(0.5 * attempt)

        # One, and only one, repair request. It receives the captured response,
        # not the full transcript again, minimizing repeated data exposure.
        if last_error and last_error.code == "INVALID_MODEL_OUTPUT" and last_error.raw_result and hasattr(self.provider, "repair"):
            try:
                repaired = self.provider.repair(last_error.raw_result)  # type: ignore[attr-defined]
                return repaired, normalize_draft(repaired.draft, meeting_started_at)
            except AnalysisProviderError:
                raise
        if last_error:
            raise last_error
        raise AnalysisProviderError("分析请求未返回结果", code="MODEL_REQUEST_FAILED")


def normalize_draft(draft: MeetingAnalysisDraft, meeting_started_at: str) -> NormalizedAnalysis:
    decisions = [
        {
            "content": item.content.strip(),
            "status": item.status,
            "evidence_text": item.evidence_text,
            "evidence_start_ms": item.evidence_start_ms,
        }
        for item in draft.decisions
    ]
    action_items = []
    for item in draft.action_items:
        parsed_date = parse_due_date(item.due_date_raw, meeting_started_at)
        action_items.append(
            {
                "content": item.content.strip(),
                "assignee": item.assignee,
                "assignee_status": item.assignee_status,
                "due_date_raw": item.due_date_raw,
                "due_at": parsed_date.due_at.isoformat() if parsed_date.due_at else None,
                "due_precision": parsed_date.precision,
                "due_date_status": item.due_date_status if parsed_date.status == "UNKNOWN" else parsed_date.status,
                "status": "TODO",
                "evidence_text": item.evidence_text,
                "evidence_start_ms": item.evidence_start_ms,
            }
        )
    return NormalizedAnalysis(summary=draft.summary.strip(), decisions=decisions, action_items=action_items)
