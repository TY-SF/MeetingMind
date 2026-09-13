from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.BIGINT(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.BIGINT(), nullable=True),
        sa.Column("meeting_started_at", sa.DateTime(), nullable=False),
        sa.Column("participants_json", sa.JSON(), nullable=True),
        sa.Column("context", sa.String(length=500), nullable=True),
        sa.Column("expected_speakers", sa.SmallInteger(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_meetings_status", "meetings", ["status"])
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("meeting_id", sa.String(length=36), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rq_job_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_stage", sa.String(length=40), nullable=False),
        sa.Column("progress", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("warning_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_processing_jobs_meeting_id", "processing_jobs", ["meeting_id"])
    op.create_index("ix_processing_jobs_status", "processing_jobs", ["status"])
    op.create_index("ix_processing_jobs_meeting_active", "processing_jobs", ["meeting_id", "status"])
    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("meeting_id", sa.String(length=36), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("speaker_label", sa.String(length=50), nullable=False),
        sa.Column("speaker_name", sa.String(length=100), nullable=True),
        sa.Column("start_ms", sa.BIGINT(), nullable=False),
        sa.Column("end_ms", sa.BIGINT(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("meeting_id", "segment_index", name="uq_transcript_meeting_segment"),
    )
    op.create_index("ix_transcript_segments_meeting_id", "transcript_segments", ["meeting_id"])
    op.create_index("ix_transcript_segments_meeting_start", "transcript_segments", ["meeting_id", "start_ms"])
    op.create_table(
        "meeting_analyses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("meeting_id", sa.String(length=36), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("ai_raw_result", sa.JSON(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=100), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("analysis_id", sa.String(length=36), sa.ForeignKey("meeting_analyses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("decision_status", sa.String(length=30), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("evidence_start_ms", sa.BIGINT(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_decisions_analysis_id", "decisions", ["analysis_id"])
    op.create_table(
        "action_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("analysis_id", sa.String(length=36), sa.ForeignKey("meeting_analyses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("assignee", sa.String(length=100), nullable=True),
        sa.Column("assignee_status", sa.String(length=30), nullable=False),
        sa.Column("due_date_raw", sa.String(length=100), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("due_precision", sa.String(length=20), nullable=True),
        sa.Column("due_date_status", sa.String(length=30), nullable=False),
        sa.Column("task_status", sa.String(length=30), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("evidence_start_ms", sa.BIGINT(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_action_items_analysis_id", "action_items", ["analysis_id"])


def downgrade() -> None:
    op.drop_table("action_items")
    op.drop_table("decisions")
    op.drop_table("meeting_analyses")
    op.drop_index("ix_transcript_segments_meeting_start", table_name="transcript_segments")
    op.drop_index("ix_transcript_segments_meeting_id", table_name="transcript_segments")
    op.drop_table("transcript_segments")
    op.drop_index("ix_processing_jobs_meeting_active", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_status", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_meeting_id", table_name="processing_jobs")
    op.drop_table("processing_jobs")
    op.drop_index("ix_meetings_status", table_name="meetings")
    op.drop_table("meetings")

