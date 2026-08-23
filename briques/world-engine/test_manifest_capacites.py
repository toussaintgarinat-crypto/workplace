"""Filet de contrat manifeste↔route (même motif que briques/personnages) : le
manifest est ce que le Cœur lit pour piloter world-engine — une capacité qui
pointe une route inexistante casserait l'assistant en silence."""
import json
import re
from pathlib import Path

import main


_ICI = Path(__file__).parent
_MANIFEST = json.loads((_ICI / "manifest.json").read_text())


def _gabarit(chemin: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", chemin)


def test_chaque_capacite_pointe_une_route_reelle():
    reelles = set()
    for r in main.app.routes:
        for methode in getattr(r, "methods", set()) or set():
            reelles.add((methode, _gabarit(getattr(r, "path", ""))))
    manquantes = [(c["nom"], c["methode"], c["chemin"]) for c in _MANIFEST["capacites"]
                  if (c["methode"], _gabarit(c["chemin"])) not in reelles]
    assert not manquantes, f"Capacités sans route correspondante : {manquantes}"


def test_noms_de_capacites_uniques():
    noms = [c["nom"] for c in _MANIFEST["capacites"]]
    assert len(noms) == len(set(noms))
