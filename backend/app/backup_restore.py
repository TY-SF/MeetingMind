from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


MANIFEST_NAME = "manifest.json"
DATABASE_DUMP_NAME = "database/meetingmind.sql"
MEETINGS_ROOT_NAME = "meetings"
MANIFEST_SCHEMA_VERSION = 1
_SAFE_DATABASE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_SAFE_CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class BackupError(RuntimeError):
    """Raised when a backup cannot be safely created, verified, or restored."""


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise BackupError(f"无法读取备份文件：{path.name}") from exc
    return size, digest.hexdigest()


def _safe_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if not normalized or pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise BackupError(f"归档路径不安全：{path}")
    return pure.as_posix()


def _safe_join(root: Path, relative_path: str) -> Path:
    safe = _safe_relative_path(relative_path)
    root_resolved = root.resolve()
    target = (root_resolved / Path(*safe.split("/"))).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise BackupError(f"恢复路径越界：{relative_path}") from exc
    return target


def _assert_safe_directory(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if resolved.exists() and not resolved.is_dir():
        raise BackupError(f"{label}必须是目录：{path}")
    return resolved


def _iter_source_files(meetings_root: Path) -> list[tuple[str, Path]]:
    if not meetings_root.exists():
        raise BackupError(f"会议文件目录不存在：{meetings_root}")
    if not meetings_root.is_dir():
        raise BackupError(f"会议文件路径不是目录：{meetings_root}")
    records: list[tuple[str, Path]] = []
    for path in sorted(meetings_root.rglob("*")):
        if path.is_symlink():
            raise BackupError(f"会议文件目录不允许符号链接：{path.name}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise BackupError(f"会议文件目录包含不支持的特殊文件：{path.name}")
        relative = path.relative_to(meetings_root).as_posix()
        records.append((_safe_relative_path(relative), path))
    return records


def _copy_stable_file(source: Path, destination: Path) -> FileRecord:
    before_size, before_hash = sha256_file(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, destination)
    except OSError as exc:
        raise BackupError(f"无法复制会议文件：{source.name}") from exc
    after_size, after_hash = sha256_file(source)
    if (before_size, before_hash) != (after_size, after_hash):
        raise BackupError(f"备份期间会议文件发生变化：{source.name}")
    copied_size, copied_hash = sha256_file(destination)
    if (copied_size, copied_hash) != (before_size, before_hash):
        raise BackupError(f"复制后的会议文件校验失败：{source.name}")
    return FileRecord("", copied_size, copied_hash)


def _safe_process_error(result: subprocess.CompletedProcess[bytes], operation: str) -> BackupError:
    # Never include stderr: database clients may echo connection details or SQL.
    return BackupError(f"{operation}失败（外部命令退出码 {result.returncode}）")


def _validate_container_name(name: str) -> str:
    if not _SAFE_CONTAINER_NAME.fullmatch(name):
        raise BackupError("Docker 容器名称不安全")
    return name


def validate_database_name(name: str) -> str:
    if not _SAFE_DATABASE_NAME.fullmatch(name):
        raise BackupError("数据库名称不安全；仅允许字母、数字和下划线")
    return name


def _docker_shell(container: str, script: str, args: Sequence[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    container = _validate_container_name(container)
    command = ["docker", "exec", "-i", container, "sh", "-c", script, "meetingmind-backup", *args]
    try:
        return subprocess.run(command, input=input_bytes, capture_output=True, check=False)
    except OSError as exc:
        raise BackupError("无法调用 Docker；请确认 Docker Desktop 正在运行") from exc


def dump_mysql_from_container(container: str, database_name: str) -> bytes:
    database_name = validate_database_name(database_name)
    script = (
        "export MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\"; "
        "exec mysqldump --single-transaction --routines --events --triggers "
        '--hex-blob --no-tablespaces -uroot -- "$1"'
    )
    result = _docker_shell(container, script, [database_name])
    if result.returncode != 0:
        raise _safe_process_error(result, "MySQL 一致性导出")
    if not result.stdout.strip():
        raise BackupError("MySQL 导出为空")
    return result.stdout


def query_mysql_from_container(container: str, database_name: str, query: str) -> list[str]:
    database_name = validate_database_name(database_name)
    script = (
        "export MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\"; "
        'exec mysql --batch --skip-column-names -uroot -e "$2" "$1"'
    )
    result = _docker_shell(container, script, [database_name, query.encode().decode("utf-8")])
    if result.returncode != 0:
        raise _safe_process_error(result, "MySQL 校验查询")
    return [line for line in result.stdout.decode("utf-8", errors="strict").splitlines() if line]


def create_database_in_container(container: str, database_name: str) -> None:
    database_name = validate_database_name(database_name)
    quoted = "`" + database_name.replace("`", "``") + "`"
    query_mysql_from_container(container, database_name="mysql", query=f"CREATE DATABASE {quoted}")


def import_mysql_dump_in_container(container: str, database_name: str, dump: bytes) -> None:
    database_name = validate_database_name(database_name)
    script = (
        "export MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\"; "
        'exec mysql -uroot -- "$1"'
    )
    result = _docker_shell(container, script, [database_name], input_bytes=dump)
    if result.returncode != 0:
        raise _safe_process_error(result, "隔离 MySQL 恢复")


def drop_database_in_container(container: str, database_name: str) -> None:
    database_name = validate_database_name(database_name)
    quoted = "`" + database_name.replace("`", "``") + "`"
    query_mysql_from_container(container, database_name="mysql", query=f"DROP DATABASE {quoted}")


def _load_manifest_from_directory(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_NAME
    if not path.is_file():
        raise BackupError("备份缺少 manifest.json")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("manifest.json 无法读取或不是有效 JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise BackupError("不支持的备份 manifest 版本")
    return manifest


def _validate_manifest_structure(manifest: dict[str, Any]) -> tuple[list[FileRecord], FileRecord, list[str]]:
    database = manifest.get("database")
    if not isinstance(database, dict) or database.get("dump_path") != DATABASE_DUMP_NAME:
        raise BackupError("manifest 的数据库导出路径无效")
    try:
        database_record = FileRecord(
            DATABASE_DUMP_NAME,
            int(database["size"]),
            str(database["sha256"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BackupError("manifest 的数据库校验信息无效") from exc
    if database_record.size < 1 or not re.fullmatch(r"[0-9a-f]{64}", database_record.sha256):
        raise BackupError("manifest 的数据库校验信息无效")

    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        raise BackupError("manifest 缺少文件清单")
    files: list[FileRecord] = []
    seen: set[str] = set()
    for item in raw_files:
        if not isinstance(item, dict):
            raise BackupError("manifest 文件清单格式无效")
        try:
            relative = _safe_relative_path(str(item["path"]))
            size = int(item["size"])
            digest = str(item["sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupError("manifest 文件清单格式无效") from exc
        if not relative.startswith(MEETINGS_ROOT_NAME + "/"):
            raise BackupError("manifest 文件必须位于 meetings/ 下")
        if relative in seen or size < 0 or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BackupError("manifest 文件清单包含重复或无效条目")
        seen.add(relative)
        files.append(FileRecord(relative, size, digest))

    raw_ids = manifest.get("meeting_ids")
    if not isinstance(raw_ids, list) or any(not isinstance(value, str) or not value for value in raw_ids):
        raise BackupError("manifest 的会议 ID 清单无效")
    meeting_ids = sorted(set(raw_ids))
    if len(meeting_ids) != len(raw_ids):
        raise BackupError("manifest 的会议 ID 清单包含重复值")
    for meeting_id in meeting_ids:
        if len(PurePosixPath(meeting_id).parts) != 1 or _safe_relative_path(f"{meeting_id}/marker") != f"{meeting_id}/marker":
            raise BackupError("manifest 的会议 ID 可能导致路径越界")
    return files, database_record, meeting_ids


def _manifest_for_snapshot(
    *,
    database_dump: bytes,
    file_records: list[FileRecord],
    meeting_ids: list[str],
    database_name: str,
) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "project": "MeetingMind",
        "created_at": utc_now(),
        "consistency": {
            "database": "mysqldump --single-transaction",
            "file_policy": "stable hash before and after copy",
            "operator_requirement": "应用与 Worker 应在维护窗口停止写入期间执行备份",
        },
        "database": {
            "engine": "mysql",
            "database_name": database_name,
            "dump_path": DATABASE_DUMP_NAME,
            "size": len(database_dump),
            "sha256": hashlib.sha256(database_dump).hexdigest(),
        },
        "meetings_root": MEETINGS_ROOT_NAME,
        "meeting_ids": sorted(meeting_ids),
        "files": [record.as_dict() for record in sorted(file_records, key=lambda item: item.path)],
        "file_count": len(file_records),
        "total_file_bytes": sum(record.size for record in file_records),
        "excluded": ["logs", "release-check reports", "secrets", "model caches"],
    }


def _detect_meeting_ids(meetings_root: Path) -> list[str]:
    ids: list[str] = []
    for path in sorted(meetings_root.iterdir()):
        if path.is_symlink():
            raise BackupError(f"会议目录不允许符号链接：{path.name}")
        if path.is_dir():
            ids.append(path.name)
    return ids


def create_backup(
    *,
    data_dir: Path,
    output_path: Path,
    database_name: str,
    container: str = "meetingmind-mysql",
    overwrite: bool = False,
) -> Path:
    data_dir = _assert_safe_directory(data_dir, "数据根目录")
    meetings_root = data_dir / MEETINGS_ROOT_NAME
    output_path = output_path.expanduser().resolve()
    if output_path.suffix.lower() != ".zip":
        raise BackupError("备份输出必须使用 .zip 扩展名")
    if output_path.exists() and not overwrite:
        raise BackupError(f"备份目标已存在；如确认覆盖请显式使用 --overwrite：{output_path.name}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    database_name = validate_database_name(database_name)

    with tempfile.TemporaryDirectory(prefix="meetingmind-backup-", dir=str(output_path.parent)) as staging_name:
        staging = Path(staging_name)
        staged_meetings = staging / MEETINGS_ROOT_NAME
        meeting_ids = _detect_meeting_ids(meetings_root)
        db_ids_before = sorted(query_mysql_from_container(container, database_name, "SELECT id FROM meetings ORDER BY id"))
        if db_ids_before != sorted(meeting_ids):
            raise BackupError("数据库会议记录与 data/meetings 目录不一致；未创建备份，需先完成隔离核对")
        active_jobs = query_mysql_from_container(
            container,
            database_name,
            "SELECT COUNT(*) FROM processing_jobs WHERE status NOT IN ('SUCCEEDED','FAILED')",
        )
        if active_jobs and active_jobs[0] != "0":
            raise BackupError("仍有未完成的会议处理任务；请先停止写入并等待任务结束")

        source_records = _iter_source_files(meetings_root)
        file_records: list[FileRecord] = []
        for relative, source in source_records:
            destination = staged_meetings / Path(*relative.split("/"))
            record = _copy_stable_file(source, destination)
            file_records.append(FileRecord(f"{MEETINGS_ROOT_NAME}/{relative}", record.size, record.sha256))

        final_sources = _iter_source_files(meetings_root)
        if [relative for relative, _ in final_sources] != [relative for relative, _ in source_records]:
            raise BackupError("备份期间会议文件清单发生变化；请在维护窗口重试")
        for (relative, source), record in zip(final_sources, file_records, strict=True):
            size, digest = sha256_file(source)
            if (size, digest) != (record.size, record.sha256):
                raise BackupError(f"备份期间会议文件发生变化：{relative}")
        if _detect_meeting_ids(meetings_root) != meeting_ids:
            raise BackupError("备份期间会议目录清单发生变化；请在维护窗口重试")

        database_dump = dump_mysql_from_container(container, database_name)
        db_ids_after = sorted(query_mysql_from_container(container, database_name, "SELECT id FROM meetings ORDER BY id"))
        if db_ids_after != db_ids_before:
            raise BackupError("备份期间数据库会议记录发生变化；请在维护窗口重试")
        manifest = _manifest_for_snapshot(
            database_dump=database_dump,
            file_records=file_records,
            meeting_ids=meeting_ids,
            database_name=database_name,
        )
        manifest_path = staging / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "database").mkdir(parents=True, exist_ok=True)
        (staging / DATABASE_DUMP_NAME).write_bytes(database_dump)

        temporary_archive = output_path.with_name(output_path.stem + ".tmp" + output_path.suffix)
        if temporary_archive.exists():
            temporary_archive.unlink()
        try:
            with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for path in sorted(staging.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(staging).as_posix())
            verify_backup(temporary_archive)
            temporary_archive.replace(output_path)
        except Exception:
            temporary_archive.unlink(missing_ok=True)
            raise
    return output_path


def _open_backup(path: Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    path = path.expanduser().resolve()
    if path.is_dir():
        return path, None
    if not path.is_file() or path.suffix.lower() != ".zip":
        raise BackupError("备份必须是目录或 .zip 归档")
    temp = tempfile.TemporaryDirectory(prefix="meetingmind-verify-")
    root = Path(temp.name)
    try:
        with zipfile.ZipFile(path) as archive:
            seen_names: set[str] = set()
            for info in archive.infolist():
                name = _safe_relative_path(info.filename)
                if name in seen_names:
                    raise BackupError(f"归档包含重复路径：{name}")
                seen_names.add(name)
                if info.is_dir():
                    continue
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise BackupError("归档不允许符号链接")
                target = _safe_join(root, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
    except Exception:
        temp.cleanup()
        raise
    return root, temp


def _reject_unsafe_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise BackupError(f"备份目录不允许符号链接：{path.name}")
        if not path.is_file() and not path.is_dir():
            raise BackupError(f"备份目录包含不支持的特殊文件：{path.name}")


def verify_backup(path: Path) -> dict[str, Any]:
    root, temp = _open_backup(path)
    try:
        _reject_unsafe_tree(root)
        manifest = _load_manifest_from_directory(root)
        files, database_record, meeting_ids = _validate_manifest_structure(manifest)
        database_path = _safe_join(root, database_record.path)
        if not database_path.is_file():
            raise BackupError("备份缺少 MySQL 导出文件")
        database_size, database_hash = sha256_file(database_path)
        if (database_size, database_hash) != (database_record.size, database_record.sha256):
            raise BackupError("MySQL 导出文件校验失败")
        actual_paths: set[str] = set()
        for record in files:
            target = _safe_join(root, record.path)
            if not target.is_file():
                raise BackupError(f"备份缺少会议文件：{record.path}")
            size, digest = sha256_file(target)
            if (size, digest) != (record.size, record.sha256):
                raise BackupError(f"会议文件校验失败：{record.path}")
            actual_paths.add(record.path)
        meetings_root = _safe_join(root, MEETINGS_ROOT_NAME)
        actual_files = {
            f"{MEETINGS_ROOT_NAME}/{path.relative_to(meetings_root).as_posix()}"
            for path in meetings_root.rglob("*")
            if path.is_file()
        } if meetings_root.exists() else set()
        if actual_files != actual_paths:
            raise BackupError("备份包含未登记或缺失的会议文件")
        expected_files = {MANIFEST_NAME, database_record.path, *actual_paths}
        actual_tree_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
        if actual_tree_files != expected_files:
            raise BackupError("备份包含不在 manifest 中的额外文件")
        actual_ids = sorted(path.name for path in meetings_root.iterdir() if path.is_dir()) if meetings_root.exists() else []
        if actual_ids != meeting_ids:
            raise BackupError("manifest 的会议 ID 与文件目录不一致")
        if manifest.get("file_count") != len(files) or manifest.get("total_file_bytes") != sum(item.size for item in files):
            raise BackupError("manifest 文件统计不一致")
        return {
            "status": "verified",
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "meeting_count": len(meeting_ids),
            "file_count": len(files),
            "database_size": database_record.size,
            "archive": str(Path(path).name),
        }
    finally:
        if temp is not None:
            temp.cleanup()


def restore_backup(
    *,
    backup_path: Path,
    target_dir: Path,
    container: str | None = None,
    isolated_database: str | None = None,
    keep_isolated_database: bool = False,
) -> dict[str, Any]:
    target_dir = target_dir.expanduser().resolve()
    if target_dir.exists():
        raise BackupError(f"恢复目标已存在；为避免覆盖数据必须使用新的隔离目录：{target_dir}")
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any]
    root, temp = _open_backup(backup_path)
    created_database = False
    try:
        # Verify the source before materializing any restore output.
        result = verify_backup(backup_path)
        shutil.copytree(root, target_dir, symlinks=False)
        (target_dir / MEETINGS_ROOT_NAME).mkdir(exist_ok=True)
        restored_check = verify_backup(target_dir)
        result.update({"restored_to": str(target_dir), "restored_file_count": restored_check["file_count"]})
        if isolated_database:
            if not container:
                raise BackupError("指定隔离数据库时必须同时指定 Docker 容器")
            isolated_database = validate_database_name(isolated_database)
            dump = _safe_join(target_dir, DATABASE_DUMP_NAME).read_bytes()
            create_database_in_container(container, isolated_database)
            created_database = True
            import_mysql_dump_in_container(container, isolated_database, dump)
            rows = query_mysql_from_container(container, isolated_database, "SELECT id FROM meetings ORDER BY id")
            expected_ids = _load_manifest_from_directory(target_dir).get("meeting_ids", [])
            actual_ids = sorted(rows)
            if actual_ids != sorted(expected_ids):
                raise BackupError("隔离数据库中的会议 ID 与恢复文件不一致")
            result.update({"isolated_database": isolated_database, "database_meeting_count": len(actual_ids)})
    except Exception:
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        raise
    finally:
        if created_database and isolated_database and not keep_isolated_database:
            drop_database_in_container(container or "", isolated_database)
        if temp is not None:
            temp.cleanup()
    return result


def parse_simple_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_runtime_value(name: str, env_file: Path | None = None, default: str | None = None) -> str | None:
    if os.getenv(name):
        return os.getenv(name)
    values = parse_simple_env(env_file) if env_file else {}
    return values.get(name) or default
