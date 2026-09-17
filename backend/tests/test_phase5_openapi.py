from __future__ import annotations

from app.main import create_app


def test_openapi_groups_public_contract_and_diarization_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(tmp_path / "missing.env"))
    app = create_app(data_dir=tmp_path)
    spec = app.openapi()

    assert spec["info"]["title"] == "MeetingMind API"
    assert spec["info"]["version"] == "0.5.0"
    assert {tag["name"] for tag in spec["tags"]} == {
        "健康检查",
        "会议与处理任务",
        "AI 分析与审核",
        "说话人与导出",
    }
    assert "/api/v1/meetings" in spec["paths"]
    assert "/api/v1/jobs/{job_id}" in spec["paths"]
    assert "/api/v1/meetings/{meeting_id}/analysis" in spec["paths"]
    assert "/api/v1/meetings/{meeting_id}/speakers" in spec["paths"]
    assert "/api/v1/meetings/{meeting_id}/exports/calendar" in spec["paths"]

    upload = spec["paths"]["/api/v1/meetings"]["post"]
    assert upload["responses"]["202"]["description"] == "Successful Response"
    assert upload["tags"] == ["会议与处理任务"]
    upload_schema_name = upload["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"].rsplit("/", 1)[-1]
    assert "data_processing_confirmed" in spec["components"]["schemas"][upload_schema_name]["properties"]

    analysis = spec["paths"]["/api/v1/meetings/{meeting_id}/analysis"]["post"]
    analysis_schema_name = analysis["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
    assert "analysis_data_confirmed" in spec["components"]["schemas"][analysis_schema_name]["properties"]

    schema = spec["components"]["schemas"]["ProcessingJob"]
    assert "diarization_status" in schema["properties"]
    assert "speaker_count" in schema["properties"]
    assert "stage_events" in schema["properties"]
