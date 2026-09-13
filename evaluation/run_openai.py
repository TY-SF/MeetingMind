from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings
from app.services.analysis import MeetingAnalysisService, OpenAIAnalysisProvider
from evaluation.evaluate import evaluate_directory


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the configured OpenAI provider on MeetingMind Gold Standard fixtures.")
    parser.add_argument("--fixtures", type=Path, default=ROOT / "evaluation" / "fixtures")
    parser.add_argument("--predictions", type=Path, default=ROOT / "evaluation" / "predictions")
    parser.add_argument("--report", type=Path, default=ROOT / "evaluation" / "reports" / "latest.json")
    args = parser.parse_args()

    settings = Settings.from_env()
    if not settings.llm_api_key:
        raise SystemExit("未配置 OPENAI_API_KEY")
    provider = OpenAIAnalysisProvider(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    service = MeetingAnalysisService(provider, settings.llm_max_input_chars)
    args.predictions.mkdir(parents=True, exist_ok=True)
    for fixture_path in sorted(args.fixtures.glob("*.json")):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        result, normalized = service.analyze(
            transcript=fixture["transcript"],
            meeting_started_at=fixture["meeting_started_at"],
            context=fixture.get("context", ""),
        )
        prediction = {
            "fixture_id": fixture["id"],
            "provider": result.provider,
            "model": result.model,
            "prompt_version": result.prompt_version,
            "analysis": {
                "summary": normalized.summary,
                "decisions": normalized.decisions,
                "action_items": normalized.action_items,
            },
        }
        (args.predictions / fixture_path.name).write_text(json.dumps(prediction, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"完成：{fixture['id']}")
    report = evaluate_directory(args.fixtures, args.predictions)
    report["provider"] = provider.provider_name
    report["model"] = provider.model
    report["prompt_version"] = provider.prompt_version
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
