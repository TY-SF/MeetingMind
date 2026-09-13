from __future__ import annotations

from evaluation.evaluate import evaluate_case


def test_gold_evaluator_scores_structured_fields_and_rejects_false_positive() -> None:
    fixture = {
        "id": "evaluation-unit",
        "expected": {
            "decisions": [{"keywords": ["FastAPI", "MySQL"], "status": "CONFIRMED"}],
            "action_items": [{
                "keywords": ["接口文档"],
                "assignee": "张三",
                "assignee_status": "EXPLICIT",
                "due_date": "2026-09-11",
            }],
        },
    }
    prediction = {
        "analysis": {
            "summary": "确定技术方案和接口文档安排。",
            "decisions": [{"content": "后端采用 FastAPI 和 MySQL", "status": "CONFIRMED", "evidence_text": None}],
            "action_items": [
                {
                    "content": "完成接口文档",
                    "assignee": "张三",
                    "assignee_status": "EXPLICIT",
                    "due_at": "2026-09-11T15:59:59+00:00",
                    "evidence_text": "接口文档由张三负责",
                },
                {
                    "content": "模型臆造的额外任务",
                    "assignee": None,
                    "assignee_status": "UNKNOWN",
                    "due_at": None,
                    "evidence_text": None,
                },
            ],
        },
    }
    result = evaluate_case(fixture, prediction)
    assert result["structured_output_success"] is True
    assert result["counts"]["matched_decisions"] == 1
    assert result["counts"]["correct_decision_statuses"] == 1
    assert result["counts"]["matched_actions"] == 1
    assert result["counts"]["predicted_actions"] == 2
    assert result["counts"]["correct_assignees"] == 1
    assert result["counts"]["correct_due_dates"] == 1
