"""Preserve microseconds for processing stage boundaries.

Revision ID: 0003_stage_event_microseconds
Revises: 0002_processing_stage_events
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0003_stage_event_microseconds"
down_revision = "0002_processing_stage_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("processing_stage_events") as batch_op:
        batch_op.alter_column(
            "started_at",
            existing_type=sa.DateTime(),
            type_=mysql.DATETIME(fsp=6),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "finished_at",
            existing_type=sa.DateTime(),
            type_=mysql.DATETIME(fsp=6),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("processing_stage_events") as batch_op:
        batch_op.alter_column(
            "started_at",
            existing_type=mysql.DATETIME(fsp=6),
            type_=sa.DateTime(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "finished_at",
            existing_type=mysql.DATETIME(fsp=6),
            type_=sa.DateTime(),
            existing_nullable=True,
        )
