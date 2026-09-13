from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class DecisionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    status: Literal["CONFIRMED", "PROPOSED", "DISPUTED", "UNRESOLVED"]
    evidence_text: str | None
    evidence_start_ms: int | None


class ActionItemDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    assignee: str | None
    assignee_status: Literal["EXPLICIT", "INFERRED", "UNKNOWN"]
    due_date_raw: str | None
    due_date_status: Literal["EXPLICIT", "AMBIGUOUS", "UNKNOWN", "CONFIRMED"]
    evidence_text: str | None
    evidence_start_ms: int | None


class MeetingAnalysisDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    decisions: list[DecisionDraft]
    action_items: list[ActionItemDraft]


class AnalysisProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "MODEL_ERROR", retryable: bool = False, raw_result: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.raw_result = raw_result


@dataclass(frozen=True)
class AnalysisProviderResult:
    draft: MeetingAnalysisDraft
    raw_result: dict[str, Any]
    provider: str
    model: str
    prompt_version: str


class AnalysisProvider(Protocol):
    def analyze(self, *, transcript: list[dict[str, Any]], meeting_started_at: str, context: str = "") -> AnalysisProviderResult: ...


class OpenAIAnalysisProvider:
    """OpenAI Responses API adapter. Instantiation is safe without an API key."""

    provider_name = "openai"
    prompt_version = "meeting_analysis_v1"

    def __init__(self, *, api_key: str | None = None, model: str | None = None, base_url: str | None = None, timeout_seconds: float = 120) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
        self.model = model or os.getenv("LLM_MODEL", "gpt-5.6-terra")
        self.base_url = base_url or os.getenv("LLM_BASE_URL")
        self.timeout_seconds = timeout_seconds

    def analyze(self, *, transcript: list[dict[str, Any]], meeting_started_at: str, context: str = "") -> AnalysisProviderResult:
        if not self.api_key:
            raise AnalysisProviderError("未配置 OpenAI API Key", code="MODEL_AUTH_ERROR")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise AnalysisProviderError("未安装 openai Python SDK", code="OPENAI_SDK_MISSING") from exc

        client_kwargs: dict[str, Any] = {"api_key": self.api_key, "timeout": self.timeout_seconds}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        client = OpenAI(**client_kwargs)
        transcript_text = "\n".join(
            f"[{segment.get('start_ms', 0)}ms] {segment.get('speaker', 'SPEAKER_00')}: {segment.get('text', '')}"
            for segment in transcript
        )
        system_prompt = _read_prompt("meeting_analysis_v1.md")
        user_content = f"会议发生时间：{meeting_started_at}\n会议背景：{context or '无'}\n\n带时间戳转录：\n{transcript_text}"
        try:
            response = client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                text_format=MeetingAnalysisDraft,
            )
        except Exception as exc:
            raise _translate_openai_error(exc) from exc
        raw = _response_to_dict(response)
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise AnalysisProviderError("OpenAI 未返回可解析的结构化结果", code="INVALID_MODEL_OUTPUT", retryable=True, raw_result=raw)
        return AnalysisProviderResult(parsed, raw, self.provider_name, self.model, self.prompt_version)

    def repair(self, raw_result: dict[str, Any]) -> AnalysisProviderResult:
        """One schema-only repair attempt for a captured invalid model response."""
        if not self.api_key:
            raise AnalysisProviderError("未配置 OpenAI API Key", code="MODEL_AUTH_ERROR")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise AnalysisProviderError("未安装 openai Python SDK", code="OPENAI_SDK_MISSING") from exc
        client_kwargs: dict[str, Any] = {"api_key": self.api_key, "timeout": self.timeout_seconds}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        try:
            response = OpenAI(**client_kwargs).responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": _read_prompt("json_repair_v1.md")},
                    {"role": "user", "content": json.dumps(raw_result, ensure_ascii=False)},
                ],
                text_format=MeetingAnalysisDraft,
            )
        except Exception as exc:
            raise _translate_openai_error(exc) from exc
        raw = _response_to_dict(response)
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise AnalysisProviderError("模型输出修复后仍不符合 Schema", code="INVALID_MODEL_OUTPUT", raw_result=raw)
        return AnalysisProviderResult(parsed, raw, self.provider_name, self.model, "json_repair_v1")


def _read_prompt(name: str) -> str:
    return (Path(__file__).parent / "prompts" / name).read_text(encoding="utf-8")


def _response_to_dict(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        # Parsed Responses objects contain SDK generic variants that Pydantic warns
        # about during JSON serialization even though the response is valid. The
        # raw snapshot is an audit artifact; suppress only those serializer warnings.
        value = response.model_dump(mode="json", warnings=False)
        return value if isinstance(value, dict) else {"response": value}
    if isinstance(response, dict):
        return response
    return {"response": json.loads(response.model_dump_json())} if hasattr(response, "model_dump_json") else {"response": str(response)}


def _translate_openai_error(exc: Exception) -> AnalysisProviderError:
    """Map SDK failures to stable application error codes without leaking secrets."""
    error_name = type(exc).__name__
    message = str(exc)
    if error_name in {"AuthenticationError", "PermissionDeniedError"}:
        return AnalysisProviderError("OpenAI 认证或权限校验失败", code="MODEL_AUTH_ERROR")
    if error_name == "RateLimitError":
        return AnalysisProviderError("OpenAI 请求受到限流", code="MODEL_RATE_LIMITED", retryable=True)
    if error_name in {"APITimeoutError", "TimeoutException"}:
        return AnalysisProviderError("OpenAI 请求超时", code="MODEL_TIMEOUT", retryable=True)
    if error_name in {"APIConnectionError", "ConnectError"}:
        return AnalysisProviderError("无法连接 OpenAI API", code="MODEL_CONNECTION_ERROR", retryable=True)
    if error_name in {"NotFoundError", "BadRequestError", "UnprocessableEntityError"}:
        return AnalysisProviderError(
            f"OpenAI 拒绝了分析请求: {message}",
            code="MODEL_REQUEST_INVALID",
        )
    return AnalysisProviderError(
        f"OpenAI 分析请求失败: {message}",
        code="MODEL_REQUEST_FAILED",
        retryable=True,
    )
