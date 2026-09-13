"""Persist processing stage timing events.

Revision ID: 0002_processing_stage_events
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_processing_stage_events"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processing_stage_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False, server_default="RUNNING"),
        sa.ForeignKeyConstraint(["job_id"], ["processing_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_processing_stage_events_job_id", "processing_stage_events", ["job_id"])
    op.create_index("ix_stage_events_job_started", "processing_stage_events", ["job_id", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_stage_events_job_started", table_name="processing_stage_events")
    op.drop_index("ix_processing_stage_events_job_id", table_name="processing_stage_events")
    op.drop_table("processing_stage_events")
