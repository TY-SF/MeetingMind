from __future__ import annotations

from app.main import create_app
from backend.tests.test_phase3_database import sample_meeting


def test_stage_transitions_persist_real_boundaries_and_durations(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(tmp_path / "missing.env"))
    app = create_app(data_dir=tmp_path)
    meeting = sample_meeting()
    meeting["created_at"] = "2026-09-09T02:00:00+00:00"
    meeting["updated_at"] = "2026-09-09T02:00:00+00:00"
    meeting["job"]["updated_at"] = "2026-09-09T02:00:00+00:00"
    app.state.store.save_meeting(meeting)

    transitions = [
        ("PREPROCESSING", "2026-09-09T02:00:01+00:00", "PROCESSING"),
        ("TRANSCRIBING", "2026-09-09T02:00:04+00:00", "PROCESSING"),
        ("SUCCEEDED", "2026-09-09T02:00:10+00:00", "SUCCEEDED_WITH_WARNINGS"),
    ]
    for stage, timestamp, status in transitions:
        meeting = app.state.store.get_meeting("meeting-db-1")
        assert meeting is not None
        meeting["status"] = status
        meeting["updated_at"] = timestamp
        meeting["job"].update({"stage": stage, "updated_at": timestamp})
        app.state.store.save_meeting(meeting)

    job = app.state.store.get_job("job-db-1")
    assert job is not None
    events = job["stage_events"]
    assert [event["stage"] for event in events] == ["QUEUED", "PREPROCESSING", "TRANSCRIBING"]
    assert [event["duration_ms"] for event in events] == [1000, 3000, 6000]
    assert [event["outcome"] for event in events] == ["COMPLETED", "COMPLETED", "COMPLETED"]
    assert all(event["finished_at"] is not None for event in events)


def test_retry_closes_interrupted_attempt_without_overwriting_history(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(tmp_path / "missing.env"))
    app = create_app(data_dir=tmp_path)
    meeting = sample_meeting()
    meeting["created_at"] = "2026-09-09T02:00:00+00:00"
    meeting["updated_at"] = "2026-09-09T02:00:00+00:00"
    meeting["job"].update({
        "stage": "TRANSCRIBING",
        "retry_count": 0,
        "updated_at": "2026-09-09T02:00:00+00:00",
    })
    app.state.store.save_meeting(meeting)

    meeting = app.state.store.get_meeting("meeting-db-1")
    assert meeting is not None
    meeting["updated_at"] = "2026-09-09T02:00:05+00:00"
    meeting["job"].update({
        "stage": "QUEUED",
        "retry_count": 1,
        "updated_at": "2026-09-09T02:00:05+00:00",
    })
    app.state.store.save_meeting(meeting)

    job = app.state.store.get_job("job-db-1")
    assert job is not None
    assert len(job["stage_events"]) == 2
    interrupted, retry = job["stage_events"]
    assert interrupted["stage"] == "TRANSCRIBING"
    assert interrupted["attempt"] == 0
    assert interrupted["duration_ms"] == 5000
    assert interrupted["outcome"] == "INTERRUPTED"
    assert retry["stage"] == "QUEUED"
    assert retry["attempt"] == 1
    assert retry["outcome"] == "RUNNING"
    assert retry["finished_at"] is None
