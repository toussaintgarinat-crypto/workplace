"""Migrations idempotentes jouées au démarrage, après `create_all` (pas d'Alembic ici).

Appelées par le lifespan ET par le conftest des tests : le schéma testé est celui de la
production. `create_all` crée les tables neuves mais n'altère jamais une table existante :
toute colonne, extension ou index ajouté après coup passe par ici.
"""
import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# Plafond (en caractères) du texte indexé : to_tsvector refuse au-delà de 1 Mo de lexèmes
# (« string is too long for tsvector »), et la colonne générée ferait alors échouer tout
# INSERT/UPDATE d'une note géante. Au-delà du plafond, le texte reste stocké mais n'est plus
# trouvable par la recherche lexicale (la branche vectorielle tronque déjà à 8000).
PLAFOND_TEXTE_INDEXE = 200_000


def _texte_normalise(alias: str) -> str:
    return (f"memoire_unaccent(lower(left(coalesce({alias}title, ''), {PLAFOND_TEXTE_INDEXE}) || ' ' || "
            f"left(coalesce({alias}content_md, ''), {PLAFOND_TEXTE_INDEXE})))")


# Texte normalisé d'un souvenir (alias `n`) : minuscules, sans accents. L'index trigramme
# ci-dessous est construit sur la MÊME expression (sans l'alias) : sinon le planificateur ne
# reconnaît pas l'index et ne s'en sert pas.
TEXTE_NORMALISE = _texte_normalise("n.")

_INSTRUCTIONS = [
    # S109 : position libre sur le canvas graphe.
    "ALTER TABLE nodes ADD COLUMN IF NOT EXISTS canvas_pos JSONB",
    # S110 : drapeau d'historique opt-in (la table node_revisions vient de create_all).
    "ALTER TABLE nodes ADD COLUMN IF NOT EXISTS track_history BOOLEAN NOT NULL DEFAULT FALSE",
    # S112 : journal temporel du graphe, opt-in par espace + soft-delete des liens.
    "ALTER TABLE spaces ADD COLUMN IF NOT EXISTS track_history BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE edges ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
    # S238 : recherche lexicale indépendante de l'embedder.
    "CREATE EXTENSION IF NOT EXISTS unaccent",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    # unaccent() n'est que STABLE : une colonne générée et un index exigent IMMUTABLE. Le
    # dictionnaire étant nommé explicitement, l'enveloppe peut l'être sans mentir.
    """CREATE OR REPLACE FUNCTION memoire_unaccent(text) RETURNS text
       LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
       AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$""",
    # Titre en `simple` (noms propres et codes intacts, poids A) + titre et contenu en
    # `french` (pluriels, conjugaisons, poids B), le tout sans accents.
    f"""ALTER TABLE nodes ADD COLUMN IF NOT EXISTS recherche_tsv tsvector GENERATED ALWAYS AS (
         setweight(to_tsvector('simple', memoire_unaccent(left(coalesce(title, ''), {PLAFOND_TEXTE_INDEXE}))), 'A') ||
         setweight(to_tsvector('french', memoire_unaccent(
           left(coalesce(title, ''), {PLAFOND_TEXTE_INDEXE}) || ' ' ||
           left(coalesce(content_md, ''), {PLAFOND_TEXTE_INDEXE}))), 'B')
       ) STORED""",
    "CREATE INDEX IF NOT EXISTS idx_nodes_recherche_tsv ON nodes USING gin (recherche_tsv)",
    f"CREATE INDEX IF NOT EXISTS idx_nodes_texte_trgm ON nodes USING gin (({_texte_normalise('')}) gin_trgm_ops)",
]


def vecteur_graine_42() -> list[float]:
    """Le faux vecteur que l'ancien Embedder renvoyait quand le Gateway tombait (avant S238)."""
    return np.random.default_rng(42).uniform(-0.1, 0.1, 384).tolist()


async def appliquer_migrations(conn: AsyncConnection) -> None:
    for instruction in _INSTRUCTIONS:
        await conn.execute(text(instruction))
    # Vecteurs graine 42 stockés comme réels pendant une panne : remis à NULL pour que la
    # tâche de revectorisation les recalcule (11 souvenirs sur le HP au 2026-10-05).
    graine = "[" + ",".join(str(v) for v in vecteur_graine_42()) + "]"
    await conn.execute(
        text("UPDATE nodes SET embedding = NULL "
             "WHERE embedding IS NOT NULL AND (embedding <=> CAST(:graine AS vector)) < 1e-6"),
        {"graine": graine},
    )
