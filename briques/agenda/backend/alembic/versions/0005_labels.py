"""0005 — étiquettes nommées : table `labels` + colonne Event.label_id

Les vraies *catégories* TimeTree : un nom + une couleur réutilisables par calendrier.
Un événement peut porter une étiquette (sa couleur d'affichage en dérive), sinon il
garde sa couleur libre (`events.color`). On conserve donc les deux mécanismes.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "labels",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("calendar_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("color", sa.String(length=20), nullable=False, server_default="#5865F2"),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["calendar_id"], ["calendars.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_labels_calendar_id", "labels", ["calendar_id"])
    op.create_index("ix_labels_external_id", "labels", ["external_id"])

    # Étiquette nommée facultative d'un événement. Les events existants restent sans
    # étiquette (NULL) — aucune valeur imposée.
    op.add_column("events", sa.Column("label_id", sa.String(length=36), nullable=True))
    op.create_index("ix_events_label_id", "events", ["label_id"])
    # FK SET NULL : supprimer un label laisse l'événement « sans étiquette ».
    with op.batch_alter_table("events") as batch:
        batch.create_foreign_key(
            "fk_events_label_id", "labels", ["label_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("events") as batch:
        batch.drop_constraint("fk_events_label_id", type_="foreignkey")
    op.drop_index("ix_events_label_id", table_name="events")
    op.drop_column("events", "label_id")
    op.drop_index("ix_labels_external_id", table_name="labels")
    op.drop_index("ix_labels_calendar_id", table_name="labels")
    op.drop_table("labels")
