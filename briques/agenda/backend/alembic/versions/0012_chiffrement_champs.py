"""0012 — S180 : chiffrement au repos des champs sensibles.

upgrade() : élargit les colonnes String→Text (le base64 dépasse les longueurs),
JSON→Text (details) et Float→Text (lat/lon), puis chiffre les lignes existantes.
downgrade() : déchiffre puis restaure les types. Cible = Postgres (dev = create_all).
Exige une clé de chiffrement configurée (AGENDA_ENCRYPTION_KEY ou VAULT_SECRET).

Create Date: 2026-07-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# Colonnes texte chiffrées : table -> (pk, colonnes)
_TEXTE = {
    "events": ("id", ["title", "description", "location"]),
    "event_comments": ("id", ["content"]),
    "user_profiles": ("user_id", ["email"]),
    "calendar_invitations": ("id", ["email"]),
    "shopping_list_invitations": ("id", ["email"]),
    "loyalty_cards": ("id", ["numero", "note"]),
    "availability_polls": ("id", ["title", "description", "location"]),
    "poll_votes": ("id", ["voter_name"]),
    "event_activity_log": ("id", ["user_nom", "details"]),  # details = JSON→Text, texte après alter
    "shopping_items": ("id", ["name", "note"]),
    "shopping_lists": ("id", ["name"]),
}
# Colonnes String(n) à élargir en Text (varchar→text, cast implicite Postgres)
_A_ELARGIR = [
    ("events", "title"), ("events", "location"),
    ("user_profiles", "email"), ("calendar_invitations", "email"),
    ("shopping_list_invitations", "email"),
    ("loyalty_cards", "numero"), ("loyalty_cards", "note"),
    ("availability_polls", "title"), ("availability_polls", "location"),
    ("poll_votes", "voter_name"), ("event_activity_log", "user_nom"),
    ("shopping_items", "name"), ("shopping_items", "note"),
    ("shopping_lists", "name"),
]


def _transformer(conn, fn):
    """Applique fn (chiffrer/déchiffrer) à toutes les colonnes texte, ligne par ligne."""
    for table, (pk, cols) in _TEXTE.items():
        rows = conn.execute(
            sa.text(f"SELECT {pk}, {', '.join(cols)} FROM {table}")).mappings().all()
        for row in rows:
            sets, params = [], {"pk": row[pk]}
            for c in cols:
                if row[c] is None:
                    continue
                sets.append(f"{c} = :{c}")
                params[c] = fn(row[c] if isinstance(row[c], str) else str(row[c]))
            if sets:
                conn.execute(
                    sa.text(f"UPDATE {table} SET {', '.join(sets)} WHERE {pk} = :pk"),
                    params)


def _chiffrer_donnees(conn):
    import crypto
    _transformer(conn, crypto.chiffrer)


def _dechiffrer_donnees(conn):
    import crypto
    _transformer(conn, crypto.dechiffrer)


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    if is_pg:
        for table, col in _A_ELARGIR:
            op.alter_column(table, col, type_=sa.Text())
        op.alter_column("event_activity_log", "details", type_=sa.Text(),
                        postgresql_using="details::text")
        # live_positions : éphémère (TTL court) → on purge pour éviter le cast Float→Text
        op.execute("DELETE FROM live_positions")
        op.alter_column("live_positions", "latitude", type_=sa.Text(),
                        postgresql_using="latitude::text")
        op.alter_column("live_positions", "longitude", type_=sa.Text(),
                        postgresql_using="longitude::text")

    _chiffrer_donnees(conn)


def downgrade() -> None:
    conn = op.get_bind()
    is_pg = conn.dialect.name == "postgresql"

    _dechiffrer_donnees(conn)

    if is_pg:
        op.alter_column("event_activity_log", "details", type_=sa.JSON(),
                        postgresql_using="details::json")
        for table, col in _A_ELARGIR:
            op.alter_column(table, col, type_=sa.String(length=500))
        op.execute("DELETE FROM live_positions")
        op.alter_column("live_positions", "latitude", type_=sa.Float(),
                        postgresql_using="latitude::double precision")
        op.alter_column("live_positions", "longitude", type_=sa.Float(),
                        postgresql_using="longitude::double precision")
