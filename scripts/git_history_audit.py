from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from pathlib import Path

from repository_audit import MAX_FILE_BYTES, ROOT, SECRET_PATTERNS


def git_bytes(*args: str, input_data: bytes | None = None) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], input=input_data)


def historical_object_paths() -> dict[str, set[str]]:
    paths: dict[str, set[str]] = defaultdict(set)
    for raw_line in git_bytes("rev-list", "--objects", "--all").splitlines():
        oid, separator, raw_path = raw_line.partition(b" ")
        if separator and raw_path:
            paths[oid.decode("ascii")].add(raw_path.decode("utf-8", errors="replace"))
    return paths


def object_metadata(object_ids: list[str]) -> dict[str, tuple[str, int]]:
    if not object_ids:
        return {}
    payload = ("\n".join(object_ids) + "\n").encode("ascii")
    output = git_bytes("cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)", input_data=payload)
    metadata: dict[str, tuple[str, int]] = {}
    for line in output.decode("ascii").splitlines():
        oid, object_type, raw_size = line.split(" ", 2)
        metadata[oid] = (object_type, int(raw_size))
    return metadata


def main() -> int:
    paths_by_object = historical_object_paths()
    metadata = object_metadata(list(paths_by_object))
    issues: list[str] = []
    blob_count = 0
    text_blob_count = 0

    for oid, paths in paths_by_object.items():
        object_type, size = metadata.get(oid, ("missing", 0))
        if object_type != "blob":
            continue
        blob_count += 1
        display_path = sorted(paths)[0]
        if size > MAX_FILE_BYTES:
            issues.append(f"历史对象超过 {MAX_FILE_BYTES // 1024 // 1024} MB：{display_path} ({oid[:12]})")
            continue
        data = git_bytes("cat-file", "blob", oid)
        if b"\0" in data[:8192]:
            continue
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        text_blob_count += 1
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                issues.append(f"历史对象疑似包含 {label}：{display_path} ({oid[:12]})")

    print(json.dumps({
        "historical_blobs": blob_count,
        "historical_text_blobs": text_blob_count,
        "issues": len(issues),
    }, ensure_ascii=False))
    for issue in issues:
        print(f"[FAIL] {issue}")
    if issues:
        return 1
    print("[PASS] Git history contains no high-confidence credential patterns or oversized historical blobs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
