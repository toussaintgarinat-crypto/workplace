"""Correspondance interlocuteur externe → utilisateur Workplace (multi-utilisateur).

Le pont est multi-utilisateur : chaque interlocuteur d'un réseau (un numéro WhatsApp, un
chat Telegram, un utilisateur Discord) est rattaché à un utilisateur Workplace, avec
CONSENTEMENT. Par défaut (`CONNEXION_OUVERT=0`), un inconnu ne traverse PAS : on l'enregistre
« en attente » avec un code de liaison, et un administrateur le relie via l'API
`/correspondances`. En mode ouvert (`CONNEXION_OUVERT=1`, pratique en dev), tout le monde
passe (rattaché à `CONNEXION_UTILISATEUR_DEFAUT`).

⚠️ Honnêteté technique : ce rattachement sert au routage / au journal / au consentement CÔTÉ
brique. L'endpoint `/assistant/chat` du Cœur n'isole pas (encore) les permissions par
utilisateur ; on injecte seulement un message *système* « qui parle » (cf. pont.py).
"""
import os
import secrets
import time

import stockage

FICHIER = "correspondances.json"


def _vrai(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "oui", "yes", "on")


def ouvert() -> bool:
    return _vrai(os.getenv("CONNEXION_OUVERT", "0"))


def _cle(reseau: str, id_externe: str) -> str:
    return f"{reseau}:{id_externe}"


def _code() -> str:
    return secrets.token_hex(3).upper()          # ex. « A1B2C3 »


def table() -> dict:
    t = stockage.lire_json(FICHIER, {})
    return t if isinstance(t, dict) else {}


def _sauver(t: dict) -> None:
    stockage.ecrire_json(FICHIER, t)


def resoudre(reseau: str, id_externe: str, nom: str | None = None) -> dict:
    """Décide si un interlocuteur est autorisé, en l'enregistrant au passage.

    Renvoie {autorise, utilisateur, statut, code, nouveau}. `nouveau` = première fois qu'on
    voit cet interlocuteur (le pont s'en sert pour un message d'accueil)."""
    t = table()
    cle = _cle(reseau, id_externe)
    e = t.get(cle)
    nouveau = e is None

    if e is None:
        statut = "ouvert" if ouvert() else "en_attente"
        utilisateur = os.getenv("CONNEXION_UTILISATEUR_DEFAUT") if ouvert() else None
        e = {"reseau": reseau, "id_externe": id_externe, "nom": nom,
             "utilisateur": utilisateur, "statut": statut, "code": _code(),
             "vu_le": time.time()}
        t[cle] = e
        _sauver(t)
    elif nom and e.get("nom") != nom:                # garde le nom affiché à jour
        e["nom"] = nom
        _sauver(t)

    autorise = e.get("statut") in ("lie", "ouvert")
    return {"autorise": autorise, "utilisateur": e.get("utilisateur"),
            "statut": e.get("statut"), "code": e.get("code"),
            "nom": e.get("nom"), "nouveau": nouveau}


def lier(reseau: str, id_externe: str, utilisateur: str) -> dict:
    """Relie (consentement administrateur) un interlocuteur à un utilisateur Workplace."""
    t = table()
    cle = _cle(reseau, id_externe)
    e = t.get(cle) or {"reseau": reseau, "id_externe": id_externe,
                       "code": _code(), "vu_le": time.time()}
    e.update(statut="lie", utilisateur=utilisateur, lie_le=time.time())
    t[cle] = e
    _sauver(t)
    return e


def lier_par_code(code: str, utilisateur: str) -> dict | None:
    """Relie par code de liaison (l'interlocuteur communique son code à l'admin)."""
    t = table()
    code = (code or "").strip().upper()
    for cle, e in t.items():
        if e.get("code") == code:
            e.update(statut="lie", utilisateur=utilisateur, lie_le=time.time())
            _sauver(t)
            return e
    return None


def delier(reseau: str, id_externe: str) -> bool:
    t = table()
    cle = _cle(reseau, id_externe)
    if cle in t:
        del t[cle]
        _sauver(t)
        return True
    return False


def lister() -> list:
    return list(table().values())
