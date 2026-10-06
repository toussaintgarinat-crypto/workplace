"""Recherche unifiée du Cœur (S241) : Forge + Ingestion + Mémoire, fusionnées par rang.

Chaque brique cherche dans sa propre base (qui fait foi) avec l'identité de l'appelant ; le
Cœur ne fait que fusionner (RRF, références exactes devant). Aucune source n'est
indispensable : une source en panne ou trop lente est signalée dans
`sources_indisponibles` et les autres répondent quand même. Si TOUTES échouent, on lève
`ToutesSourcesIndisponibles` — jamais une liste vide présentée comme un succès.

`partage` : vrai pour Ingestion (une seule clé de service, aucune isolation par personne) et
pour la Forge quand elle a cherché sous son identité de service (pas de jeton utilisateur), et
pour l'espace Mémoire `solution` (l'espace commun « Workplace » du cercle) ; `perso` et `veille`
restent privés.

Modes : `hybride` (sens + mots), `lexical` (le sens est coupé, repli sur les mots) et
`plein_texte` (Ingestion, qui n'a QUE les mots : ce n'est pas une panne). La réponse porte
`recherche_par_le_sens_indisponible` : noms des sources qui ont normalement la recherche par le
sens (Forge, espaces Mémoire) et qui ont répondu en `lexical` — l'onglet et l'outil s'appuient
dessus, jamais sur la valeur brute des `modes`.

Vocabulaire des sources indisponibles (réponse ET exception) : un espace Mémoire en panne seul
garde son nom `memoire-<espace>` ; si les trois espaces sont en panne, ils deviennent `memoire`.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

import orchestrateur
from outils_communs import _entetes_brique, entetes_forge_sortants

logger = logging.getLogger(__name__)

K_RRF = 60
DELAI_SOURCE = 8.0
LIMITE_MAX = 50
SOURCES = ("forge", "ingestion", "memoire")
ESPACES_MEMOIRE = ("perso", "solution", "veille")


def degradees(modes: dict[str, str]) -> list[str]:
    """Sources dont la recherche par le sens est coupée : celles qui l'ont normalement
    (Forge, Mémoire) et répondent en `lexical`. Ingestion (`plein_texte`) n'en fait jamais partie."""
    return [nom for nom, mode in modes.items()
            if mode == "lexical" and (nom == "forge" or nom.startswith("memoire-"))]


class ToutesSourcesIndisponibles(Exception):
    """Aucune source n'a répondu ; `args[0]` = la liste des sources tentées."""


@dataclass
class _Liste:
    nom: str
    mode: str
    resultats: list[dict]


def _resultat(source: str, x: dict, partage: bool, exact: bool) -> dict:
    return {"source": source, "id": str(x.get("id") or ""), "titre": x.get("titre") or "",
            "extrait": x.get("extrait") or "", "partage": partage, "exact": exact}


async def _forge(client: httpx.AsyncClient, registre, q: str, n: int) -> _Liste:
    base = orchestrateur._brique_base(registre, "forge")
    r = await client.get(f"{base}/documents/chercher", params={"q": q, "limite": n},
                         headers=entetes_forge_sortants())
    r.raise_for_status()
    d = r.json()
    partage = d.get("identite") != "utilisateur"
    return _Liste("forge", d.get("mode", "hybride"), [
        _resultat("forge-kb" if x.get("source") == "kb" else "forge-document", x, partage, bool(x.get("exact")))
        for x in d.get("resultats", [])])


async def _ingestion(client: httpx.AsyncClient, registre, q: str, n: int) -> _Liste:
    base = orchestrateur._brique_base(registre, "ingestion")
    r = await client.get(f"{base}/recherche", params={"q": q, "limite": n},
                         headers=_entetes_brique("ingestion"))
    r.raise_for_status()
    d = r.json()
    return _Liste("ingestion", d.get("mode", "plein_texte"), [
        _resultat("ingestion", x, True, bool(x.get("exact"))) for x in d.get("resultats", [])])


async def _memoire(client: httpx.AsyncClient, registre, q: str, n: int, espace: str) -> _Liste:
    base = orchestrateur._brique_base(registre, "memoire")
    r = await client.get(f"{base}/rappeler", params={"q": q, "limite": n, "espace": espace},
                         headers=_entetes_brique("memoire"))
    r.raise_for_status()
    d = r.json()
    return _Liste(f"memoire-{espace}", d.get("mode", "hybride"), [
        _resultat(f"memoire-{espace}", x, espace == "solution", x.get("correspondance") == "exacte")
        for x in d.get("souvenirs", [])])


def _replier_memoire(indisponibles: list[str]) -> list[str]:
    if all(f"memoire-{e}" in indisponibles for e in ESPACES_MEMOIRE):
        return [n for n in indisponibles if not n.startswith("memoire-")] + ["memoire"]
    return indisponibles


def fusionner(listes: list[_Liste], limite: int) -> list[dict]:
    """RRF sur les classements de chaque sous-source ; +1 pour une référence exacte (un score
    RRF vaut au plus 1/(K+1) par liste, donc un exact passe toujours devant)."""
    scores: dict[tuple[str, str], float] = {}
    fiches: dict[tuple[str, str], dict] = {}
    for liste in listes:
        for rang, x in enumerate(liste.resultats, start=1):
            cle = (x["source"], x["id"])
            scores[cle] = scores.get(cle, 0.0) + 1.0 / (K_RRF + rang) + (1.0 if x["exact"] else 0.0)
            fiches.setdefault(cle, x)
    ordre = sorted(scores, key=lambda c: (-scores[c], c[0], c[1]))[:limite]
    return [fiches[c] for c in ordre]


async def rechercher(q: str, registre, limite: int = 10, sources: set[str] | None = None,
                     transport=None) -> dict:
    q = (q or "").strip()
    if not q:
        return {"resultats": [], "modes": {}, "sources_indisponibles": [],
                "recherche_par_le_sens_indisponible": []}
    limite = min(max(int(limite), 1), LIMITE_MAX)
    inconnues = sorted(set(sources or ()) - set(SOURCES))
    if inconnues:
        raise ValueError("source inconnue : " + ", ".join(inconnues))
    voulues = [s for s in SOURCES if not sources or s in sources]
    async with httpx.AsyncClient(timeout=DELAI_SOURCE, transport=transport) as client:
        appels: dict = {}
        if "forge" in voulues:
            appels["forge"] = _forge(client, registre, q, limite)
        if "ingestion" in voulues:
            appels["ingestion"] = _ingestion(client, registre, q, limite)
        if "memoire" in voulues:
            for espace in ESPACES_MEMOIRE:
                appels[f"memoire-{espace}"] = _memoire(client, registre, q, limite, espace)
        reponses = await asyncio.gather(
            *(asyncio.wait_for(appel, DELAI_SOURCE) for appel in appels.values()), return_exceptions=True)
    listes, indisponibles = [], []
    for nom, reponse in zip(appels, reponses):
        if isinstance(reponse, BaseException):
            logger.warning("[recherche] source %s indisponible : %s", nom, str(reponse)[:160] or type(reponse).__name__)
            indisponibles.append(nom)
        else:
            listes.append(reponse)
    indisponibles = _replier_memoire(indisponibles)
    if appels and not listes:
        raise ToutesSourcesIndisponibles(indisponibles)
    modes = {l.nom: l.mode for l in listes}
    return {"resultats": fusionner(listes, limite), "modes": modes,
            "sources_indisponibles": indisponibles,
            "recherche_par_le_sens_indisponible": degradees(modes)}
