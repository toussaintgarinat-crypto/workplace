"""0011 — S179 : présence éphémère (live_positions) + jeton d'abonnement ICS.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_positions",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("scope", sa.Enum("famille", "event", name="live_position_scope"),
                  nullable=False, server_default="famille"),
        sa.Column("event_id", sa.String(36),
                  sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_live_positions_expires_at", "live_positions", ["expires_at"])
    op.add_column("user_profiles", sa.Column("ics_token", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_user_profiles_ics_token", "user_profiles", ["ics_token"])


def downgrade() -> None:
    op.drop_constraint("uq_user_profiles_ics_token", "user_profiles", type_="unique")
    op.drop_column("user_profiles", "ics_token")
    op.drop_index("ix_live_positions_expires_at", table_name="live_positions")
    op.drop_table("live_positions")
    op.execute("DROP TYPE IF EXISTS live_position_scope")  # nettoyage enum Postgres
