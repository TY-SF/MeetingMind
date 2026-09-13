from __future__ import annotations

from datetime import datetime, timezone

from app.services.analysis.date_parser import parse_due_date
from app.services.analysis.provider import ActionItemDraft, DecisionDraft, MeetingAnalysisDraft
from app.services.analysis.service import MeetingAnalysisService


class FakeProvider:
    def analyze(self, *, transcript, meeting_started_at, context=""):
        from app.services.analysis.provider import AnalysisProviderResult

        draft = MeetingAnalysisDraft(
            summary="确认接口交付安排。",
            decisions=[DecisionDraft(content="确认先完成接口文档", status="CONFIRMED", evidence_text="先完成接口文档", evidence_start_ms=1000)],
            action_items=[ActionItemDraft(content="补齐接口文档", assignee="张三", assignee_status="EXPLICIT", due_date_raw="下周五", due_date_status="EXPLICIT", evidence_text="张三负责下周五前补齐", evidence_start_ms=2000)],
        )
        return AnalysisProviderResult(draft, {"fake": True}, "fake", "test-model", "test-v1")


def test_parse_relative_dates_from_meeting_anchor() -> None:
    result = parse_due_date("下周五", "2026-09-09T10:00:00+08:00")
    assert result.status == "CONFIRMED"
    assert result.precision == "DAY"
    assert result.due_at == datetime(2026, 9, 18, 15, 59, 59, tzinfo=timezone.utc)


def test_ambiguous_date_is_not_invented() -> None:
    result = parse_due_date("尽快", "2026-09-09T10:00:00+08:00")
    assert result.status == "AMBIGUOUS"
    assert result.due_at is None


def test_analysis_service_normalizes_due_date_and_todo_status() -> None:
    service = MeetingAnalysisService(FakeProvider(), max_input_chars=1000)
    provider_result, normalized = service.analyze(
        transcript=[{"speaker": "张三", "start_ms": 2000, "text": "张三负责下周五前补齐"}],
        meeting_started_at="2026-09-09T10:00:00+08:00",
    )
    assert provider_result.provider == "fake"
    assert normalized.action_items[0]["status"] == "TODO"
    assert normalized.action_items[0]["due_at"] == "2026-09-18T15:59:59+00:00"


def test_analysis_service_rejects_oversized_transcript() -> None:
    service = MeetingAnalysisService(FakeProvider(), max_input_chars=3)
    try:
        service.analyze(transcript=[{"text": "abcd"}], meeting_started_at="2026-09-09T10:00:00+08:00")
    except Exception as exc:
        assert getattr(exc, "code", None) == "TRANSCRIPT_TOO_LONG"
    else:
        raise AssertionError("expected transcript length error")



def _analysis_payload(*, summary: str = "第一版摘要", decision: str = "采用方案 A") -> dict:
    return {
        "summary": summary,
        "decisions": [
            {
                "id": "decision-1",
                "content": decision,
                "status": "CONFIRMED",
                "evidence_text": "确认采用方案 A",
                "evidence_start_ms": 1000,
            }
        ],
        "action_items": [
            {
                "id": "action-1",
                "content": "补齐接口文档",
                "assignee": "张三",
                "assignee_status": "EXPLICIT",
                "due_date_raw": "2026-09-18",
                "due_at": "2026-09-18T15:59:59+00:00",
                "due_precision": "DAY",
                "due_date_status": "CONFIRMED",
                "status": "TODO",
                "evidence_text": "张三负责补齐接口文档",
                "evidence_start_ms": 2000,
            }
        ],
    }


def test_repository_persists_replaces_and_versions_analysis(tmp_path) -> None:
    from app.db import Base, OptimisticLockError, SqlAlchemyMeetingRepository, create_db_engine, create_session_factory
    from app.db.models import MeetingAnalysisRecord
    from backend.tests.test_phase3_database import sample_meeting

    engine = create_db_engine(f"sqlite:///{tmp_path / 'analysis.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)

    with sessions.begin() as session:
        repository = SqlAlchemyMeetingRepository(session)
        repository.save_meeting(sample_meeting())
        first = repository.save_analysis(
            "meeting-db-1",
            _analysis_payload(),
            raw_result={"response_id": "response-1"},
            provider="openai",
            model="test-model",
            prompt_version="meeting_analysis_v1",
        )
        assert first["version"] == 1

    with sessions.begin() as session:
        repository = SqlAlchemyMeetingRepository(session)
        second_payload = _analysis_payload(summary="人工审核摘要", decision="改用方案 B")
        second_payload["decisions"][0]["id"] = "decision-2"
        second_payload["action_items"] = []
        second = repository.save_analysis("meeting-db-1", second_payload, expected_version=1)
        assert second["version"] == 2
        assert second["summary"] == "人工审核摘要"
        assert [item["content"] for item in second["decisions"]] == ["改用方案 B"]
        assert second["action_items"] == []
        assert second["provider"] == "openai"
        persisted = session.get(MeetingAnalysisRecord, second["id"])
        assert persisted is not None
        assert persisted.ai_raw_result == {"response_id": "response-1"}

    with sessions.begin() as session:
        repository = SqlAlchemyMeetingRepository(session)
        try:
            repository.save_analysis("meeting-db-1", _analysis_payload(), expected_version=1)
        except OptimisticLockError:
            pass
        else:
            raise AssertionError("expected optimistic lock conflict")


def _seed_analysis_api(app) -> None:
    from backend.tests.test_phase3_database import sample_meeting

    meeting = sample_meeting()
    meeting["transcript"] = [
        {"id": "segment-1", "speaker": "张三", "start_ms": 0, "end_ms": 1200, "text": "确认采用方案 A"}
    ]
    meeting["status"] = "SUCCEEDED_WITH_WARNINGS"
    app.state.store.save_meeting(meeting)
    app.state.store.save_analysis(
        meeting["id"],
        _analysis_payload(),
        raw_result={"response_id": "response-1"},
        provider="openai",
        model="test-model",
        prompt_version="meeting_analysis_v1",
    )


def test_patch_analysis_updates_whole_draft_and_rejects_stale_version(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import create_app

    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(tmp_path / "missing.env"))
    app = create_app(data_dir=tmp_path)
    _seed_analysis_api(app)
    payload = _analysis_payload(summary="人工确认后的摘要", decision="人工确认采用方案 B")
    payload["version"] = 1

    with TestClient(app) as client:
        response = client.patch("/api/v1/meetings/meeting-db-1/analysis", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["version"] == 2
        assert body["summary"] == "人工确认后的摘要"
        assert body["provider"] == "openai"

        stale = client.patch("/api/v1/meetings/meeting-db-1/analysis", json=payload)
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "ANALYSIS_VERSION_CONFLICT"


def test_missing_api_key_does_not_change_transcript_or_job_state(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import create_app

    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    app = create_app(data_dir=tmp_path)
    _seed_analysis_api(app)
    before = app.state.store.get_meeting("meeting-db-1")

    with TestClient(app) as client:
        response = client.post("/api/v1/meetings/meeting-db-1/analysis")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "MODEL_AUTH_ERROR"

    after = app.state.store.get_meeting("meeting-db-1")
    assert after is not None and before is not None
    assert after["transcript"] == before["transcript"]
    assert after["status"] == before["status"]
    assert after["job"]["stage"] == before["job"]["stage"]



def test_openai_error_mapping_uses_stable_codes() -> None:
    from app.services.analysis.provider import _translate_openai_error

    AuthenticationError = type("AuthenticationError", (Exception,), {})
    RateLimitError = type("RateLimitError", (Exception,), {})
    APITimeoutError = type("APITimeoutError", (Exception,), {})

    assert _translate_openai_error(AuthenticationError()).code == "MODEL_AUTH_ERROR"
    assert _translate_openai_error(RateLimitError()).code == "MODEL_RATE_LIMITED"
    timeout = _translate_openai_error(APITimeoutError())
    assert timeout.code == "MODEL_TIMEOUT"
    assert timeout.retryable is True


def test_patch_rejects_confirmed_due_date_without_timezone(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import create_app

    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(tmp_path / "missing.env"))
    app = create_app(data_dir=tmp_path)
    _seed_analysis_api(app)
    payload = _analysis_payload()
    payload["version"] = 1
    payload["action_items"][0]["due_at"] = "2026-09-18T18:00:00"

    with TestClient(app) as client:
        response = client.patch("/api/v1/meetings/meeting-db-1/analysis", json=payload)
        assert response.status_code == 422



def test_analysis_retries_transient_provider_failure(monkeypatch) -> None:
    from app.services.analysis.provider import AnalysisProviderError, AnalysisProviderResult, MeetingAnalysisDraft

    class FlakyProvider:
        def __init__(self) -> None:
            self.calls = 0

        def analyze(self, *, transcript, meeting_started_at, context=""):
            self.calls += 1
            if self.calls == 1:
                raise AnalysisProviderError("temporary", code="MODEL_TIMEOUT", retryable=True)
            return AnalysisProviderResult(MeetingAnalysisDraft(summary="ok", decisions=[], action_items=[]), {"ok": True}, "fake", "model", "v1")

    monkeypatch.setattr("app.services.analysis.service.time.sleep", lambda _seconds: None)
    provider = FlakyProvider()
    result, normalized = MeetingAnalysisService(provider).analyze(transcript=[{"text": "内容"}], meeting_started_at="2026-09-09T10:00:00+08:00")
    assert provider.calls == 2
    assert result.raw_result == {"ok": True}
    assert normalized.summary == "ok"


def test_analysis_uses_one_schema_repair_attempt() -> None:
    from app.services.analysis.provider import AnalysisProviderError, AnalysisProviderResult, MeetingAnalysisDraft

    class RepairProvider:
        def __init__(self) -> None:
            self.repair_calls = 0

        def analyze(self, *, transcript, meeting_started_at, context=""):
            raise AnalysisProviderError("invalid", code="INVALID_MODEL_OUTPUT", retryable=True, raw_result={"bad": "json"})

        def repair(self, raw_result):
            self.repair_calls += 1
            assert raw_result == {"bad": "json"}
            return AnalysisProviderResult(MeetingAnalysisDraft(summary="repaired", decisions=[], action_items=[]), {"fixed": True}, "fake", "model", "json_repair_v1")

    provider = RepairProvider()
    result, normalized = MeetingAnalysisService(provider).analyze(transcript=[{"text": "内容"}], meeting_started_at="2026-09-09T10:00:00+08:00")
    assert provider.repair_calls == 1
    assert result.prompt_version == "json_repair_v1"
    assert normalized.summary == "repaired"
