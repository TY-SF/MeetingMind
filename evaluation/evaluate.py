from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def normalize(value: str | None) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", (value or "").lower())


def keyword_score(candidate: dict[str, Any], expected: dict[str, Any]) -> float:
    haystack = normalize(" ".join(str(candidate.get(key) or "") for key in ("content", "evidence_text")))
    keywords = [normalize(str(item)) for item in expected.get("keywords", []) if normalize(str(item))]
    return sum(keyword in haystack for keyword in keywords) / len(keywords) if keywords else 0.0


def match_expected(predicted: list[dict[str, Any]], expected: list[dict[str, Any]], threshold: float = 0.5) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    available = list(predicted)
    for gold in expected:
        if not available:
            break
        candidate = max(available, key=lambda item: keyword_score(item, gold))
        if keyword_score(candidate, gold) >= threshold:
            matches.append((gold, candidate))
            available.remove(candidate)
    return matches


def local_due_date(value: str | None) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI).date().isoformat()


def evaluate_case(fixture: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    analysis = prediction.get("analysis") or prediction
    predicted_decisions = analysis.get("decisions") if isinstance(analysis, dict) else None
    predicted_actions = analysis.get("action_items") if isinstance(analysis, dict) else None
    structured = isinstance(analysis.get("summary") if isinstance(analysis, dict) else None, str) and isinstance(predicted_decisions, list) and isinstance(predicted_actions, list)
    predicted_decisions = predicted_decisions if isinstance(predicted_decisions, list) else []
    predicted_actions = predicted_actions if isinstance(predicted_actions, list) else []
    expected = fixture["expected"]
    decision_matches = match_expected(predicted_decisions, expected["decisions"])
    action_matches = match_expected(predicted_actions, expected["action_items"])
    matched_prediction_ids = {id(prediction) for _, prediction in action_matches}
    return {
        "id": fixture["id"],
        "structured_output_success": structured,
        "counts": {
            "expected_decisions": len(expected["decisions"]),
            "matched_decisions": len(decision_matches),
            "correct_decision_statuses": sum(gold["status"] == item.get("status") for gold, item in decision_matches),
            "expected_actions": len(expected["action_items"]),
            "predicted_actions": len(predicted_actions),
            "matched_actions": len(action_matches),
            "matched_predicted_actions": sum(id(item) in matched_prediction_ids for item in predicted_actions),
            "assignee_checks": sum(gold.get("assignee") is not None for gold, _ in action_matches),
            "correct_assignees": sum(normalize(gold.get("assignee")) == normalize(item.get("assignee")) for gold, item in action_matches if gold.get("assignee") is not None),
            "assignee_status_checks": len(action_matches),
            "correct_assignee_statuses": sum(gold.get("assignee_status") == item.get("assignee_status") for gold, item in action_matches),
            "due_date_checks": len(action_matches),
            "correct_due_dates": sum(gold.get("due_date") == local_due_date(item.get("due_at")) for gold, item in action_matches),
        },
    }


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def evaluate_directory(fixtures_dir: Path, predictions_dir: Path) -> dict[str, Any]:
    cases = []
    for fixture_path in sorted(fixtures_dir.glob("*.json")):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        prediction_path = predictions_dir / fixture_path.name
        if not prediction_path.exists():
            raise FileNotFoundError(f"缺少预测结果：{prediction_path}")
        prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
        cases.append(evaluate_case(fixture, prediction))
    totals: dict[str, int] = {}
    for case in cases:
        for key, value in case["counts"].items():
            totals[key] = totals.get(key, 0) + int(value)
    metrics = {
        "sample_count": len(cases),
        "structured_output_success_rate": ratio(sum(case["structured_output_success"] for case in cases), len(cases)),
        "action_item_precision": ratio(totals.get("matched_predicted_actions", 0), totals.get("predicted_actions", 0)),
        "action_item_recall": ratio(totals.get("matched_actions", 0), totals.get("expected_actions", 0)),
        "assignee_accuracy": ratio(totals.get("correct_assignees", 0), totals.get("assignee_checks", 0)),
        "assignee_status_accuracy": ratio(totals.get("correct_assignee_statuses", 0), totals.get("assignee_status_checks", 0)),
        "due_date_accuracy": ratio(totals.get("correct_due_dates", 0), totals.get("due_date_checks", 0)),
        "decision_status_accuracy": ratio(totals.get("correct_decision_statuses", 0), totals.get("matched_decisions", 0)),
    }
    return {"metrics": metrics, "totals": totals, "cases": cases, "limitations": "三组受控样本用于回归，不代表生产环境统计性能。"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate MeetingMind structured analysis against three Gold Standard fixtures.")
    parser.add_argument("--fixtures", type=Path, default=Path("evaluation/fixtures"))
    parser.add_argument("--predictions", type=Path, default=Path("evaluation/predictions"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/reports/latest.json"))
    parser.add_argument("--minimum", type=float, default=None, help="Fail if any acceptance metric is below this value.")
    args = parser.parse_args()
    report = evaluate_directory(args.fixtures, args.predictions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    if args.minimum is not None:
        below = {
            key: value
            for key, value in report["metrics"].items()
            if key != "sample_count" and isinstance(value, (int, float)) and value < args.minimum
        }
        if below:
            raise SystemExit(f"Gold Standard 指标低于 {args.minimum}: {below}")


if __name__ == "__main__":
    main()
