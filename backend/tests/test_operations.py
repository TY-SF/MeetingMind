from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import operations
from app.operations import OperationalCheck, build_operational_report, update_monitor_state


def test_insecure_tls_is_restricted_to_localhost() -> None:
    with pytest.raises(ValueError, match="只允许"):
        operations._ssl_context("https://example.com", True)
    with pytest.raises(ValueError, match="不得包含凭据"):
        operations._validate_base_url("https://user:password@example.com")
    assert operations._ssl_context("https://localhost:8443", True) is not None


def test_operational_report_contains_metrics_but_not_access_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "api.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "logs" / "worker.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / "latest.zip").write_bytes(b"backup")

    def fake_endpoint(**kwargs):
        if kwargs["name"] == "queue_readiness":
            return OperationalCheck("queue_readiness", "pass", "检查通过", {"worker_online": True, "queue_length": 0})
        return OperationalCheck(kwargs["name"], "pass", "检查通过", {})

    monkeypatch.setattr(operations, "check_http_endpoint", fake_endpoint)
    report = build_operational_report(
        base_url="https://localhost:8443",
        data_dir=tmp_path,
        token="must-not-appear",
        queue_backend="rq",
        allow_insecure_localhost=True,
    )

    assert report["status"] == "healthy"
    assert "must-not-appear" not in json.dumps(report, ensure_ascii=False)


def test_monitor_alerts_only_on_nonhealthy_transition(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    alerts = tmp_path / "alerts.jsonl"
    warning = {
        "generated_at": "2026-09-18T00:00:00+00:00",
        "status": "warning",
        "checks": [{"name": "backup_freshness", "status": "warn"}],
    }
    healthy = {
        "generated_at": "2026-09-18T01:00:00+00:00",
        "status": "healthy",
        "checks": [{"name": "backup_freshness", "status": "pass"}],
    }

    assert update_monitor_state(state, alerts, warning) is True
    assert update_monitor_state(state, alerts, warning) is False
    assert len(alerts.read_text(encoding="utf-8").splitlines()) == 1
    assert update_monitor_state(state, alerts, healthy) is True
    assert len(alerts.read_text(encoding="utf-8").splitlines()) == 1
    assert json.loads(state.read_text(encoding="utf-8"))["status"] == "healthy"
