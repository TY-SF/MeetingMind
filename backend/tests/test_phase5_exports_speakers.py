from __future__ import annotations

from codecs import BOM_UTF8
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.exports import render_ics, render_markdown


def seeded_meeting() -> dict:
    now = "2026-09-09T10:00:00+00:00"
    return {
        "id": "meeting-phase5",
        "title": "第五阶段验证会议",
        "original_filename": "meeting.mp3",
        "mime_type": "audio/mpeg",
        "file_size": 2048,
        "duration_ms": 72000,
        "meeting_started_at": now,
        "participants": ["张三", "李四"],
        "context": "验证导出和说话人映射",
        "status": "SUCCEEDED",
        "created_at": now,
        "updated_at": now,
        "transcript": [
            {"id": "unused-1", "speaker": "SPEAKER_00", "start_ms": 0, "end_ms": 3000, "text": "我来整理文档。"},
            {"id": "unused-2", "speaker": "SPEAKER_01", "start_ms": 4000, "end_ms": 7000, "text": "周五前完成。"},
        ],
        "job": {
            "id": "job-phase5",
            "stage": "SUCCEEDED",
            "progress": 100,
            "error": None,
            "warning": None,
            "updated_at": now,
        },
    }


def analysis_payload() -> dict:
    return {
        "summary": "确认文档整理安排。",
        "decisions": [
            {"id": "decision-phase5", "content": "周五前完成文档", "status": "CONFIRMED", "evidence_text": "周五前完成", "evidence_start_ms": 4000}
        ],
        "action_items": [
            {
                "id": "action-explicit",
                "content": "整理文档",
                "assignee": "张三",
                "assignee_status": "EXPLICIT",
                "due_date_raw": "周五前",
                "due_at": "2026-09-11T15:59:59+00:00",
                "due_precision": "DAY",
                "due_date_status": "CONFIRMED",
                "status": "TODO",
                "evidence_text": "我来整理文档，周五前完成",
                "evidence_start_ms": 0,
            },
            {
                "id": "action-ambiguous",
                "content": "继续讨论预算",
                "assignee": None,
                "assignee_status": "UNKNOWN",
                "due_date_raw": "尽快",
                "due_at": None,
                "due_precision": None,
                "due_date_status": "AMBIGUOUS",
                "status": "TODO",
                "evidence_text": None,
                "evidence_start_ms": None,
            },
        ],
    }


def seed(app) -> None:
    app.state.store.save_meeting(seeded_meeting())
    app.state.store.save_analysis(
        "meeting-phase5",
        analysis_payload(),
        raw_result={"response_id": "phase5"},
        provider="openai",
        model="test-model",
        prompt_version="meeting_analysis_v1",
    )


def test_markdown_uses_reviewed_analysis_and_transcript() -> None:
    meeting = seeded_meeting()
    meeting["analysis"] = analysis_payload() | {"version": 2, "provider": "openai", "model": "test-model", "prompt_version": "v1"}
    content = render_markdown(meeting)
    assert "# 第五阶段验证会议" in content
    assert "## 关键结论" in content
    assert "整理文档" in content
    assert "**[00:00:00] SPEAKER_00**" in content
    assert "- 分析版本：2" in content


def test_ics_exports_only_reliable_due_dates() -> None:
    meeting = seeded_meeting()
    meeting["analysis"] = analysis_payload() | {"version": 1}
    content = render_ics(meeting, datetime(2026, 9, 9, tzinfo=timezone.utc))
    assert content.count("BEGIN:VEVENT") == 1
    assert "BEGIN:VTODO" not in content
    assert "DTSTART:20260911T145959Z" in content
    assert "DTEND:20260911T155959Z" in content
    assert "SUMMARY:【待办】整理文档" in content
    assert "X-WR-CALNAME:MeetingMind 待办事项" in content
    assert "继续讨论预算" not in content
    assert content.endswith("\r\n")
    assert all(len(line.encode("utf-8")) <= 75 for line in content.split("\r\n"))


def test_speaker_mapping_persists_raw_label_and_survives_meeting_save(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(tmp_path / "missing.env"))
    app = create_app(data_dir=tmp_path)
    seed(app)
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/meetings/meeting-phase5/speakers",
            json={"mappings": [{"speaker_label": "SPEAKER_00", "speaker_name": "张三"}]},
        )
        assert response.status_code == 200
        segment = response.json()["transcript"][0]
        assert segment["speaker"] == "张三"
        assert segment["speaker_label"] == "SPEAKER_00"

        # A later status/meeting save must not turn the raw label into the display name.
        saved = app.state.store.get_meeting("meeting-phase5")
        app.state.store.save_meeting(saved)
        persisted = client.get("/api/v1/meetings/meeting-phase5").json()["transcript"][0]
        assert persisted["speaker"] == "张三"
        assert persisted["speaker_label"] == "SPEAKER_00"


def test_export_endpoints_return_downloads_without_persisting_derived_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(tmp_path / "missing.env"))
    app = create_app(data_dir=tmp_path)
    seed(app)
    with TestClient(app) as client:
        markdown = client.get("/api/v1/meetings/meeting-phase5/exports/markdown")
        assert markdown.status_code == 200
        assert markdown.headers["content-type"].startswith("text/markdown")
        assert "filename*=UTF-8''" in markdown.headers["content-disposition"]
        assert "第五阶段验证会议" in markdown.text

        calendar = client.get("/api/v1/meetings/meeting-phase5/exports/calendar")
        assert calendar.status_code == 200
        assert calendar.headers["content-type"].startswith("text/calendar")
        assert calendar.content.startswith(BOM_UTF8)
        assert calendar.content[len(BOM_UTF8):].decode("utf-8").count("BEGIN:VEVENT") == 1

    export_dir = tmp_path.parent / "meetings" / "meeting-phase5" / "exports"
    assert not export_dir.exists()


def test_rejects_unknown_speaker_and_calendar_without_reliable_date(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(tmp_path / "missing.env"))
    app = create_app(data_dir=tmp_path)
    seed(app)
    with TestClient(app) as client:
        unknown = client.patch(
            "/api/v1/meetings/meeting-phase5/speakers",
            json={"mappings": [{"speaker_label": "SPEAKER_99", "speaker_name": "某人"}]},
        )
        assert unknown.status_code == 422
        assert unknown.json()["detail"]["code"] == "UNKNOWN_SPEAKER_LABEL"

        current = app.state.store.get_analysis("meeting-phase5")
        current["action_items"] = []
        app.state.store.save_analysis("meeting-phase5", current, expected_version=current["version"])
        no_calendar = client.get("/api/v1/meetings/meeting-phase5/exports/calendar")
        assert no_calendar.status_code == 409
        assert no_calendar.json()["detail"]["code"] == "NO_EXPORTABLE_ACTION_ITEMS"

