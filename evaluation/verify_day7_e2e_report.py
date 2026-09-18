from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / "evaluation" / "audio_fixtures"
DEFAULT_REPORT = ROOT / "evaluation" / "reports" / "day7-e2e-latest.json"
FORBIDDEN_KEYS = {"access_token", "authorization", "api_key", "hf_token", "raw_result", "transcript", "summary"}

if hasattr(__import__("sys").stdout, "reconfigure"):
    __import__("sys").stdout.reconfigure(encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_forbidden_keys(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in FORBIDDEN_KEYS:
                findings.append(child_path)
            findings.extend(find_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(find_forbidden_keys(child, f"{path}[{index}]"))
    return findings


def verify_report(report_path: Path = DEFAULT_REPORT, fixtures_dir: Path = DEFAULT_FIXTURES) -> list[str]:
    errors: list[str] = []
    if not report_path.is_file():
        return [f"缺少第七天端到端验收报告：{report_path}"]
    try:
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"验收报告无法解析：{exc}"]

    forbidden = find_forbidden_keys(report)
    if forbidden:
        errors.append(f"验收报告包含禁止字段：{', '.join(forbidden)}")
    if report.get("acceptance", {}).get("status") != "passed":
        errors.append("acceptance.status 不是 passed")
    if not re.fullmatch(r"[0-9a-f]{40}", str(report.get("git_commit") or "")):
        errors.append("git_commit 缺失或格式无效")

    fixture_paths = sorted(fixtures_dir.glob("*.json"))
    if len(fixture_paths) != 3:
        errors.append(f"音频 Gold Standard 必须恰好为三组，当前为 {len(fixture_paths)}")
    fixture_hashes = {path.stem: sha256_file(path) for path in fixture_paths}
    cases = report.get("cases") if isinstance(report.get("cases"), list) else []
    if len(cases) != 3:
        errors.append(f"报告必须包含三组端到端结果，当前为 {len(cases)}")
    seen: set[str] = set()
    for case in cases:
        case_id = str(case.get("id") or "")
        if not case_id or case_id in seen:
            errors.append(f"样本 ID 缺失或重复：{case_id!r}")
            continue
        seen.add(case_id)
        if fixture_hashes.get(case_id) != case.get("fixture_sha256"):
            errors.append(f"{case_id} 的 fixture_sha256 与当前样本不一致")
        if case.get("status") != "passed":
            errors.append(f"{case_id} 未通过")
        if case.get("audio_job", {}).get("stage") != "SUCCEEDED":
            errors.append(f"{case_id} 音频任务未成功")
        if int(case.get("transcript_segment_count") or 0) < 1:
            errors.append(f"{case_id} 没有转录片段")
        if int(case.get("speaker_mapping_count") or 0) < 1:
            errors.append(f"{case_id} 没有执行说话人姓名映射")
        if case.get("markdown_export") != "passed":
            errors.append(f"{case_id} Markdown 导出未通过")
        if case.get("calendar_export") not in {"passed", "correctly_rejected"}:
            errors.append(f"{case_id} ICS 验收结果无效")
        if case.get("deletion_verified") is not True:
            errors.append(f"{case_id} 删除完整性未验证")

    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    if metrics.get("sample_count") != 3:
        errors.append("metrics.sample_count 不是 3")
    if metrics.get("structured_output_success_rate") != 1.0:
        errors.append("结构化 JSON 解析成功率不是 100%")
    for name in ("action_item_precision", "assignee_accuracy", "due_date_accuracy", "decision_status_accuracy"):
        value = metrics.get(name)
        if not isinstance(value, (int, float)) or value < 0.8:
            errors.append(f"{name} 低于 0.8")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the committed Day-7 end-to-end acceptance evidence.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    args = parser.parse_args()
    errors = verify_report(args.report, args.fixtures)
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        raise SystemExit(1)
    print("[PASS] 第七天三组音频端到端验收证据完整且指标达标")


if __name__ == "__main__":
    main()
