"""Registre des paquets de données utilisateur (S248 3a) : métadonnées seulement, JAMAIS le
contenu ni l'identité en clair (empreinte sha256[:16]). Écriture atomique ; toute erreur disque
à la lecture se lit comme « rien » (on n'agit pas sur un registre illisible). Journal d'accès
JSONL : qui/quoi/quand, jamais de contenu."""
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Optional

RETENTION_S = 14 * 86400
PREUVE_TTL_S = 6 * 3600
_RE_APP = re.compile(r"[a-z0-9_-]{1,40}")
_RE_H = re.compile(r"[0-9a-f]{16}")
_RE_ID = re.compile(r"[0-9a-f]{32}")


def _dossier() -> Path:
    return Path(os.getenv("LIVRAISON_DATA", "/data"))


def _chemin() -> Path:
    return _dossier() / "paquets.json"


def empreinte_utilisateur(utilisateur: str) -> str:
    return hashlib.sha256(utilisateur.encode("utf-8")).hexdigest()[:16]


def nouveau_id() -> str:
    return secrets.token_hex(16)


def cle_objet(app: str, h: str, paquet_id: str) -> str:
    if not (_RE_APP.fullmatch(app) and _RE_H.fullmatch(h) and _RE_ID.fullmatch(paquet_id)):
        raise ValueError("composant d'objet invalide")
    return f"contrat/{app}/{h}/{paquet_id}.bin"


def _lire_tout() -> dict:
    try:
        d = json.loads(_chemin().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _lire_strict() -> dict:
    """Pour les ÉCRIVAINS : fichier absent = registre vide ; présent mais illisible = on refuse
    (sinon l'écriture suivante écraserait les autres entrées)."""
    p = _chemin()
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        raise OSError("registre illisible") from None
    if not isinstance(d, dict):
        raise OSError("registre illisible")
    return d


def _ecrire_tout(tout: dict) -> None:
    p = _chemin()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(tout))
    tmp.replace(p)


def enregistrer(paquet_id: str, app: str, h: str, objet: str, empreinte: str, comptages: dict,
                version_schema: str, maintenant: Optional[float] = None) -> dict:
    now = maintenant if maintenant is not None else time.time()
    rec = {"id": paquet_id, "app": app, "h": h, "objet": objet, "empreinte": empreinte,
           "comptages": comptages, "version_schema": version_schema,
           "cree_a": now, "expire_a": now + RETENTION_S, "verifie_a": None, "consomme_a": None}
    tout = _lire_strict()
    tout[paquet_id] = rec
    _ecrire_tout(tout)
    return rec


def lire(paquet_id: str) -> Optional[dict]:
    r = _lire_tout().get(paquet_id)
    return r if isinstance(r, dict) and r.get("id") == paquet_id else None


def marquer_verifie(paquet_id: str, maintenant: Optional[float] = None) -> Optional[dict]:
    tout = _lire_strict()
    r = tout.get(paquet_id)
    if not isinstance(r, dict):
        return None
    r["verifie_a"] = maintenant if maintenant is not None else time.time()
    _ecrire_tout(tout)
    return r


def marquer_consomme(paquet_id: str, maintenant: Optional[float] = None) -> Optional[dict]:
    """Un paquet utilisé pour un reset ne peut plus autoriser un second reset."""
    tout = _lire_strict()
    r = tout.get(paquet_id)
    if not isinstance(r, dict):
        return None
    r["consomme_a"] = maintenant if maintenant is not None else time.time()
    _ecrire_tout(tout)
    return r


def dernier_verifie(app: str, h: str, maintenant: Optional[float] = None,
                    preuve_s: Optional[float] = PREUVE_TTL_S,
                    inclure_consommes: bool = False) -> Optional[dict]:
    """Paquet (app, h) vérifié le plus récemment, non expiré, preuve fraîche si preuve_s ;
    lecteur pur : une date illisible rend l'entrée inéligible, jamais d'exception."""
    now = maintenant if maintenant is not None else time.time()
    candidats = []
    for r in _lire_tout().values():
        if not (isinstance(r, dict) and r.get("app") == app and r.get("h") == h):
            continue
        try:
            v = r.get("verifie_a")
            if v is None or _est_expire(r, now):
                continue
            v = float(v)
            if not inclure_consommes and r.get("consomme_a") is not None:
                continue
            if preuve_s is not None and v + preuve_s <= now:
                continue
        except (TypeError, ValueError):
            continue
        candidats.append((v, r))
    return max(candidats, key=lambda c: c[0])[1] if candidats else None


def _est_expire(r: dict, now: float) -> bool:
    try:
        return float(r.get("expire_a", 0)) <= now
    except (TypeError, ValueError):
        return True     # date illisible : traité comme expiré, pour que l'entrée soit purgée


def expires(maintenant: Optional[float] = None) -> list:
    now = maintenant if maintenant is not None else time.time()
    return [r for r in _lire_tout().values() if isinstance(r, dict) and _est_expire(r, now)]


def retirer(paquet_id: str) -> None:
    tout = _lire_strict()
    if paquet_id in tout:
        del tout[paquet_id]
        _ecrire_tout(tout)


def journaliser(operation: str, app: str, h: str, paquet_id: str, ok: bool,
                maintenant: Optional[float] = None) -> None:
    ligne = {"t": maintenant if maintenant is not None else time.time(), "operation": operation,
             "app": app, "h": h, "paquet": paquet_id, "ok": bool(ok)}
    p = _dossier() / "acces.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(ligne) + "\n")
