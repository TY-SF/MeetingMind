"""One durable job record per meeting prevents concurrent active processing jobs."""
from alembic import op

revision = "0007_one_job_per_meeting"
down_revision = "0006_processing_status_message"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_processing_jobs_meeting_id", "processing_jobs", ["meeting_id"])


def downgrade() -> None:
    op.drop_constraint("uq_processing_jobs_meeting_id", "processing_jobs", type_="unique")
