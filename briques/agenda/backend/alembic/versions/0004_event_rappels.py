"""0004 — rappels configurables : colonne Event.rappels (liste de minutes avant)

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Liste JSON de « minutes avant le début » (ex. [10, 1440]). Les événements
    # existants démarrent sans rappel (liste vide) — aucun défaut imposé.
    op.add_column(
        "events",
        sa.Column("rappels", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("events", "rappels")
