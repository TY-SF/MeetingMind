"""Persist speaker diarization outcome on processing jobs.

Revision ID: 0005_diarization_result
Revises: 0004_correct_capability_warning
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_diarization_result"
down_revision = "0004_correct_capability_warning"
branch_labels = None
depends_on = None

STALE_WARNING = (
    "当前版本尚未接入自动说话人分离，转录片段暂使用默认说话人标签；"
    "可在“完整转录”中人工映射姓名。AI 分析已可在会议结果页生成。"
)


def upgrade() -> None:
    op.add_column(
        "processing_jobs",
        sa.Column("diarization_status", sa.String(length=20), nullable=False, server_default="NOT_RUN"),
    )
    op.add_column(
        "processing_jobs",
        sa.Column("speaker_count", sa.Integer(), nullable=False, server_default="0"),
    )
    jobs = sa.table("processing_jobs", sa.column("warning_message", sa.Text()))
    op.execute(
        jobs.update()
        .where(jobs.c.warning_message == STALE_WARNING)
        .values(warning_message=None)
    )


def downgrade() -> None:
    op.drop_column("processing_jobs", "speaker_count")
    op.drop_column("processing_jobs", "diarization_status")
