"""Test de DÉCOUVERTE : le manifest est le contrat que le Cœur lit pour piloter Personnages.

Garantit que chaque capacité pointe une route RÉELLE (même méthode + gabarit de chemin), et
que la clé d'intégration `PERSONNAGES_KEY` est bien fusionnée dans les clés acceptées (style
« clé fusionnée » de l'ADR surface-de-service, S167) → l'assistant pilote la brique même
sous auth BYO. Ajouter une capacité au manifest suffit à la rendre pilotable (zéro code Cœur)."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import main

_ICI = Path(__file__).parent
_MANIFEST = json.loads((_ICI / "manifest.json").read_text())


def _gabarit(chemin: str) -> str:
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


def test_nouvelles_capacites_t4_presentes():
    noms = {c["nom"] for c in _MANIFEST["capacites"]}
    attendues = {
        "personnage_fiche_ranger", "personnage_holistique_traditions",
        "personnage_holistique_lecture", "personnage_recherche_inverse",
        "personnages_distributions_lister", "personnage_distribution_lire",
        "personnage_distribution_creer", "personnage_distribution_modifier",
        "personnage_distribution_supprimer", "personnage_distribution_proposer_dans",
        "personnage_distribution_perso_ajouter", "personnage_distribution_perso_modifier",
        "personnage_distribution_perso_retirer", "personnage_distribution_caster",
    }
    assert attendues <= noms, f"Capacités T4 manquantes : {attendues - noms}"


def test_ecritures_marquees_action():
    """Toute écriture (POST/PATCH/DELETE) est action:true SAUF les analyses/propositions en
    lecture (holistique, proposer) qui ne persistent rien → pas de gate de confirmation."""
    lecture_via_post = {
        "personnage_distribution_proposer", "personnage_portrait_generer",
        "personnage_distribution_proposer_dans", "personnage_holistique_traditions",
        "personnage_holistique_lecture", "personnage_recherche_inverse",
        "personnage_theme_complet",
    }
    for c in _MANIFEST["capacites"]:
        if c["methode"] in ("POST", "PATCH", "DELETE") and c["nom"] not in lecture_via_post:
            assert c["action"] is True, f"{c['nom']} devrait être action:true"


def test_personnages_key_fusionnee_sous_auth():
    """Câblage à l'import : avec une auth BYO active (API_KEYS), la PERSONNAGES_KEY injectée
    par le Cœur est acceptée — sinon l'assistant serait rejeté (401). Vérifié en sous-process
    car API_KEYS/PERSONNAGES_KEY sont lus une fois à l'import du module."""
    code = (
        "import main;"
        "assert 'cle-coeur-xyz' in main.API_KEYS, main.API_KEYS;"
        "assert main.cle_api(x_api_key='cle-coeur-xyz', authorization=None) == 'cle-coeur-xyz';"
        "import fastapi;"
        "\ntry:\n"
        "    main.cle_api(x_api_key='intrus', authorization=None); raise SystemExit('intrus accepté')\n"
        "except fastapi.HTTPException as e:\n"
        "    assert e.status_code == 401\n"
        "print('OK')"
    )
    env = {**os.environ, "PERSONNAGES_KEY": "cle-coeur-xyz", "API_KEYS": "byo-standalone",
           "PERSONNAGES_DB": os.path.join(os.environ.get("TMPDIR", "/tmp"), "pk_merge_test.db")}
    r = subprocess.run([sys.executable, "-c", code], cwd=str(_ICI), env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0 and "OK" in r.stdout, f"stdout={r.stdout!r} stderr={r.stderr!r}"
