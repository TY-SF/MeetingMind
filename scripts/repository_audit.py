from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 5 * 1024 * 1024
SECRET_PATTERNS = (
    ("OpenAI API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{16,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "credential-bearing service URL",
        re.compile(r"(?i)(?:mysql|postgres(?:ql)?|redis)[^:\s]*://[^\s:/]+:[^\s@/]+@"),
    ),
)
REQUIRED_IGNORED_PATHS = (
    "backend/.env/meetingmind.env",
    "data/runtime/meetingmind.db",
    "backend/data/runtime/meetingmind.db",
    "frontend/node_modules",
    "frontend/dist",
    "repository-audit-sample.mp3",
)
BIDI_CONTROLS = "\u202e\u2066\u2067\u2068\u2069"


def git_bytes(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def candidate_files() -> list[Path]:
    raw = git_bytes("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return [ROOT / item.decode("utf-8") for item in raw.split(b"\0") if item]


def main() -> int:
    issues: list[str] = []
    files = candidate_files()
    seen_paths: dict[str, str] = {}
    total_bytes = 0

    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        total_bytes += len(data)
        normalized = unicodedata.normalize("NFC", relative).casefold()
        if normalized in seen_paths:
            issues.append(f"路径大小写或 Unicode 冲突：{seen_paths[normalized]} <> {relative}")
        seen_paths[normalized] = relative

        if len(str(path.resolve())) >= 240:
            issues.append(f"Windows 路径过长：{relative}")
        if len(data) > MAX_FILE_BYTES:
            issues.append(f"文件超过 {MAX_FILE_BYTES // 1024 // 1024} MB：{relative}")
        if b"\0" in data[:8192]:
            issues.append(f"候选集合含二进制文件：{relative}")
            continue
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            issues.append(f"文件不是 UTF-8：{relative}（{exc}）")
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.rstrip(" \t") != line:
                issues.append(f"行尾空白：{relative}:{line_number}")
            if any(control in line for control in BIDI_CONTROLS):
                issues.append(f"可疑双向文本控制字符：{relative}:{line_number}")

        for label, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                line_number = text.count("\n", 0, match.start()) + 1
                issues.append(f"疑似 {label}：{relative}:{line_number}")

        if path.suffix.lower() == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                issues.append(f"JSON 无效：{relative}:{exc.lineno}:{exc.colno}")

    for relative in REQUIRED_IGNORED_PATHS:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "--quiet", "--", relative],
            check=False,
        )
        if result.returncode != 0:
            issues.append(f"敏感或生成路径未被忽略：{relative}")

    summary = {
        "candidate_files": len(files),
        "total_bytes": total_bytes,
        "issues": len(issues),
    }
    print(json.dumps(summary, ensure_ascii=False))
    for issue in issues:
        print(f"[FAIL] {issue}")
    if issues:
        return 1
    print("[PASS] Repository candidate audit found no credential, binary/large-file, format, or ignore-rule issues.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
