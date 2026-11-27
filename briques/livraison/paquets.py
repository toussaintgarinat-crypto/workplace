"""Registre des paquets de données utilisateur (S248 3a) : métadonnées seulement, JAMAIS le
contenu ni l'identité en clair (empreinte sha256[:16]). Écriture atomique ; toute erreur disque
à la lecture se lit comme « rien » (on n'agit pas sur un registre illisible). Journal d'accès
JSONL : qui/quoi/quand, jamais de contenu."""
import hashlib
import json
import math
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
           "cree_a": now, "expire_a": now + RETENTION_S, "verifie_a": None, "consomme_a": None,
           "restitue_a": None}
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


def marquer_restitue(paquet_id: str, maintenant: Optional[float] = None) -> Optional[dict]:
    """Un paquet restitué ne doit plus être ré-importé implicitement par-dessus des données plus
    récentes."""
    tout = _lire_strict()
    r = tout.get(paquet_id)
    if not isinstance(r, dict):
        return None
    r["restitue_a"] = maintenant if maintenant is not None else time.time()
    _ecrire_tout(tout)
    return r


def _date_verif(r: dict, now: float) -> Optional[float]:
    """`verifie_a` utilisable (fini, <= now) d'un enregistrement non expiré, sinon None."""
    try:
        v = r.get("verifie_a")
        if v is None or _est_expire(r, now):
            return None
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v <= now else None


def dernier_verifie(app: str, h: str, maintenant: Optional[float] = None,
                    preuve_s: Optional[float] = PREUVE_TTL_S,
                    inclure_consommes: bool = False) -> Optional[dict]:
    """Paquet (app, h) vérifié le plus récemment, non expiré, preuve fraîche si preuve_s ;
    lecteur pur : une date illisible, non finie ou future rend l'entrée inéligible."""
    now = maintenant if maintenant is not None else time.time()
    candidats = []
    for r in _lire_tout().values():
        if not (isinstance(r, dict) and r.get("app") == app and r.get("h") == h):
            continue
        v = _date_verif(r, now)
        if v is None:
            continue
        if not inclure_consommes and r.get("consomme_a") is not None:
            continue
        if preuve_s is not None and v + preuve_s <= now:
            continue
        candidats.append((v, r))
    return max(candidats, key=lambda c: c[0])[1] if candidats else None


def dernier_a_restituer(app: str, h: str, maintenant: Optional[float] = None) -> Optional[dict]:
    """Choix implicite d'une restitution : le paquet vérifié, non expiré, CONSOMMÉ (donc utilisé
    pour un effacement) et pas encore restitué, le plus récemment consommé ; à défaut, le dernier
    vérifié non consommé. Jamais le plus frais vérifié : après un reset douteux, une nouvelle
    vérification photographie un état vide ou partiel."""
    now = maintenant if maintenant is not None else time.time()
    candidats = []
    for r in _lire_tout().values():
        if not (isinstance(r, dict) and r.get("app") == app and r.get("h") == h):
            continue
        if _date_verif(r, now) is None or r.get("restitue_a") is not None:
            continue
        try:
            c = r.get("consomme_a")
            if c is None:
                continue
            c = float(c)
        except (TypeError, ValueError):
            continue
        if math.isfinite(c):
            candidats.append((c, r))
    if candidats:
        return max(candidats, key=lambda c: c[0])[1]
    return dernier_verifie(app, h, now, preuve_s=None)


def _est_expire(r: dict, now: float) -> bool:
    try:
        e = float(r.get("expire_a", 0))
        return not math.isfinite(e) or e <= now
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
