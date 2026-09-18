from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import Settings  # noqa: E402
from app.operations import build_operational_report, update_monitor_state, write_json_atomic  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MeetingMind 运行健康、备份时效、日志和磁盘检查")
    parser.add_argument("--base-url", default="https://localhost:8443")
    parser.add_argument("--allow-insecure-localhost", action="store_true", help="只允许 localhost 跳过本地 CA 校验")
    parser.add_argument("--timeout-seconds", type=float, default=10)
    parser.add_argument("--backup-max-age-hours", type=float, default=26)
    parser.add_argument("--disk-warning-free-percent", type=float, default=15)
    parser.add_argument("--disk-critical-free-percent", type=float, default=5)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--alerts", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.disk_critical_free_percent >= args.disk_warning_free_percent:
        print("错误：磁盘严重阈值必须小于告警阈值", file=sys.stderr)
        return 2
    settings = Settings.from_env(BACKEND)
    report_path = (args.report or settings.data_dir / "monitoring" / "latest.json").expanduser().resolve()
    state_path = (args.state or settings.data_dir / "monitoring" / "state.json").expanduser().resolve()
    alert_path = (args.alerts or settings.data_dir / "monitoring" / "alerts.jsonl").expanduser().resolve()
    try:
        report = build_operational_report(
            base_url=args.base_url,
            data_dir=settings.data_dir,
            token=settings.api_access_token,
            queue_backend=settings.queue_backend,
            timeout_seconds=args.timeout_seconds,
            allow_insecure_localhost=args.allow_insecure_localhost,
            backup_max_age_hours=args.backup_max_age_hours,
            disk_warning_free_percent=args.disk_warning_free_percent,
            disk_critical_free_percent=args.disk_critical_free_percent,
        )
        write_json_atomic(report_path, report)
        changed = update_monitor_state(state_path, alert_path, report)
    except Exception as exc:
        print(f"错误：运行检查无法完成（{type(exc).__name__}）", file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "changed": changed, "report": str(report_path)}, ensure_ascii=False))
    return {"healthy": 0, "warning": 1, "critical": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
