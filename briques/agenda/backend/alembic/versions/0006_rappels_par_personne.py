"""0006 — rappels par personne : EventParticipant.rappels + user_profiles + event_activity_log

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Override personnel des rappels. NULL par défaut = hérite du défaut de l'événement
    # (les participants existants ne changent donc pas de comportement).
    op.add_column(
        "event_participants",
        sa.Column("rappels", sa.JSON(), nullable=True),
    )
    op.create_unique_constraint("uq_event_participant", "event_participants", ["event_id", "user_id"])
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.String(length=255), primary_key=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("avatar_color", sa.String(length=20), nullable=False, server_default="#3B82F6"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "event_activity_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_id", sa.String(length=36), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("user_nom", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("event_activity_log")
    op.drop_table("user_profiles")
    op.drop_constraint("uq_event_participant", "event_participants", type_="unique")
    op.drop_column("event_participants", "rappels")
