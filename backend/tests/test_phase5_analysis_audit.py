from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.analysis import MeetingAnalysisDraft, normalize_draft
from backend.tests.test_phase3_database import sample_meeting


MEETING_STARTED_AT = "2026-09-09T10:00:00+08:00"


def _model_draft() -> dict:
    return {
        "summary": "确认接口交付安排。",
        "decisions": [
            {
                "content": "确认先完成接口文档",
                "status": "CONFIRMED",
                "evidence_text": "先完成接口文档",
                "evidence_start_ms": 1000,
            }
        ],
        "action_items": [
            {
                "content": "补齐接口文档",
                "assignee": "张三",
                "assignee_status": "EXPLICIT",
                "due_date_raw": "下周五",
                "due_date_status": "EXPLICIT",
                "evidence_text": "张三负责下周五前补齐",
                "evidence_start_ms": 2000,
            }
        ],
    }


def _provider_snapshot(parsed: object) -> dict:
    return {
        "id": "resp-private-id",
        "usage": {"input_tokens": 999, "output_tokens": 111},
        "instructions": "private system instructions",
        "user": "private user payload",
        "output": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "parsed": parsed,
                        "text": "provider raw text must not be returned",
                    }
                ],
            }
        ],
    }


def _seed(app, *, raw_result: dict | None = None) -> None:
    meeting = sample_meeting()
    meeting["meeting_started_at"] = MEETING_STARTED_AT
    meeting["status"] = "SUCCEEDED_WITH_WARNINGS"
    meeting["transcript"] = [
        {
            "id": "segment-audit-1",
            "speaker": "张三",
            "speaker_label": "SPEAKER_00",
            "start_ms": 0,
            "end_ms": 3000,
            "text": "先完成接口文档，张三负责下周五前补齐。",
        }
    ]
    app.state.store.save_meeting(meeting)

    draft = MeetingAnalysisDraft.model_validate(_model_draft())
    normalized = normalize_draft(draft, MEETING_STARTED_AT)
    app.state.store.save_analysis(
        meeting["id"],
        {
            "summary": normalized.summary,
            "decisions": normalized.decisions,
            "action_items": normalized.action_items,
        },
        raw_result=raw_result,
        provider="openai",
        model="test-model",
        prompt_version="meeting_analysis_v1",
    )


def _app(tmp_path, monkeypatch, *, raw_result: dict | None = None):
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(tmp_path / "missing.env"))
    app = create_app(data_dir=tmp_path)
    _seed(app, raw_result=raw_result)
    return app


def test_analysis_audit_matches_original_and_does_not_leak_provider_response(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path, monkeypatch, raw_result=_provider_snapshot(_model_draft()))

    with TestClient(app) as client:
        response = client.get("/api/v1/meetings/meeting-db-1/analysis/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["has_changes"] is False
    assert body["changed_fields"] == []
    assert body["ai_original"] == body["current"]
    assert body["current_version"] == 1
    assert body["provider"] == "openai"

    serialized = response.text
    for forbidden in ("usage", "instructions", "private user payload", "resp-private-id", "provider raw text"):
        assert forbidden not in serialized


def test_analysis_audit_reports_human_summary_change(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path, monkeypatch, raw_result=_provider_snapshot(_model_draft()))

    with TestClient(app) as client:
        current = client.get("/api/v1/meetings/meeting-db-1/analysis").json()
        update = {
            "summary": "人工确认后的摘要。",
            "decisions": current["decisions"],
            "action_items": current["action_items"],
            "version": current["version"],
        }
        saved = client.patch("/api/v1/meetings/meeting-db-1/analysis", json=update)
        assert saved.status_code == 200

        audit = client.get("/api/v1/meetings/meeting-db-1/analysis/audit")

    assert audit.status_code == 200
    body = audit.json()
    assert body["has_changes"] is True
    assert body["changed_fields"] == ["摘要"]
    assert body["ai_original"]["summary"] == "确认接口交付安排。"
    assert body["current"]["summary"] == "人工确认后的摘要。"
    assert body["current_version"] == 2


def test_analysis_audit_returns_null_original_for_unparseable_legacy_snapshot(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path, monkeypatch, raw_result=_provider_snapshot({"legacy": "unsupported"}))

    with TestClient(app) as client:
        response = client.get("/api/v1/meetings/meeting-db-1/analysis/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["ai_original"] is None
    assert body["current"]["summary"] == "确认接口交付安排。"
    assert body["has_changes"] is False
    assert body["changed_fields"] == []


def test_analysis_audit_requires_existing_analysis(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(tmp_path / "missing.env"))
    app = create_app(data_dir=tmp_path)
    app.state.store.save_meeting(sample_meeting())

    with TestClient(app) as client:
        missing_analysis = client.get("/api/v1/meetings/meeting-db-1/analysis/audit")
        missing_meeting = client.get("/api/v1/meetings/not-found/analysis/audit")

    assert missing_analysis.status_code == 404
    assert missing_meeting.status_code == 404
