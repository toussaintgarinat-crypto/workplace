"""Mémoire du dernier rollback par application.

Dokploy n'ajoute AUCUNE entrée `deployments[]` après `rollback.rollback` (constaté en réel,
S246 T12) : sans cette mémoire, `/etat` continue d'annoncer comme « en service » le dernier
déploiement alors que le service tourne sur une version antérieure. On retient, par application,
quel déploiement était le plus récent AU MOMENT du rollback (`dernier_id`) et lequel a été
visé (`cible_id`). Tant qu'aucun nouveau déploiement n'apparaît (le plus récent est toujours
`dernier_id`), la cible est la version en service ; dès qu'un déploiement plus récent existe, le
repère est périmé et ignoré.

Persistance : un petit JSON dans `LIVRAISON_DATA` (volume Docker). Toute erreur disque est
avalée : perdre le repère dégrade l'affichage, il ne doit jamais faire échouer une action.
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def _chemin() -> Path:
    return Path(os.getenv("LIVRAISON_DATA", "/data")) / "reperes_rollback.json"


def _lire_tout() -> dict:
    try:
        d = json.loads(_chemin().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def lire(app_id: str) -> Optional[dict]:
    r = _lire_tout().get(app_id)
    return r if isinstance(r, dict) and r.get("dernier_id") and r.get("cible_id") else None


def noter(app_id: str, dernier_id: str, cible_id: str) -> None:
    try:
        tout = _lire_tout()
        tout[app_id] = {"dernier_id": dernier_id, "cible_id": cible_id}
        p = _chemin()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(tout))
        tmp.replace(p)
    except OSError:
        log.warning("repère de rollback non enregistré (disque)", exc_info=True)
