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

from app.backup_restore import (  # noqa: E402
    BackupError,
    create_backup,
    restore_backup,
    resolve_runtime_value,
    verify_backup,
)


def _default_env_file() -> Path:
    return BACKEND / ".env" / "meetingmind.env"


def _default_data_dir(env_file: Path) -> Path:
    configured = resolve_runtime_value("MEETINGMIND_DATA_DIR", env_file, "data") or "data"
    value = Path(configured)
    return value if value.is_absolute() else ROOT / value


def _default_database_name(env_file: Path) -> str:
    return resolve_runtime_value("MYSQL_DATABASE", ROOT / ".env.compose", "meetingmind") or "meetingmind"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MeetingMind 数据库与会议文件备份/恢复工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup = subparsers.add_parser("backup", help="创建包含 MySQL dump 与会议文件的校验归档")
    backup.add_argument("--output", type=Path, required=True, help="输出 .zip 路径")
    backup.add_argument("--data-dir", type=Path, help="运行数据根目录，默认读取配置")
    backup.add_argument("--database", help="MySQL 数据库名")
    backup.add_argument("--container", default="meetingmind-mysql", help="MySQL Docker 容器名")
    backup.add_argument("--env-file", type=Path, default=_default_env_file())
    backup.add_argument("--overwrite", action="store_true")

    verify = subparsers.add_parser("verify", help="验证归档、manifest、文件与数据库 dump 哈希")
    verify.add_argument("backup", type=Path)

    restore = subparsers.add_parser("restore", help="恢复到全新的隔离目录，可选恢复到隔离 MySQL 数据库")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--target-dir", type=Path, required=True)
    restore.add_argument("--container", help="用于隔离数据库恢复的 Docker 容器名")
    restore.add_argument("--isolated-database", help="隔离数据库名，建议使用 meetingmind_restore_ 前缀")
    restore.add_argument("--keep-isolated-database", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "backup":
            env_file = args.env_file.expanduser().resolve()
            data_dir = (args.data_dir or _default_data_dir(env_file)).expanduser().resolve()
            database_name = args.database or _default_database_name(env_file)
            archive = create_backup(
                data_dir=data_dir,
                output_path=args.output,
                database_name=database_name,
                container=args.container,
                overwrite=args.overwrite,
            )
            print(json.dumps({"status": "created", "archive": str(archive)}, ensure_ascii=False))
            return 0
        if args.command == "verify":
            print(json.dumps(verify_backup(args.backup), ensure_ascii=False))
            return 0
        if args.command == "restore":
            if bool(args.container) != bool(args.isolated_database):
                raise BackupError("--container 与 --isolated-database 必须成对使用")
            result = restore_backup(
                backup_path=args.backup,
                target_dir=args.target_dir,
                container=args.container,
                isolated_database=args.isolated_database,
                keep_isolated_database=args.keep_isolated_database,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        raise BackupError("未知命令")
    except BackupError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
