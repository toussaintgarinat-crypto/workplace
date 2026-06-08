"""0001 — tables initiales calendar service

Revision ID: 0001
Revises:
Create Date: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendars",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("color", sa.String(20), nullable=False, server_default="#3B82F6"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_calendars_user_id", "calendars", ["user_id"])

    op.create_table(
        "calendar_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("calendar_id", sa.String(36), sa.ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("joined_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_calendar_members_user_id", "calendar_members", ["user_id"])

    op.create_table(
        "calendar_invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("calendar_id", sa.String(36), sa.ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(36), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("used_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("calendar_id", sa.String(36), sa.ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("start_at", sa.DateTime, nullable=False),
        sa.Column("end_at", sa.DateTime, nullable=False),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("color", sa.String(20), nullable=True),
        sa.Column("all_day", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("recurrence_rule", sa.String(500), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_events_calendar_id", "events", ["calendar_id"])
    op.create_index("ix_events_start_at", "events", ["start_at"])
    op.create_index("ix_events_end_at", "events", ["end_at"])

    op.create_table(
        "event_participants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("responded_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_event_participants_user_id", "event_participants", ["user_id"])

    op.create_table(
        "event_comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_event_comments_user_id", "event_comments", ["user_id"])

    op.create_table(
        "event_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("mimetype", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("storage_path", sa.String(1000), nullable=False),
        sa.Column("uploaded_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("event_attachments")
    op.drop_table("event_comments")
    op.drop_table("event_participants")
    op.drop_table("events")
    op.drop_table("calendar_invitations")
    op.drop_table("calendar_members")
    op.drop_table("calendars")
