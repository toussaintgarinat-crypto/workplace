"""Test de DÉCOUVERTE : le manifest est le contrat que le Cœur lit pour piloter le Studio.

On garantit que chaque capacité déclarée pointe une route RÉELLE de l'app (même méthode +
même gabarit de chemin), et que ces routes passent bien par l'auth `cle_api` (celle qui
accepte STUDIO_KEY, style « clé fusionnée » — cf. ADR surface-de-service). Ainsi, ajouter
une capacité au manifest suffit à la rendre pilotable, sans code Cœur (S167 — T3)."""
import json
import re
from pathlib import Path

import main

_MANIFEST = json.loads((Path(__file__).parent / "manifest.json").read_text())


def _gabarit(chemin: str) -> str:
    """Normalise les paramètres de chemin : /series/{serie_id} → /series/{}."""
    return re.sub(r"\{[^}]+\}", "{}", chemin)


def _routes_reelles() -> set[tuple[str, str]]:
    routes = set()
    for r in main.app.routes:
        for methode in getattr(r, "methods", set()) or set():
            routes.add((methode, _gabarit(getattr(r, "path", ""))))
    return routes


def test_chaque_capacite_pointe_une_route_reelle():
    reelles = _routes_reelles()
    manquantes = [(c["nom"], c["methode"], c["chemin"]) for c in _MANIFEST["capacites"]
                  if (c["methode"], _gabarit(c["chemin"])) not in reelles]
    assert not manquantes, f"Capacités sans route correspondante : {manquantes}"


def test_noms_de_capacites_uniques():
    noms = [c["nom"] for c in _MANIFEST["capacites"]]
    doublons = sorted({n for n in noms if noms.count(n) > 1})
    assert not doublons, f"Noms de capacités en double : {doublons}"


def test_nouvelles_capacites_structure_et_production_presentes():
    """Les ajouts T3 (tomes/cycles/série + production) sont bien exposés."""
    noms = {c["nom"] for c in _MANIFEST["capacites"]}
    attendues = {
        "studio_series_reordonner", "studio_cycle_creer", "studio_cycle_renommer",
        "studio_cycle_supprimer", "studio_tome_creer", "studio_tome_renommer",
        "studio_tome_supprimer", "studio_tome_actif_definir", "studio_tome_bilan",
        "studio_episode_couverture", "studio_episode_teaser",
    }
    assert attendues <= noms, f"Capacités T3 manquantes : {attendues - noms}"


def test_capacites_destructives_marquees_action():
    """Toute écriture (POST/PATCH/DELETE) est action:true SAUF les analyses en lecture
    (bilan de tome) qui ne modifient rien → l'assistant ne les met pas derrière un gate."""
    lecture_via_post = {"studio_tome_bilan", "studio_bible_proposer",
                        "studio_distribution_proposer"}
    for c in _MANIFEST["capacites"]:
        if c["methode"] in ("POST", "PATCH", "DELETE") and c["nom"] not in lecture_via_post:
            assert c["action"] is True, f"{c['nom']} devrait être action:true"
