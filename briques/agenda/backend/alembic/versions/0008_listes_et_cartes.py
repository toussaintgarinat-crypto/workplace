"""0008 — S176 : listes de courses/tâches partagées + cartes de fidélité.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shopping_lists",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.Enum("courses", "taches", name="list_kind"), nullable=False, server_default="courses"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "shopping_list_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("list_id", sa.String(36), sa.ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("owner", "editor", "viewer", name="list_member_role"), nullable=False, server_default="viewer"),
        sa.Column("joined_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("list_id", "user_id", name="uq_list_member"),
    )
    op.create_index("ix_shopping_list_members_list_id", "shopping_list_members", ["list_id"])
    op.create_index("ix_shopping_list_members_user_id", "shopping_list_members", ["user_id"])
    op.create_table(
        "shopping_list_invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("list_id", sa.String(36), sa.ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(36), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "shopping_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("list_id", sa.String(36), sa.ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("emoji", sa.String(16), nullable=True),
        sa.Column("rayon", sa.String(50), nullable=True),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("checked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checked_by", sa.String(255), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("added_by", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_shopping_items_list_id", "shopping_items", ["list_id"])
    op.create_table(
        "catalog_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("list_id", sa.String(36), sa.ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("emoji", sa.String(16), nullable=False, server_default="🛒"),
        sa.Column("rayon", sa.String(50), nullable=False, server_default="Autre"),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_catalog_items_list_id", "catalog_items", ["list_id"])
    op.create_table(
        "loyalty_cards",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("enseigne", sa.String(255), nullable=False),
        sa.Column("numero", sa.String(255), nullable=False),
        sa.Column("format", sa.Enum("code128", "ean13", "qr", name="barcode_format"), nullable=False, server_default="code128"),
        sa.Column("couleur", sa.String(20), nullable=False, server_default="#3B82F6"),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_loyalty_cards_user_id", "loyalty_cards", ["user_id"])


def downgrade() -> None:
    op.drop_table("loyalty_cards")
    op.drop_index("ix_catalog_items_list_id", table_name="catalog_items")
    op.drop_table("catalog_items")
    op.drop_index("ix_shopping_items_list_id", table_name="shopping_items")
    op.drop_table("shopping_items")
    op.drop_table("shopping_list_invitations")
    op.drop_index("ix_shopping_list_members_user_id", table_name="shopping_list_members")
    op.drop_index("ix_shopping_list_members_list_id", table_name="shopping_list_members")
    op.drop_table("shopping_list_members")
    op.drop_table("shopping_lists")
    for enum in ("list_kind", "list_member_role", "barcode_format"):
        sa.Enum(name=enum).drop(op.get_bind(), checkfirst=True)
