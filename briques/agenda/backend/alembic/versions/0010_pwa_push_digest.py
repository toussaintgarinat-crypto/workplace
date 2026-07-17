"""0010 — S178 : champs push/digest sur user_profiles.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("email", sa.String(320), nullable=True))
    op.add_column("user_profiles", sa.Column("digest_cadence", sa.String(10), nullable=False, server_default="off"))
    op.add_column("user_profiles", sa.Column("digest_push", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("user_profiles", sa.Column("digest_email", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("user_profiles", sa.Column("heures_calmes", sa.String(20), nullable=True))
    op.add_column("user_profiles", sa.Column("dernier_digest_quotidien", sa.String(10), nullable=True))
    op.add_column("user_profiles", sa.Column("dernier_digest_hebdo", sa.String(10), nullable=True))


def downgrade() -> None:
    for col in ("dernier_digest_hebdo", "dernier_digest_quotidien", "heures_calmes",
                "digest_email", "digest_push", "digest_cadence", "email"):
        op.drop_column("user_profiles", col)
