"""Correct stale capability warning text in existing jobs.

Revision ID: 0004_correct_capability_warning
Revises: 0003_stage_event_microseconds
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_correct_capability_warning"
down_revision = "0003_stage_event_microseconds"
branch_labels = None
depends_on = None

OLD_WARNING = "阶段二已完成真实音频规范化和 WhisperX 转录；说话人分离与 AI 分析将在后续阶段接入。"
NEW_WARNING = (
    "当前版本尚未接入自动说话人分离，转录片段暂使用默认说话人标签；"
    "可在“完整转录”中人工映射姓名。AI 分析已可在会议结果页生成。"
)


def upgrade() -> None:
    jobs = sa.table("processing_jobs", sa.column("warning_message", sa.Text()))
    op.execute(
        jobs.update()
        .where(jobs.c.warning_message.contains(OLD_WARNING))
        .values(warning_message=sa.func.replace(jobs.c.warning_message, OLD_WARNING, NEW_WARNING))
    )


def downgrade() -> None:
    jobs = sa.table("processing_jobs", sa.column("warning_message", sa.Text()))
    op.execute(
        jobs.update()
        .where(jobs.c.warning_message.contains(NEW_WARNING))
        .values(warning_message=sa.func.replace(jobs.c.warning_message, NEW_WARNING, OLD_WARNING))
    )
