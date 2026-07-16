"""0009 — S177 : sondages de disponibilité (façon Doodle).

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "availability_polls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("calendar_id", sa.String(36), sa.ForeignKey("calendars.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.Enum("open", "closed", name="poll_status"), nullable=False, server_default="open"),
        sa.Column("final_slot_id", sa.String(36), nullable=True),
        sa.Column("final_event_id", sa.String(36), nullable=True),
        sa.Column("share_token", sa.String(36), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_availability_polls_created_by", "availability_polls", ["created_by"])
    op.create_table(
        "poll_slots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("poll_id", sa.String(36), sa.ForeignKey("availability_polls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_poll_slots_poll_id", "poll_slots", ["poll_id"])
    op.create_table(
        "poll_votes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("poll_id", sa.String(36), sa.ForeignKey("availability_polls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slot_id", sa.String(36), sa.ForeignKey("poll_slots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("voter_id", sa.String(255), nullable=True),
        sa.Column("voter_name", sa.String(255), nullable=False),
        sa.Column("guest_key", sa.String(36), nullable=True),
        sa.Column("value", sa.Enum("oui", "si_besoin", "non", name="poll_vote_value"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_poll_votes_poll_id", "poll_votes", ["poll_id"])
    op.create_index("ix_poll_votes_slot_id", "poll_votes", ["slot_id"])
    op.create_index("ix_poll_votes_voter_id", "poll_votes", ["voter_id"])
    op.create_index("ix_poll_votes_guest_key", "poll_votes", ["guest_key"])


def downgrade() -> None:
    op.drop_index("ix_poll_votes_guest_key", table_name="poll_votes")
    op.drop_index("ix_poll_votes_voter_id", table_name="poll_votes")
    op.drop_index("ix_poll_votes_slot_id", table_name="poll_votes")
    op.drop_index("ix_poll_votes_poll_id", table_name="poll_votes")
    op.drop_table("poll_votes")
    op.drop_index("ix_poll_slots_poll_id", table_name="poll_slots")
    op.drop_table("poll_slots")
    op.drop_index("ix_availability_polls_created_by", table_name="availability_polls")
    op.drop_table("availability_polls")
    for enum in ("poll_status", "poll_vote_value"):
        sa.Enum(name=enum).drop(op.get_bind(), checkfirst=True)
