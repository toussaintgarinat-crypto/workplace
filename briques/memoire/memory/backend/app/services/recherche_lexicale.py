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


async def termes_significatifs(db: AsyncSession, requete: str) -> list[str]:
    """Termes de la requête que la configuration `french` ne tient pas pour mots vides, dans
    l'ordre d'origine."""
    mots = termes(requete)
    if not mots:
        return []
    sql = text("""
        SELECT m FROM unnest(CAST(:mots AS text[])) WITH ORDINALITY AS t(m, i)
        WHERE numnode(plainto_tsquery('french', memoire_unaccent(m))) > 0
        ORDER BY i
    """)
    return [r[0] for r in (await db.execute(sql, {"mots": mots})).all()]


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
        # Le titre est indexé en `simple`, mots vides compris : un mot vide de la requête
        # (« le », « de ») y trouverait tous les titres qui le contiennent. La partie `simple`
        # n'est donc ajoutée que pour les termes que `french` garde (S241).
        morceaux.append(
            f"(CASE WHEN numnode(plainto_tsquery('french', memoire_unaccent(:t{i}))) > 0 "
            f"THEN plainto_tsquery('simple', memoire_unaccent(:t{i})) || plainto_tsquery('french', memoire_unaccent(:t{i})) "
            f"ELSE ''::tsquery END)"
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
    """Filet pour les fautes de frappe, utilisé quand le plein texte ne trouve rien. Ne porte
    que sur les termes significatifs : les mots vides ressembleraient à n'importe quel texte."""
    utiles = await termes_significatifs(db, requete)
    if not utiles:
        return []
    where, params = conditions_sql(filtres)
    params.update(q=" ".join(utiles), seuil=SEUIL_TRIGRAMME, limite=limite)
    similarite = f"word_similarity(memoire_unaccent(lower(:q)), {TEXTE_NORMALISE})"
    sql = text(f"""
        SELECT n.id FROM nodes n
        WHERE {where} AND {similarite} >= :seuil
        ORDER BY {similarite} DESC, n.updated_at DESC, n.id
        LIMIT :limite
    """)
    return [r[0] for r in (await db.execute(sql, params)).all()]


async def references_normalisees(db: AsyncSession, references: list[str]) -> list[str]:
    """Références passées par la MÊME normalisation que le texte (memoire_unaccent(lower)),
    dans l'ordre d'origine."""
    sql = text("""
        SELECT memoire_unaccent(lower(r)) FROM unnest(CAST(:refs AS text[])) WITH ORDINALITY AS t(r, i)
        ORDER BY i
    """)
    return [r[0] for r in (await db.execute(sql, {"refs": references})).all()]


async def correspondances_exactes(
    db: AsyncSession, references: list[str], filtres: Filtres, limite: int
) -> dict[UUID, CorrespondanceExacte]:
    """Souvenirs contenant littéralement au moins une référence (mot entier, sans casse ni
    accents), avec le nombre de références trouvées et la présence dans le titre.

    Chaque référence est d'abord normalisée en SQL, puis le motif est construit en Python
    sur le texte normalisé et comparé tel quel : unaccent appliqué APRÈS l'échappement
    développerait certains symboles en métacaractères (⁇ en ??) et rendrait l'expression
    régulière invalide."""
    if not references:
        return {}
    normalisees = [r for r in await references_normalisees(db, references) if r and r.strip()]
    if not normalisees:
        return {}
    where, params = conditions_sql(filtres)
    comptes, titres = [], []
    for i, reference in enumerate(normalisees):
        params[f"r{i}"] = motif_reference(reference)
        comptes.append(f"(CASE WHEN {TEXTE_NORMALISE} ~ :r{i} THEN 1 ELSE 0 END)")
        titres.append(f"{_TITRE_NORMALISE} ~ :r{i}")
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
