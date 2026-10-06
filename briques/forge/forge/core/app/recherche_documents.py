"""Branches SQL de la recherche documentaire Forge (S241) : exacte, plein texte, trigrammes.

Toute requête porte `user_id = :moi` DANS le SQL : aucune ligne d'un autre utilisateur ne
peut sortir d'une branche, quelle que soit la requête. Les noms de tables et de colonnes
viennent de `recherche_schema.TABLES` (constantes), jamais de l'appelant.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.recherche_fusion import Cle, CorrespondanceExacte, motif_reference
from app.recherche_schema import TABLES, TableRecherche, texte_normalise, titre_normalise

SEUIL_TRIGRAMME = 0.3
TERMES_MAX = 32
LONGUEUR_EXTRAIT = 280
_TEXTE_FICHE_MAX = 20_000


def termes(requete: str) -> list[str]:
    """Mots de la requête (lettres et chiffres seulement : aucun opérateur tsquery ne passe)."""
    return re.findall(r"[^\W_]+", requete.lower())[:TERMES_MAX]


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte.lower()) if not unicodedata.combining(c))


def extrait_autour(texte: str, mots: list[str], longueur: int = LONGUEUR_EXTRAIT) -> str:
    """Fenêtre de `longueur` caractères centrée sur le premier mot trouvé (sans casse ni
    accents), sinon le début du texte. « … » marque une coupe."""
    # NFC d'abord : un caractère précomposé = un caractère, donc la suppression des accents
    # garde les longueurs et les positions du texte normalisé valent pour le texte d'origine.
    texte = " ".join(unicodedata.normalize("NFC", texte or "").split())
    if len(texte) <= longueur:
        return texte
    normalise = _sans_accents(texte)
    positions = [p for p in (normalise.find(_sans_accents(m)) for m in mots) if p >= 0]
    debut = max(0, min(positions) - longueur // 3) if positions else 0
    debut = min(debut, max(0, len(texte) - longueur))
    morceau = texte[debut:debut + longueur]
    return ("…" if debut > 0 else "") + morceau + ("…" if debut + longueur < len(texte) else "")


def _tables(sources: frozenset[str]) -> list[TableRecherche]:
    return [TABLES[s] for s in ("document", "kb") if s in sources]


async def plein_texte(s: AsyncSession, requete: str, user_id: str, sources: frozenset[str],
                      limite: int) -> list[Cle]:
    """OU sur les termes, en `simple` et en `french`, classé par ts_rank_cd."""
    mots, tables = termes(requete), _tables(sources)
    if not mots or not tables:
        return []
    params: dict = {"moi": user_id, "limite": limite}
    morceaux = []
    for i, mot in enumerate(mots):
        params[f"t{i}"] = mot
        # La partie `simple` (qui garde codes et noms propres) n'est ajoutée que si `french` ne
        # tient pas le terme pour un mot vide : sinon « le », « de »… correspondraient, en `simple`,
        # à tous les titres qui contiennent ce mot (poids A) et noieraient les vrais résultats.
        morceaux.append(
            f"(CASE WHEN numnode(plainto_tsquery('french', forge_unaccent(:t{i}))) > 0 "
            f"THEN plainto_tsquery('simple', forge_unaccent(:t{i})) || "
            f"plainto_tsquery('french', forge_unaccent(:t{i})) ELSE ''::tsquery END)")
    unions = " UNION ALL ".join(
        f"SELECT '{t.source}' AS source, x.id, ts_rank_cd(x.recherche_tsv, q.r) AS rang, "
        f"x.created_at AS date FROM {t.table} x, q WHERE x.user_id = :moi AND x.recherche_tsv @@ q.r"
        for t in tables
    )
    sql = text(f"WITH q AS (SELECT ({' || '.join(morceaux)}) AS r) "
               f"SELECT source, id FROM ({unions}) u ORDER BY rang DESC, date DESC, id LIMIT :limite")
    return [(r[0], r[1]) for r in (await s.execute(sql, params)).all()]


def sql_trigrammes(tables: list[TableRecherche]) -> str:
    """Requête trigramme. Le filtre est l'OPÉRATEUR `<%` (seul usage possible de l'index GIN
    gin_trgm_ops), son seuil étant `pg_trgm.word_similarity_threshold` (posé par l'appelant)."""
    unions = []
    for t in tables:
        texte = texte_normalise(t, "x.")
        unions.append(f"SELECT '{t.source}' AS source, x.id, "
                      f"word_similarity(forge_unaccent(lower(:q)), {texte}) AS rang, x.created_at AS date "
                      f"FROM {t.table} x WHERE x.user_id = :moi AND forge_unaccent(lower(:q)) <% {texte}")
    return (f"SELECT source, id FROM ({' UNION ALL '.join(unions)}) u "
            f"ORDER BY rang DESC, date DESC, id LIMIT :limite")


async def termes_significatifs(s: AsyncSession, requete: str) -> list[str]:
    """Termes de la requête, dans l'ordre, que la configuration `french` ne tient pas pour des
    mots vides (« le », « de », « des »… donnent une tsquery vide)."""
    mots = termes(requete)
    if not mots:
        return []
    sql = text("SELECT t.m FROM unnest(CAST(:mots AS text[])) WITH ORDINALITY AS t(m, i) "
               "WHERE numnode(plainto_tsquery('french', forge_unaccent(t.m))) > 0 ORDER BY t.i")
    return [r[0] for r in (await s.execute(sql, {"mots": mots})).all()]


async def trigrammes(s: AsyncSession, requete: str, user_id: str, sources: frozenset[str],
                     limite: int) -> list[Cle]:
    """Filet pour les fautes de frappe, utilisé quand le plein texte ne trouve rien. Ne cherche
    que sur les termes significatifs : les mots vides feraient remonter des titres hors sujet."""
    tables = _tables(sources)
    if not tables:
        return []
    utiles = await termes_significatifs(s, requete)
    if not utiles:
        return []
    params = {"moi": user_id, "q": " ".join(utiles), "limite": limite}
    # SET LOCAL : valable pour la transaction en cours seulement (pas de paramètre lié possible).
    await s.execute(text(f"SET LOCAL pg_trgm.word_similarity_threshold = {float(SEUIL_TRIGRAMME)}"))
    return [(r[0], r[1]) for r in (await s.execute(text(sql_trigrammes(tables)), params)).all()]


async def _references_normalisees(s: AsyncSession, references: list[str]) -> list[str]:
    """Références passées par la MÊME normalisation que le texte, dans l'ordre d'origine."""
    sql = text("SELECT forge_unaccent(lower(r)) FROM unnest(CAST(:refs AS text[])) "
               "WITH ORDINALITY AS t(r, i) ORDER BY i")
    return [r[0] for r in (await s.execute(sql, {"refs": references})).all()]


async def exacts(s: AsyncSession, references: list[str], user_id: str, sources: frozenset[str],
                 limite: int) -> dict[Cle, CorrespondanceExacte]:
    """Documents contenant littéralement au moins une référence (mot entier, sans casse ni
    accents), avec le nombre de références trouvées et leur présence dans le titre."""
    tables = _tables(sources)
    if not references or not tables:
        return {}
    normalisees = [r for r in await _references_normalisees(s, references) if r and r.strip()]
    if not normalisees:
        return {}
    params: dict = {"moi": user_id, "limite": limite}
    for i, reference in enumerate(normalisees):
        params[f"r{i}"] = motif_reference(reference)
    unions = []
    for t in tables:
        comptes = " + ".join(f"(CASE WHEN {texte_normalise(t, 'x.')} ~ :r{i} THEN 1 ELSE 0 END)"
                             for i in range(len(normalisees)))
        titres = " OR ".join(f"{titre_normalise(t, 'x.')} ~ :r{i}" for i in range(len(normalisees)))
        unions.append(f"SELECT '{t.source}' AS source, x.id, x.created_at AS date, ({comptes}) AS trouvees, "
                      f"({titres}) AS dans_titre FROM {t.table} x WHERE x.user_id = :moi")
    sql = text(f"SELECT source, id, trouvees, dans_titre FROM ({' UNION ALL '.join(unions)}) u "
               f"WHERE trouvees > 0 ORDER BY trouvees DESC, dans_titre DESC, date DESC, id LIMIT :limite")
    return {(r[0], r[1]): CorrespondanceExacte(int(r[2]), bool(r[3]))
            for r in (await s.execute(sql, params)).all()}


async def existants(s: AsyncSession, cles: list[Cle], user_id: str) -> set[Cle]:
    """Recoupement : parmi `cles`, celles qui existent encore ET appartiennent à `user_id`.
    Écarte les fragments Qdrant orphelins (document supprimé) ou mal attribués."""
    trouvees: set[Cle] = set()
    for t in TABLES.values():
        ids = [i for (source, i) in cles if source == t.source]
        if not ids:
            continue
        lignes = await s.execute(
            text(f"SELECT id FROM {t.table} WHERE user_id = :moi AND id = ANY(CAST(:ids AS uuid[]))"),
            {"moi": user_id, "ids": [str(i) for i in ids]},
        )
        trouvees |= {(t.source, r[0]) for r in lignes.all()}
    return trouvees


@dataclass(frozen=True)
class Fiche:
    titre: str
    texte: str


async def fiches(s: AsyncSession, cles: list[Cle], user_id: str) -> dict[Cle, Fiche]:
    """Titre et début du contenu des résultats à afficher (toujours filtré par `user_id`)."""
    resultat: dict[Cle, Fiche] = {}
    for t in TABLES.values():
        ids = [i for (source, i) in cles if source == t.source]
        if not ids:
            continue
        lignes = await s.execute(
            text(f"SELECT id, {t.titre}, left(coalesce(contenu, ''), {_TEXTE_FICHE_MAX}) FROM {t.table} "
                 f"WHERE user_id = :moi AND id = ANY(CAST(:ids AS uuid[]))"),
            {"moi": user_id, "ids": [str(i) for i in ids]},
        )
        for r in lignes.all():
            resultat[(t.source, r[0])] = Fiche(r[1] or "", r[2] or "")
    return resultat
