"""Catalogue de capacités (S63) — le « schéma corporel » du Cœur.

Construit, à partir des manifests du registre, la liste des CAPACITÉS appelables
qu'offrent les briques : chaque entrée = un outil potentiel (nom, description,
méthode + chemin HTTP, params, drapeau `action`). C'est la source de vérité
DÉCLARATIVE qui remplacera, au sprint suivant (S64), les specs d'outils câblées en
dur dans `outils.py` — un nerf qui pousse tout seul vers chaque brique au lieu d'être
soudé à la main.

Calque exact du motif `horloge.collecter_taches` : on lit le champ manifest
`capacites`, on normalise, on valide les champs requis, et on IGNORE en le signalant
toute déclaration incomplète plutôt que de casser la découverte. L'URL de base d'une
brique suit la même règle que l'orchestrateur (override d'env `{NOM}_URL`, sinon
`http://{BRIQUE_HOST}:{port}`).

Honnêteté : une capacité dont la brique n'a pas de port (frontend pur) ou dont les
champs requis manquent n'est pas inventée — elle est écartée avec un avertissement.

⚠ S63 ne CÂBLE rien au LLM : ce module se contente de DÉCOUVRIR et de présenter le
catalogue (endpoint `GET /capacites`). La génération des outils du LLM à partir de ce
catalogue, et le routage dynamique, sont le sujet de S64.
"""
import logging
import os

logger = logging.getLogger(__name__)

BRIQUE_HOST = os.environ.get("BRIQUE_HOST", "host.docker.internal")
_CHAMPS_REQUIS = ("nom", "chemin")


def base_brique(registre, nom: str) -> str | None:
    """URL de base d'une brique (override d'env prioritaire), ou None si introuvable.

    Même règle que `orchestrateur._brique_base`, mais NON bloquante : une brique sans
    port (frontend pur, ex. app-builder) renvoie None et sera écartée du catalogue."""
    override = os.environ.get(f"{nom.upper()}_URL")
    if override:
        return override.rstrip("/")
    port = (registre.briques.get(nom) or {}).get("port")
    if not port:
        return None
    return f"http://{BRIQUE_HOST}:{port}"


def _niveau(brut) -> int:
    """Niveau de divulgation déclaré (entier ≥ 0), tolérant : valeur absente/illisible → 0."""
    try:
        return max(0, int(brut))
    except (TypeError, ValueError):
        return 0


def collecter_capacites(registre) -> list[dict]:
    """Découvre toutes les capacités déclarées par les briques (champ manifest `capacites`).

    Renvoie une liste normalisée d'entrées appelables :
    ``{nom, brique, description, methode, chemin, url, params, action}``.

    Ignore — en le signalant — toute capacité incomplète (champs requis manquants) ou
    déclarée par une brique non joignable (ni port ni override d'env)."""
    capacites: list[dict] = []
    for nom_brique, manifest in registre.briques.items():
        decls = manifest.get("capacites", []) or []
        if not decls:
            continue
        base = base_brique(registre, nom_brique)
        if base is None:
            logger.warning("Catalogue : brique '%s' déclare des capacités mais n'a pas "
                           "de port/override — ignorées", nom_brique)
            continue
        for decl in decls:
            if not all(decl.get(c) for c in _CHAMPS_REQUIS):
                logger.warning("Catalogue : capacité incomplète ignorée dans '%s' : %r",
                               nom_brique, decl)
                continue
            chemin = decl["chemin"]
            if not chemin.startswith("/"):
                chemin = "/" + chemin
            capacites.append({
                "nom": decl["nom"],
                "brique": nom_brique,
                "description": decl.get("description", ""),
                "methode": (decl.get("methode") or "GET").upper(),
                "chemin": chemin,
                "url": base + chemin,
                "params": dict(decl.get("params") or {}),
                "action": bool(decl.get("action", False)),
                # S90 — porte à divulgation progressive
                "niveau": _niveau(decl.get("niveau")),
                # S134 — socle:true = toujours inclus dans le routage par embeddings
                "socle": bool(decl.get("socle", False)),
            })
    return capacites


def doublons(capacites: list[dict]) -> list[str]:
    """Noms de capacités déclarés par PLUSIEURS briques (collision à arbitrer en S64).

    Le LLM exige des noms d'outils uniques : on remonte les doublons pour pouvoir les
    préfixer/écarter au moment du câblage, plutôt que de les masquer silencieusement."""
    vus: set = set()
    dup: list = []
    for c in capacites:
        nom = c["nom"]
        if nom in vus and nom not in dup:
            dup.append(nom)
        vus.add(nom)
    return dup
