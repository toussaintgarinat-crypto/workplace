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


def _rattacher(e: dict, utilisateur: str) -> None:
    """Passe une entrée à « lie ». Le droit d'approbation (S245) suit le COMPTE : conservé si
    on relie au même utilisateur, retiré si l'entrée change de compte (jamais transmis)."""
    if e.get("utilisateur") != utilisateur:
        e.pop("approbateur", None)
    e.update(statut="lie", utilisateur=utilisateur, lie_le=time.time())


def lier(reseau: str, id_externe: str, utilisateur: str) -> dict:
    """Relie (consentement administrateur) un interlocuteur à un utilisateur Workplace."""
    t = table()
    cle = _cle(reseau, id_externe)
    e = t.get(cle) or {"reseau": reseau, "id_externe": id_externe,
                       "code": _code(), "vu_le": time.time()}
    _rattacher(e, utilisateur)
    t[cle] = e
    _sauver(t)
    return e


def lier_par_code(code: str, utilisateur: str) -> dict | None:
    """Relie par code de liaison (l'interlocuteur communique son code à l'admin)."""
    t = table()
    code = (code or "").strip().upper()
    for cle, e in t.items():
        if e.get("code") == code:
            _rattacher(e, utilisateur)
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


def cibles_pour(utilisateur: str) -> list:
    """Toutes les cibles (reseau, id_externe) rattachées à un utilisateur Workplace.

    Sert l'envoi PROACTIF (rappels d'agenda poussés par le Cœur) : on retrouve où
    joindre l'utilisateur sur ses messageries. Ne renvoie que les interlocuteurs
    autorisés (statut « lie » ou « ouvert »). Liste vide = personne à joindre (repli
    honnête côté appelant : aucun envoi, pas d'erreur)."""
    cibles = []
    for e in table().values():
        if e.get("utilisateur") == utilisateur and e.get("statut") in ("lie", "ouvert"):
            cibles.append((e.get("reseau"), e.get("id_externe")))
    return cibles


def est_approbateur(reseau: str, id_externe: str) -> bool:
    """Droit d'APPROUVER une action sensible (S245). Triple condition, vide par défaut :
    entrée connue, statut « lie » (JAMAIS « ouvert » : CONNEXION_OUVERT=1 ne donne aucun
    droit d'approbation) et drapeau `approbateur` explicitement True."""
    e = table().get(_cle(reseau, str(id_externe)))
    return bool(e) and e.get("statut") == "lie" and e.get("approbateur") is True


def approbateurs(reseau: str) -> list[str]:
    """`id_externe` des approbateurs d'un réseau (mêmes conditions que `est_approbateur`)."""
    return [e["id_externe"] for e in table().values()
            if e.get("reseau") == reseau and e.get("statut") == "lie"
            and e.get("approbateur") is True and not str(e["id_externe"]).startswith("-")]


def utilisateur_de(reseau: str, id_externe: str) -> str | None:
    """Utilisateur Workplace d'un interlocuteur **lié** (S245b), sinon None."""
    e = table().get(_cle(reseau, str(id_externe)))
    if e and e.get("statut") == "lie" and e.get("utilisateur"):
        return e["utilisateur"]
    return None


def approbateurs_de(reseau: str, utilisateur: str) -> list[str]:
    """Approbateurs d'un réseau dont le compte lié est `utilisateur` (S245b : une demande
    n'est envoyée qu'à l'approbateur de son demandeur)."""
    return [i for i in approbateurs(reseau) if utilisateur_de(reseau, i) == utilisateur]


def definir_approbateur(reseau: str, id_externe: str, valeur: bool) -> dict | None:
    """Pose/retire le drapeau. Ne marche que sur une entrée existante au statut « lie »
    (None sinon) : on n'accorde jamais ce droit à un inconnu ou à quelqu'un en attente."""
    if str(id_externe).startswith("-"):           # groupe Telegram : un résumé y serait publié
        return None
    t = table()
    e = t.get(_cle(reseau, str(id_externe)))
    if not e or e.get("statut") != "lie":
        return None
    e["approbateur"] = bool(valeur)
    _sauver(t)
    return e
