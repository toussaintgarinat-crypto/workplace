"""Schéma de la recherche documentaire Forge (S241) : tables cherchables et migrations.

Source UNIQUE des expressions SQL indexées : l'index trigramme doit porter exactement la
même expression que les requêtes, sinon le planificateur ne le reconnaît pas. Les branches
SQL (`app/recherche_documents.py`) et les migrations (`scripts/init_db.py`) importent d'ici.

Pas d'Alembic dans ce projet : chaque instruction est idempotente et rejouée à chaque
démarrage par le service `forge-migrate` (`python -m scripts.init_db`).
"""
from __future__ import annotations

from dataclasses import dataclass

# to_tsvector refuse au-delà de 1 Mo de lexèmes : au-delà du plafond, le texte reste stocké
# mais n'est plus trouvable par la recherche lexicale (même plafond que la Mémoire, S238).
PLAFOND_TEXTE_INDEXE = 200_000


@dataclass(frozen=True)
class TableRecherche:
    source: str               # identifiant exposé : "document" | "kb"
    table: str                # table PostgreSQL
    titre: str                # colonne du titre
    corps: tuple[str, ...]    # colonnes du corps, dans l'ordre d'indexation


TABLES: dict[str, TableRecherche] = {
    "document": TableRecherche("document", "documents", "nom", ("contenu",)),
    "kb": TableRecherche("kb", "kb_articles", "titre", ("tags", "contenu")),
}


def _concat(t: TableRecherche, alias: str) -> str:
    colonnes = (t.titre, *t.corps)
    return " || ' ' || ".join(f"coalesce({alias}{c}, '')" for c in colonnes)


def texte_normalise(t: TableRecherche, alias: str = "") -> str:
    """Titre + corps, minuscules, sans accents, plafonné."""
    return f"forge_unaccent(lower(left({_concat(t, alias)}, {PLAFOND_TEXTE_INDEXE})))"


def titre_normalise(t: TableRecherche, alias: str = "") -> str:
    return f"forge_unaccent(lower(left(coalesce({alias}{t.titre}, ''), {PLAFOND_TEXTE_INDEXE})))"


def _tsv(t: TableRecherche) -> str:
    # Titre en `simple` (noms propres et codes intacts, poids A) + titre et corps en `french`
    # (pluriels, conjugaisons, poids B), le tout sans accents.
    return (
        f"setweight(to_tsvector('simple', forge_unaccent(left(coalesce({t.titre}, ''), "
        f"{PLAFOND_TEXTE_INDEXE}))), 'A') || "
        f"setweight(to_tsvector('french', forge_unaccent(left({_concat(t, '')}, "
        f"{PLAFOND_TEXTE_INDEXE}))), 'B')"
    )


def _migrations_table(t: TableRecherche) -> tuple[str, ...]:
    return (
        f"ALTER TABLE {t.table} ADD COLUMN IF NOT EXISTS recherche_tsv tsvector "
        f"GENERATED ALWAYS AS ({_tsv(t)}) STORED",
        f"CREATE INDEX IF NOT EXISTS idx_{t.table}_recherche_tsv ON {t.table} USING gin (recherche_tsv)",
        f"CREATE INDEX IF NOT EXISTS idx_{t.table}_texte_trgm ON {t.table} "
        f"USING gin (({texte_normalise(t)}) gin_trgm_ops)",
    )


MIGRATIONS_S241: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS unaccent",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    # unaccent() n'est que STABLE : une colonne générée et un index exigent IMMUTABLE. Le
    # dictionnaire étant nommé explicitement, l'enveloppe peut l'être sans mentir.
    """CREATE OR REPLACE FUNCTION forge_unaccent(text) RETURNS text
       LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
       AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$""",
    *_migrations_table(TABLES["document"]),
    *_migrations_table(TABLES["kb"]),
)
