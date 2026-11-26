"""Inventaire des sauvegardes par application (S247) : ce que contient chaque app (bases Postgres,
volumes) et où sont ses sauvegardes. Fichier JSON tenu à la main par l'exploitant (jamais deviné :
une app absente ou une entrée mal formée ne sont PAS sauvegardées « au hasard », on refuse)."""
import json
import os
import re
from pathlib import Path
from typing import Optional

_CHAMPS_BASE = ("base", "service", "utilisateur", "sauvegarde_id", "prefixe_s3")
_RE_PREFIXE = re.compile(r"^[A-Za-z0-9._/-]{1,150}$")


def _chemin() -> Path:
    explicite = os.getenv("LIVRAISON_INVENTAIRE")
    return Path(explicite) if explicite else Path(os.getenv("LIVRAISON_DATA", "/data")) / "inventaire.json"


def _valide(e) -> bool:
    if not isinstance(e, dict):
        return False
    bases, volumes = e.get("bases", []), e.get("volumes", [])
    if not isinstance(bases, list) or not isinstance(volumes, list) or not (bases or volumes):
        return False
    for b in bases:
        if not (isinstance(b, dict) and all(isinstance(b.get(c), str) and b[c] for c in _CHAMPS_BASE)):
            return False
        if not _RE_PREFIXE.match(b["prefixe_s3"]) or ".." in b["prefixe_s3"] \
                or b["prefixe_s3"].startswith("/"):
            return False
    return all(isinstance(v, dict) and isinstance(v.get("volume_backup_id"), str)
               and v["volume_backup_id"] for v in volumes)


def lire(nom_app: str) -> Optional[dict]:
    try:
        d = json.loads(_chemin().read_text())
    except (OSError, ValueError):
        return None
    e = d.get((nom_app or "").strip().lower()) if isinstance(d, dict) else None
    if not _valide(e):
        return None
    return {"bases": list(e.get("bases", [])), "volumes": list(e.get("volumes", []))}
