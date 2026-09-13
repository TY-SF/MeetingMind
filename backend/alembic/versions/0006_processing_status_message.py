"""Persist processing status messages separately from errors.

Revision ID: 0006_processing_status_message
Revises: 0005_diarization_result
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_processing_status_message"
down_revision = "0005_diarization_result"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("processing_jobs", sa.Column("status_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("processing_jobs", "status_message")
