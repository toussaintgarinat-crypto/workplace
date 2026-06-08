"""0002 — colonne role sur calendar_invitations

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "calendar_invitations",
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
    )


def downgrade() -> None:
    op.drop_column("calendar_invitations", "role")
