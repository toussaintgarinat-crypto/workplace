"""Registre des preuves de sauvegarde par application (S247).

Une preuve = « la dernière sauvegarde de cette app a été restaurée dans une instance jetable et
les contrôles (santé, comptages) sont passés ». Elle est la condition de toute action `donnees`
(reset, bascule). Une preuve `invalide` plus récente ANNULE une preuve valide plus ancienne
(la dernière vérification fait foi). Toute erreur disque se lit comme « aucune preuve » : on
refuse d'agir, on ne devine pas.
"""
import json
import os
import time
from pathlib import Path
from typing import Optional

PREUVE_TTL_S = 6 * 3600


def _chemin() -> Path:
    return Path(os.getenv("LIVRAISON_DATA", "/data")) / "preuves_sauvegarde.json"


def _lire_tout() -> dict:
    try:
        d = json.loads(_chemin().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def lire(app_id: str) -> Optional[dict]:
    r = _lire_tout().get(app_id)
    return r if isinstance(r, dict) and r.get("preuve_id") else None


def valide(app_id: str, maintenant: Optional[float] = None) -> Optional[dict]:
    now = maintenant if maintenant is not None else time.time()
    r = lire(app_id)
    if not r or r.get("verdict") != "valide":
        return None
    try:
        expire_a = float(r.get("expire_a", 0))
    except (TypeError, ValueError):
        return None
    return r if expire_a > now else None


def noter(app_id: str, preuve_id: str, verdict: str, comptages: dict,
          maintenant: Optional[float] = None) -> dict:
    now = maintenant if maintenant is not None else time.time()
    rec = {"preuve_id": preuve_id, "verdict": verdict, "comptages": comptages,
           "cree_a": now, "expire_a": now + PREUVE_TTL_S if verdict == "valide" else now}
    tout = _lire_tout()
    tout[app_id] = rec
    p = _chemin()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(tout))
    tmp.replace(p)
    return rec
