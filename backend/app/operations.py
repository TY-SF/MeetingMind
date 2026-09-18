from __future__ import annotations

import json
import shutil
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OperationalCheck:
    name: str
    status: str
    summary: str
    metrics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"连接失败（{type(exc.reason).__name__}）"
    return type(exc).__name__


def _validate_base_url(base_url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("监控地址必须是有效的 HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("监控地址不得包含凭据")
    if parsed.query or parsed.fragment:
        raise ValueError("监控地址不得包含查询参数或片段")
    return parsed


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _ssl_context(base_url: str, allow_insecure_localhost: bool) -> ssl.SSLContext | None:
    parsed = _validate_base_url(base_url)
    if parsed.scheme != "https":
        return None
    if not allow_insecure_localhost:
        return ssl.create_default_context()
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("跳过 TLS 证书验证只允许 localhost/回环地址")
    return ssl._create_unverified_context()  # noqa: SLF001 - explicit local-only operational option


def fetch_json(
    base_url: str,
    path: str,
    *,
    token: str | None,
    timeout_seconds: float,
    allow_insecure_localhost: bool,
) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "MeetingMind-Operational-Check/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(base_url.rstrip("/") + path, headers=headers)
    context = _ssl_context(base_url, allow_insecure_localhost)
    handlers: list[Any] = [_NoRedirect()]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    with opener.open(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("响应不是 JSON 对象")
    return payload


def check_http_endpoint(
    *,
    name: str,
    base_url: str,
    path: str,
    expected_status: str,
    token: str | None,
    timeout_seconds: float,
    allow_insecure_localhost: bool,
) -> OperationalCheck:
    try:
        payload = fetch_json(
            base_url,
            path,
            token=token,
            timeout_seconds=timeout_seconds,
            allow_insecure_localhost=allow_insecure_localhost,
        )
    except Exception as exc:
        return OperationalCheck(name, "fail", _safe_error(exc), {})
    actual = payload.get("status")
    if actual != expected_status:
        return OperationalCheck(name, "fail", f"状态为 {actual!s}，期望 {expected_status}", {})
    metrics = {
        key: payload[key]
        for key in ("redis", "worker_online", "worker_count", "queue_length", "started_job_count", "intermediate_job_count")
        if key in payload
    }
    if path.endswith("/queue") and payload.get("worker_online") is False:
        return OperationalCheck(name, "fail", "RQ Worker 不在线", metrics)
    return OperationalCheck(name, "pass", "检查通过", metrics)


def check_disk(data_dir: Path, warning_free_percent: float, critical_free_percent: float) -> OperationalCheck:
    try:
        usage = shutil.disk_usage(data_dir)
    except OSError as exc:
        return OperationalCheck("disk_space", "fail", _safe_error(exc), {})
    free_percent = round((usage.free / usage.total) * 100, 2) if usage.total else 0.0
    metrics = {"free_bytes": usage.free, "total_bytes": usage.total, "free_percent": free_percent}
    if free_percent < critical_free_percent:
        return OperationalCheck("disk_space", "fail", "数据盘可用空间低于严重阈值", metrics)
    if free_percent < warning_free_percent:
        return OperationalCheck("disk_space", "warn", "数据盘可用空间低于告警阈值", metrics)
    return OperationalCheck("disk_space", "pass", "数据盘空间充足", metrics)


def check_backup_freshness(data_dir: Path, max_age_hours: float) -> OperationalCheck:
    backup_dir = data_dir / "backups"
    archives = sorted(backup_dir.glob("*.zip"), key=lambda path: path.stat().st_mtime, reverse=True) if backup_dir.is_dir() else []
    if not archives:
        return OperationalCheck("backup_freshness", "warn", "尚无备份归档候选文件", {"archive_count": 0})
    latest = archives[0]
    age_hours = max(0.0, (utc_now().timestamp() - latest.stat().st_mtime) / 3600)
    metrics = {"archive_count": len(archives), "latest_archive": latest.name, "age_hours": round(age_hours, 2)}
    if age_hours > max_age_hours:
        return OperationalCheck("backup_freshness", "warn", "最新备份超过允许时效", metrics)
    return OperationalCheck("backup_freshness", "pass", "最新备份归档候选文件在时效范围内", metrics)


def check_logs(data_dir: Path, queue_backend: str) -> OperationalCheck:
    log_dir = data_dir / "logs"
    required = ["api.jsonl"] + (["worker.jsonl"] if queue_backend == "rq" else [])
    missing = [name for name in required if not (log_dir / name).is_file()]
    metrics = {"required_files": required, "missing_files": missing}
    if missing:
        return OperationalCheck("structured_logs", "warn", "结构化运行日志尚未全部生成", metrics)
    return OperationalCheck("structured_logs", "pass", "结构化运行日志可用", metrics)


def overall_status(checks: list[OperationalCheck]) -> str:
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        return "critical"
    if "warn" in statuses:
        return "warning"
    return "healthy"


def build_operational_report(
    *,
    base_url: str,
    data_dir: Path,
    token: str | None,
    queue_backend: str,
    timeout_seconds: float = 10,
    allow_insecure_localhost: bool = False,
    backup_max_age_hours: float = 26,
    disk_warning_free_percent: float = 15,
    disk_critical_free_percent: float = 5,
) -> dict[str, Any]:
    checks = [
        check_http_endpoint(
            name="api_liveness",
            base_url=base_url,
            path="/api/v1/health",
            expected_status="ok",
            token=None,
            timeout_seconds=timeout_seconds,
            allow_insecure_localhost=allow_insecure_localhost,
        ),
        check_http_endpoint(
            name="api_readiness",
            base_url=base_url,
            path="/api/v1/health/ready",
            expected_status="ready",
            token=None,
            timeout_seconds=timeout_seconds,
            allow_insecure_localhost=allow_insecure_localhost,
        ),
    ]
    if queue_backend == "rq":
        checks.append(
            check_http_endpoint(
                name="queue_readiness",
                base_url=base_url,
                path="/api/v1/health/queue",
                expected_status="ready",
                token=token,
                timeout_seconds=timeout_seconds,
                allow_insecure_localhost=allow_insecure_localhost,
            )
        )
    checks.extend(
        [
            check_disk(data_dir, disk_warning_free_percent, disk_critical_free_percent),
            check_backup_freshness(data_dir, backup_max_age_hours),
            check_logs(data_dir, queue_backend),
        ]
    )
    return {
        "schema_version": 1,
        "generated_at": utc_now().isoformat(),
        "project": "MeetingMind",
        "status": overall_status(checks),
        "checks": [check.as_dict() for check in checks],
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def update_monitor_state(state_path: Path, alert_path: Path, report: dict[str, Any]) -> bool:
    previous: dict[str, Any] = {}
    if state_path.is_file():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            previous = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            previous = {}
    status = str(report["status"])
    changed = previous.get("status") != status
    state = {
        "status": status,
        "updated_at": report["generated_at"],
        "changed_at": report["generated_at"] if changed else previous.get("changed_at", report["generated_at"]),
    }
    write_json_atomic(state_path, state)
    if changed and status != "healthy":
        alert_path.parent.mkdir(parents=True, exist_ok=True)
        alert = {
            "timestamp": report["generated_at"],
            "severity": status,
            "event": "operational_status_changed",
            "failed_checks": [
                check["name"] for check in report["checks"] if check["status"] in {"warn", "fail"}
            ],
        }
        with alert_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(alert, ensure_ascii=False) + "\n")
    return changed
