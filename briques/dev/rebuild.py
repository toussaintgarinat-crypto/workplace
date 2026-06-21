"""Rebuild CIBLÉ d'une brique après fusion — la seule brique modifiée, jamais toute la stack.

Chaque brique de Workplace porte son propre `docker-compose.yml` (service = nom de la brique,
`build: .`). Quand une fusion touche `briques/<nom>/`, on rebuild **uniquement** ce service.

Honnêteté avant tout : par défaut on **simule** (on journalise la commande exacte sans
l'exécuter) — déployer pour de vrai depuis l'atelier est un effet de bord lourd, réservé au cas
où l'utilisateur l'arme explicitement via `DEV_REBUILD=1`. On ne prétend jamais avoir déployé
quand on n'a pas déployé.
"""
from __future__ import annotations

import os
import subprocess

# Racine du dépôt (même défaut que git_atelier) : on en dérive le chemin de chaque brique.
REPO = os.environ.get("DEV_REPO", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


def commande_rebuild(brique: str, repo: str = REPO) -> list:
    """Commande `docker compose` qui rebuild + redémarre la SEULE brique ciblée."""
    compose = os.path.join(repo, "briques", brique, "docker-compose.yml")
    return ["docker", "compose", "-f", compose, "up", "-d", "--build", brique]


def rebuild_brique(brique: str, repo: str = REPO, reel: bool | None = None) -> dict:
    """Rebuild ciblé d'une brique. SIMULÉ par défaut ; réel seulement si armé.

    `reel=None` → on lit `DEV_REBUILD` (== "1" pour exécuter). Renvoie un compte rendu honnête :
    `{"reel", "commande", "ok", "note"}` — et en mode réel, le code de retour + un extrait."""
    reel = (os.environ.get("DEV_REBUILD") == "1") if reel is None else reel
    cmd = commande_rebuild(brique, repo)
    affiche = " ".join(cmd)
    if not reel:
        return {"reel": False, "commande": affiche, "ok": True,
                "note": "rebuild SIMULÉ (honnête) : commande non exécutée. Arme DEV_REBUILD=1 "
                        "pour rebuild réellement la brique."}
    compose = os.path.join(repo, "briques", brique, "docker-compose.yml")
    if not os.path.isfile(compose):
        return {"reel": True, "commande": affiche, "ok": False,
                "note": f"compose introuvable : {compose}"}
    proc = subprocess.run(cmd, capture_output=True, text=True)
    sortie = (proc.stdout + proc.stderr).strip()
    return {"reel": True, "commande": affiche, "ok": proc.returncode == 0,
            "code": proc.returncode, "note": sortie[-1500:]}
