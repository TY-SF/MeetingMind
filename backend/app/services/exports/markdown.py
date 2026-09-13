from __future__ import annotations

from typing import Any


def render_markdown(meeting: dict[str, Any]) -> str:
    """Render the persisted, human-reviewable state rather than raw model output."""
    analysis = meeting.get("analysis")
    if not analysis:
        raise ValueError("会议尚未生成分析结果")

    lines = [
        f"# {meeting['title']}",
        "",
        f"> 会议时间：{meeting['meeting_started_at']}",
        f"> 音频文件：{meeting['original_filename']}",
        f"> 音频时长：{format_duration(meeting.get('duration_ms', 0))}",
        f"> 参会人：{'、'.join(meeting.get('participants') or []) or '未填写'}",
        "",
        "## 会议摘要",
        "",
        analysis.get("summary") or "暂无摘要",
        "",
        "## 关键结论",
        "",
    ]
    decisions = analysis.get("decisions") or []
    lines.extend(
        f"{index}. **[{item['status']}]** {item['content']}"
        for index, item in enumerate(decisions, start=1)
    )
    if not decisions:
        lines.append("暂无关键结论。")

    lines.extend([
        "",
        "## 待办事项",
        "",
        "| 待办 | 负责人 | 截止时间 | 状态 |",
        "|---|---|---|---|",
    ])
    action_items = analysis.get("action_items") or []
    lines.extend(
        "| {content} | {assignee} | {due} | {status} |".format(
            content=escape_table(item["content"]),
            assignee=escape_table(item.get("assignee") or "未指定"),
            due=escape_table(item.get("due_date_raw") or item.get("due_at") or "未指定"),
            status=item["status"],
        )
        for item in action_items
    )
    if not action_items:
        lines.append("| 暂无待办 | — | — | — |")

    lines.extend(["", "## 完整转录", ""])
    transcript = meeting.get("transcript") or []
    lines.extend(
        f"**[{format_timestamp(item['start_ms'])}] {item['speaker']}**：{item['text']}"
        for item in transcript
    )
    if not transcript:
        lines.append("暂无转录内容。")

    lines.extend([
        "",
        "## 处理信息",
        "",
        f"- Provider：{analysis.get('provider') or '未记录'}",
        f"- 模型：{analysis.get('model') or '未记录'}",
        f"- Prompt 版本：{analysis.get('prompt_version') or '未记录'}",
        f"- 分析版本：{analysis.get('version', 1)}",
        "",
    ])
    return "\n".join(lines)


def escape_table(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def format_timestamp(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds // 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_duration(milliseconds: int) -> str:
    return format_timestamp(milliseconds)
