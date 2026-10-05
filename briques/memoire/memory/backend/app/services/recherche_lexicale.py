"""Branche lexicale de la recherche Mémoire (S238) : indépendante de l'embedder.

Couvre tous les souvenirs visibles, qu'ils aient un vecteur ou non.
"""
import re
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.migrations_demarrage import TEXTE_NORMALISE
from app.services.recherche_conditions import Filtres, conditions_sql
from app.services.recherche_fusion import CorrespondanceExacte, motif_reference

SEUIL_TRIGRAMME = 0.3
TERMES_MAX = 32
_TITRE_NORMALISE = "memoire_unaccent(lower(coalesce(n.title, '')))"


def termes(requete: str) -> list[str]:
    """Mots de la requête (lettres et chiffres seulement : aucun opérateur tsquery ne passe)."""
    return re.findall(r"[^\W_]+", requete.lower())[:TERMES_MAX]


async def classement_plein_texte(db: AsyncSession, requete: str, filtres: Filtres, limite: int) -> list[UUID]:
    """OU sur les termes, en `simple` et en `french`, classé par ts_rank_cd (plus de termes
    trouvés et titre de poids A = mieux classé)."""
    mots = termes(requete)
    if not mots:
        return []
    where, params = conditions_sql(filtres)
    morceaux = []
    for i, mot in enumerate(mots):
        params[f"t{i}"] = mot
        morceaux.append(
            f"plainto_tsquery('simple', memoire_unaccent(:t{i})) || plainto_tsquery('french', memoire_unaccent(:t{i}))"
        )
    params["limite"] = limite
    sql = text(f"""
        WITH q AS (SELECT ({' || '.join(morceaux)}) AS requete)
        SELECT n.id FROM nodes n, q
        WHERE {where} AND n.recherche_tsv @@ q.requete
        ORDER BY ts_rank_cd(n.recherche_tsv, q.requete) DESC, n.updated_at DESC, n.id
        LIMIT :limite
    """)
    return [r[0] for r in (await db.execute(sql, params)).all()]


async def classement_trigramme(db: AsyncSession, requete: str, filtres: Filtres, limite: int) -> list[UUID]:
    """Filet pour les fautes de frappe, utilisé quand le plein texte ne trouve rien."""
    if not requete.strip():
        return []
    where, params = conditions_sql(filtres)
    params.update(q=requete.strip(), seuil=SEUIL_TRIGRAMME, limite=limite)
    similarite = f"word_similarity(memoire_unaccent(lower(:q)), {TEXTE_NORMALISE})"
    sql = text(f"""
        SELECT n.id FROM nodes n
        WHERE {where} AND {similarite} >= :seuil
        ORDER BY {similarite} DESC, n.updated_at DESC, n.id
        LIMIT :limite
    """)
    return [r[0] for r in (await db.execute(sql, params)).all()]


async def correspondances_exactes(
    db: AsyncSession, references: list[str], filtres: Filtres, limite: int
) -> dict[UUID, CorrespondanceExacte]:
    """Souvenirs contenant littéralement au moins une référence (mot entier, sans casse ni
    accents), avec le nombre de références trouvées et la présence dans le titre."""
    if not references:
        return {}
    where, params = conditions_sql(filtres)
    comptes, titres = [], []
    for i, reference in enumerate(references):
        params[f"r{i}"] = motif_reference(reference)
        motif = f"memoire_unaccent(lower(:r{i}))"
        comptes.append(f"(CASE WHEN {TEXTE_NORMALISE} ~ {motif} THEN 1 ELSE 0 END)")
        titres.append(f"{_TITRE_NORMALISE} ~ {motif}")
    params["limite"] = limite
    sql = text(f"""
        SELECT id, trouvees, dans_titre FROM (
            SELECT n.id, n.updated_at, ({' + '.join(comptes)}) AS trouvees, ({' OR '.join(titres)}) AS dans_titre
            FROM nodes n WHERE {where}
        ) x
        WHERE trouvees > 0
        ORDER BY trouvees DESC, dans_titre DESC, updated_at DESC, id
        LIMIT :limite
    """)
    return {r[0]: CorrespondanceExacte(int(r[1]), bool(r[2])) for r in (await db.execute(sql, params)).all()}
