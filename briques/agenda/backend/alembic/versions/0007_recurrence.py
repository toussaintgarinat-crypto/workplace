"""0007 — récurrence : exdates + override (recurrence_parent_id, recurrence_date).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("exdates", sa.JSON(), nullable=False,
                                      server_default="[]"))
    op.add_column("events", sa.Column("recurrence_parent_id", sa.String(36), nullable=True))
    op.add_column("events", sa.Column("recurrence_date", sa.DateTime(), nullable=True))
    op.create_index("ix_events_recurrence_parent_id", "events", ["recurrence_parent_id"])
    op.create_foreign_key("fk_events_recurrence_parent", "events", "events",
                          ["recurrence_parent_id"], ["id"], ondelete="CASCADE")
    op.create_unique_constraint("uq_event_override", "events",
                                ["recurrence_parent_id", "recurrence_date"])


def downgrade() -> None:
    op.drop_constraint("uq_event_override", "events", type_="unique")
    op.drop_constraint("fk_events_recurrence_parent", "events", type_="foreignkey")
    op.drop_index("ix_events_recurrence_parent_id", table_name="events")
    op.drop_column("events", "recurrence_date")
    op.drop_column("events", "recurrence_parent_id")
    op.drop_column("events", "exdates")
