"""Recherche hybride des documents et de la base de connaissances Forge (S241).

PostgreSQL fait foi, Qdrant n'est qu'un index : les fragments vectoriels sont RECOUPÉS avec
PostgreSQL (existence + propriétaire) avant toute fusion. Embedder ou Qdrant en panne → mode
« lexical », annoncé, jamais une liste vide présentée comme un succès.
"""
from __future__ import annotations

from uuid import UUID

from app import memory
from app import recherche_documents as rd
from app.db import SessionLocal
from app.recherche_fusion import Cle, extraire_references, ordonner

SOURCES: frozenset[str] = frozenset({"document", "kb"})
_TYPE_VERS_SOURCE = {"document": "document", "kb_article": "kb"}


def _borner(limite: int) -> int:
    return min(max(int(limite), 1), 50)


async def _branche_vectorielle(requete: str, user_id: str, sources: frozenset[str],
                               candidats: int) -> tuple[str, list[Cle], dict[Cle, str]]:
    """(mode, clés par meilleur fragment, extrait du meilleur fragment par clé)."""
    try:
        fragments = await memory.chercher_fragments(requete, user_id, limite=candidats * 3)
    except memory.RechercheVectorielleIndisponible:
        return "lexical", [], {}
    cles: list[Cle] = []
    extraits: dict[Cle, str] = {}
    for f in sorted(fragments, key=lambda f: -f.score):
        source = _TYPE_VERS_SOURCE.get(f.source_type)
        if source not in sources:
            continue
        try:
            cle = (source, UUID(f.source_id))
        except ValueError:
            continue
        if cle not in extraits:
            extraits[cle] = f.texte
            cles.append(cle)
    return "hybride", cles, extraits


async def rechercher(requete: str, user_id: str, limite: int = 10,
                     sources: frozenset[str] = SOURCES) -> dict:
    requete = (requete or "").strip()
    sources = frozenset(sources) & SOURCES
    if not requete or not sources:
        return {"mode": "hybride", "resultats": []}
    limite = _borner(limite)
    candidats = limite * 3

    async with SessionLocal() as s:
        exacts = await rd.exacts(s, extraire_references(requete), user_id, sources, candidats)
        lexical = await rd.plein_texte(s, requete, user_id, sources, candidats)
        if not lexical:
            lexical = await rd.trigrammes(s, requete, user_id, sources, candidats)

    mode, vectoriel, extraits_vect = await _branche_vectorielle(requete, user_id, sources, candidats)

    async with SessionLocal() as s:
        if vectoriel:
            presents = await rd.existants(s, vectoriel, user_id)
            vectoriel = [c for c in vectoriel if c in presents]
        classes = ordonner(exacts, lexical, vectoriel, limite)
        fiches = await rd.fiches(s, [c.cle for c in classes], user_id)

    mots = rd.termes(requete)
    resultats = []
    for c in classes:
        fiche = fiches.get(c.cle)
        if fiche is None:  # supprimé entre les deux lectures
            continue
        if c.correspondance == "vectorielle":
            extrait = rd.extrait_autour(extraits_vect.get(c.cle, ""), mots)
        else:
            extrait = rd.extrait_autour(fiche.texte, mots)
        resultats.append({"id": str(c.cle[1]), "source": c.cle[0], "titre": fiche.titre,
                          "extrait": extrait, "rang": len(resultats) + 1,
                          "exact": c.correspondance == "exacte"})
    return {"mode": mode, "resultats": resultats}
