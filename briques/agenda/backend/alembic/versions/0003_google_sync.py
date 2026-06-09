"""0003 — pont Google Agenda (S27) : colonnes Event.source/external_id + table user_tokens

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-09
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Provenance + clé d'idempotence sur les événements existants.
    op.add_column(
        "events",
        sa.Column("source", sa.String(20), nullable=False, server_default="manuel"),
    )
    op.add_column("events", sa.Column("external_id", sa.String(255), nullable=True))
    op.create_index("ix_events_external_id", "events", ["external_id"])

    # Coffre de tokens OAuth chiffrés (un par user/provider).
    op.create_table(
        "user_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False, server_default="google"),
        sa.Column("access_token_enc", sa.LargeBinary, nullable=False),
        sa.Column("refresh_token_enc", sa.LargeBinary, nullable=True),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("scope", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_provider"),
    )
    op.create_index("ix_user_tokens_user_id", "user_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_tokens_user_id", table_name="user_tokens")
    op.drop_table("user_tokens")
    op.drop_index("ix_events_external_id", table_name="events")
    op.drop_column("events", "external_id")
    op.drop_column("events", "source")
