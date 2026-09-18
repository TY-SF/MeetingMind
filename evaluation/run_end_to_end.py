from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings
from evaluation.evaluate import evaluate_directory

TERMINAL_STAGES = {"SUCCEEDED", "FAILED"}
ACCEPTANCE_MINIMUM = 0.8


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str | None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
    if isinstance(detail, dict):
        code = detail.get("code")
        message = detail.get("message")
        return " ".join(str(item) for item in (code, message) if item) or f"HTTP {response.status_code}"
    return str(detail)


def require(response: httpx.Response, expected: int | set[int], operation: str) -> httpx.Response:
    statuses = {expected} if isinstance(expected, int) else expected
    if response.status_code not in statuses:
        raise RuntimeError(f"{operation}失败：{response_detail(response)}")
    return response


def poll_job(client: httpx.Client, job_id: str, timeout_seconds: int, interval_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_stage = None
    while time.monotonic() < deadline:
        response = require(client.get(f"/api/v1/jobs/{job_id}"), 200, "查询任务")
        job = response.json()
        stage = job.get("stage")
        if stage != last_stage:
            print(f"  阶段：{stage} ({job.get('progress', 0)}%)")
            last_stage = stage
        if stage in TERMINAL_STAGES:
            return job
        time.sleep(interval_seconds)
    raise TimeoutError(f"任务 {job_id} 在 {timeout_seconds} 秒内未完成")


def unique_speakers(fixture: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for segment in fixture["segments"]:
        name = str(segment["speaker"])
        if name not in names:
            names.append(name)
    return names


def map_speakers(client: httpx.Client, meeting_id: str, meeting: dict[str, Any], fixture: dict[str, Any]) -> int:
    labels: list[str] = []
    for segment in meeting.get("transcript", []):
        label = str(segment.get("speaker_label") or segment.get("speaker") or "")
        if label and label not in labels:
            labels.append(label)
    names = unique_speakers(fixture)
    mappings = [
        {"speaker_label": label, "speaker_name": names[index] if index < len(names) else f"测试说话人{index + 1}"}
        for index, label in enumerate(labels[:10])
    ]
    if not mappings:
        return 0
    require(
        client.patch(f"/api/v1/meetings/{meeting_id}/speakers", json={"mappings": mappings}),
        200,
        "保存说话人映射",
    )
    return len(mappings)


def stage_summary(job: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for event in job.get("stage_events", []):
        result.append(
            {
                "stage": event.get("stage"),
                "status": event.get("status"),
                "duration_ms": event.get("duration_ms"),
                "attempt": event.get("attempt"),
            }
        )
    return result


def run_case(
    client: httpx.Client,
    fixture_path: Path,
    audio_path: Path,
    predictions_dir: Path,
    timeout_seconds: int,
    poll_interval: float,
    keep_meetings: bool,
) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8-sig"))
    case_id = fixture["id"]
    result: dict[str, Any] = {
        "id": case_id,
        "status": "failed",
        "fixture_sha256": sha256_file(fixture_path),
        "audio_sha256": sha256_file(audio_path),
        "audio_size_bytes": audio_path.stat().st_size,
        "synthetic_audio": True,
    }
    meeting_id: str | None = None
    deletion_verified = False
    try:
        print(f"\n[{case_id}] 上传合成验收音频")
        with audio_path.open("rb") as audio:
            upload = require(
                client.post(
                    "/api/v1/meetings",
                    files={"file": (audio_path.name, audio, "audio/wav")},
                    data={
                        "title": fixture["title"],
                        "meeting_started_at": fixture["meeting_started_at"],
                        "participants": json.dumps(unique_speakers(fixture), ensure_ascii=False),
                        "context": fixture.get("context", ""),
                        "expected_speakers": str(fixture["expected_speakers"]),
                        "data_processing_confirmed": "true",
                    },
                ),
                202,
                "上传音频",
            ).json()
        meeting_id = upload["meeting_id"]
        job = poll_job(client, upload["job_id"], timeout_seconds, poll_interval)
        result["audio_job"] = {
            "stage": job.get("stage"),
            "retry_count": job.get("retry_count"),
            "diarization_status": job.get("diarization_status"),
            "speaker_count": job.get("speaker_count"),
            "stage_events": stage_summary(job),
        }
        if job.get("stage") != "SUCCEEDED":
            raise RuntimeError(f"音频处理失败：{job.get('error_code') or 'UNKNOWN_ERROR'}")

        meeting = require(client.get(f"/api/v1/meetings/{meeting_id}"), 200, "读取会议").json()
        segment_count = len(meeting.get("transcript", []))
        if segment_count < 1:
            raise RuntimeError("音频处理成功但没有转录片段")
        result["transcript_segment_count"] = segment_count
        result["speaker_mapping_count"] = map_speakers(client, meeting_id, meeting, fixture)

        print(f"[{case_id}] 请求结构化 AI 分析")
        analysis = require(
            client.post(
                f"/api/v1/meetings/{meeting_id}/analysis",
                json={"analysis_data_confirmed": True},
                timeout=max(180.0, client.timeout.read or 0.0),
            ),
            200,
            "生成 AI 分析",
        ).json()
        prediction = {
            "fixture_id": case_id,
            "provider": analysis.get("provider"),
            "model": analysis.get("model"),
            "prompt_version": analysis.get("prompt_version"),
            "analysis": {
                "summary": analysis.get("summary", ""),
                "decisions": analysis.get("decisions", []),
                "action_items": analysis.get("action_items", []),
            },
        }
        json_write(predictions_dir / fixture_path.name, prediction)
        result["analysis"] = {
            "provider": analysis.get("provider"),
            "model": analysis.get("model"),
            "prompt_version": analysis.get("prompt_version"),
            "version": analysis.get("version"),
            "decision_count": len(analysis.get("decisions", [])),
            "action_item_count": len(analysis.get("action_items", [])),
        }

        markdown = require(client.get(f"/api/v1/meetings/{meeting_id}/exports/markdown"), 200, "导出 Markdown")
        if not markdown.content:
            raise RuntimeError("Markdown 导出为空")
        result["markdown_export"] = "passed"

        calendar = client.get(f"/api/v1/meetings/{meeting_id}/exports/calendar")
        if fixture.get("calendar_expected"):
            require(calendar, 200, "导出 ICS")
            if b"BEGIN:VEVENT" not in calendar.content:
                raise RuntimeError("ICS 未包含 VEVENT")
            result["calendar_export"] = "passed"
        else:
            require(calendar, 409, "验证无可靠日期时拒绝 ICS")
            if "NO_EXPORTABLE_ACTION_ITEMS" not in response_detail(calendar):
                raise RuntimeError("ICS 409 未返回 NO_EXPORTABLE_ACTION_ITEMS")
            result["calendar_export"] = "correctly_rejected"

        result["status"] = "passed"
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result
    finally:
        if meeting_id and not keep_meetings:
            deletion = client.delete(f"/api/v1/meetings/{meeting_id}")
            if deletion.status_code == 204:
                deletion_verified = client.get(f"/api/v1/meetings/{meeting_id}").status_code == 404
            if not deletion_verified:
                result["status"] = "failed"
                result["error"] = (result.get("error", "") + "; 测试会议删除完整性验证失败").strip("; ")
        result["deletion_verified"] = deletion_verified if not keep_meetings else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the three Day-7 audio Gold Standard cases through the live MeetingMind API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--fixtures", type=Path, default=ROOT / "evaluation" / "audio_fixtures")
    parser.add_argument("--audio-dir", type=Path, default=ROOT / "data" / "evaluation" / "day7-audio")
    parser.add_argument("--predictions", type=Path, default=ROOT / "data" / "evaluation" / "day7-e2e-predictions")
    parser.add_argument("--report", type=Path, default=ROOT / "evaluation" / "reports" / "day7-e2e-latest.json")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--keep-meetings", action="store_true")
    args = parser.parse_args()

    fixture_paths = sorted(args.fixtures.glob("*.json"))
    if len(fixture_paths) != 3:
        raise SystemExit(f"第七天验收必须恰好包含三组音频样本，当前为 {len(fixture_paths)}")
    missing_audio = [path.stem for path in fixture_paths if not (args.audio_dir / f"{path.stem}.wav").is_file()]
    if missing_audio:
        raise SystemExit(f"缺少验收音频：{', '.join(missing_audio)}；先运行 scripts/generate_day7_audio_fixtures.ps1")

    settings = Settings.from_env()
    headers = {"Authorization": f"Bearer {settings.api_access_token}"} if settings.api_access_token else {}
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": "MeetingMind",
        "acceptance_target": "Day 7",
        "git_commit": git_commit(),
        "base_url": args.base_url,
        "privacy": "报告不包含访问令牌、音频正文、完整转录、会议摘要或模型原始响应。",
        "cases": [],
    }

    try:
        with httpx.Client(base_url=args.base_url.rstrip("/"), headers=headers, timeout=60.0) as client:
            require(client.get("/api/v1/health"), 200, "API 健康检查")
            queue = require(client.get("/api/v1/health/queue"), 200, "队列健康检查").json()
            if queue.get("status") != "ready":
                raise RuntimeError(f"队列未就绪：{queue.get('status')}")
            report["queue"] = {
                "status": queue.get("status"),
                "redis": queue.get("redis"),
                "worker_online": queue.get("worker_online"),
            }
            for fixture_path in fixture_paths:
                case = run_case(
                    client,
                    fixture_path,
                    args.audio_dir / f"{fixture_path.stem}.wav",
                    args.predictions,
                    args.timeout_seconds,
                    args.poll_interval,
                    args.keep_meetings,
                )
                report["cases"].append(case)
                print(f"[{case['id']}] {case['status']}")
    except Exception as exc:
        report["infrastructure_error"] = str(exc)

    completed_predictions = all((args.predictions / path.name).is_file() for path in fixture_paths)
    if completed_predictions:
        evaluation = evaluate_directory(args.fixtures, args.predictions)
        report["metrics"] = evaluation["metrics"]
        report["totals"] = evaluation["totals"]
    else:
        report["metrics"] = None

    metrics = report.get("metrics") or {}
    metric_failures = {
        key: value
        for key, value in metrics.items()
        if key != "sample_count"
        and isinstance(value, (int, float))
        and ((key == "structured_output_success_rate" and value != 1.0) or (key != "structured_output_success_rate" and value < ACCEPTANCE_MINIMUM))
    }
    case_failures = [case["id"] for case in report["cases"] if case.get("status") != "passed"]
    report["acceptance"] = {
        "status": "passed" if len(report["cases"]) == 3 and not case_failures and not metric_failures and metrics.get("sample_count") == 3 else "failed",
        "required_sample_count": 3,
        "structured_output_success_required": 1.0,
        "other_metric_minimum": ACCEPTANCE_MINIMUM,
        "case_failures": case_failures,
        "metric_failures": metric_failures,
    }
    json_write(args.report, report)
    print(f"\n验收报告：{args.report}")
    print(json.dumps(report["acceptance"], ensure_ascii=False, indent=2))
    if report["acceptance"]["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
