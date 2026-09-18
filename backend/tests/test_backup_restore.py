from __future__ import annotations

import json
import sys
import warnings
import zipfile
from pathlib import Path

import pytest

from app import backup_restore
from app.backup_restore import BackupError, create_backup, restore_backup, verify_backup


def _seed_data(root: Path) -> None:
    meetings = root / "meetings"
    for meeting_id, content in (("meeting-a", b"audio-a"), ("meeting-b", b"audio-b")):
        (meetings / meeting_id / "source").mkdir(parents=True)
        (meetings / meeting_id / "results").mkdir(parents=True)
        (meetings / meeting_id / "source" / "original.mp3").write_bytes(content)
        (meetings / meeting_id / "results" / "transcript.json").write_text("{\"segments\": []}", encoding="utf-8")


def _fake_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
    dump = b"-- fake mysqldump\nCREATE TABLE meetings (id varchar(36));\n"

    def query(_container: str, _database: str, sql: str) -> list[str]:
        if "COUNT(*)" in sql:
            return ["0"]
        return ["meeting-a", "meeting-b"]

    monkeypatch.setattr(backup_restore, "dump_mysql_from_container", lambda *_args: dump)
    monkeypatch.setattr(backup_restore, "query_mysql_from_container", query)


def test_create_verify_and_restore_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    _seed_data(data_dir)
    _fake_mysql(monkeypatch)

    archive = create_backup(
        data_dir=data_dir,
        output_path=tmp_path / "backup.zip",
        database_name="meetingmind",
        container="fake-container",
    )
    assert archive.is_file()
    verification = verify_backup(archive)
    assert verification["status"] == "verified"
    assert verification["meeting_count"] == 2

    restored = restore_backup(backup_path=archive, target_dir=tmp_path / "restored")
    assert restored["restored_file_count"] == 4
    assert (tmp_path / "restored" / "meetings" / "meeting-a" / "source" / "original.mp3").read_bytes() == b"audio-a"
    assert verify_backup(tmp_path / "restored")["status"] == "verified"


def test_verify_rejects_tampered_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    _seed_data(data_dir)
    _fake_mysql(monkeypatch)
    archive = create_backup(data_dir=data_dir, output_path=tmp_path / "backup.zip", database_name="meetingmind")

    tampered = tmp_path / "tampered"
    with zipfile.ZipFile(archive) as source:
        source.extractall(tampered)
    target = tampered / "meetings" / "meeting-a" / "source" / "original.mp3"
    target.write_bytes(b"changed")
    with pytest.raises(BackupError, match="校验失败"):
        verify_backup(tampered)


def test_verify_rejects_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    _seed_data(data_dir)
    _fake_mysql(monkeypatch)
    archive = create_backup(data_dir=data_dir, output_path=tmp_path / "backup.zip", database_name="meetingmind")

    incomplete = tmp_path / "incomplete"
    with zipfile.ZipFile(archive) as source:
        source.extractall(incomplete)
    (incomplete / "meetings" / "meeting-b" / "source" / "original.mp3").unlink()
    with pytest.raises(BackupError, match="缺少会议文件"):
        verify_backup(incomplete)


def test_verify_rejects_duplicate_archive_path(tmp_path: Path) -> None:
    archive = tmp_path / "duplicate.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("manifest.json", "{}")
            handle.writestr("manifest.json", "{}")
    with pytest.raises(BackupError, match="重复路径"):
        verify_backup(archive)


def test_backup_rejects_database_directory_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    _seed_data(data_dir)
    monkeypatch.setattr(
        backup_restore,
        "query_mysql_from_container",
        lambda *_args: ["0"] if "COUNT(*)" in _args[-1] else ["meeting-a"],
    )
    monkeypatch.setattr(backup_restore, "dump_mysql_from_container", lambda *_args: b"dump")
    with pytest.raises(BackupError, match="数据库会议记录"):
        create_backup(data_dir=data_dir, output_path=tmp_path / "backup.zip", database_name="meetingmind")
    assert not (tmp_path / "backup.zip").exists()


def test_verify_rejects_path_traversal_archive(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../manifest.json", "{}")
    with pytest.raises(BackupError, match="归档路径不安全"):
        verify_backup(archive)


def test_restore_refuses_existing_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    _seed_data(data_dir)
    _fake_mysql(monkeypatch)
    archive = create_backup(data_dir=data_dir, output_path=tmp_path / "backup.zip", database_name="meetingmind")
    target = tmp_path / "existing"
    target.mkdir()
    with pytest.raises(BackupError, match="恢复目标已存在"):
        restore_backup(backup_path=archive, target_dir=target)


def test_manifest_does_not_contain_transcript_content_or_secret_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    _seed_data(data_dir)
    _fake_mysql(monkeypatch)
    archive = create_backup(data_dir=data_dir, output_path=tmp_path / "backup.zip", database_name="meetingmind")
    extract = tmp_path / "extract"
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(extract)
    manifest = json.loads((extract / "manifest.json").read_text(encoding="utf-8"))
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert "segments" not in serialized
    assert "OPENAI_API_KEY" not in serialized
    assert "MYSQL_PASSWORD" not in serialized
