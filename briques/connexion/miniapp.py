"""Mini App Telegram — authentification souveraine par `initData` (S77).

Une Mini App Telegram est une page web chargée DANS Telegram. Telegram lui fournit un
`initData` SIGNÉ (HMAC-SHA256 dérivé du token du bot) : on peut donc prouver, sans tiers,
QUI est l'interlocuteur. La brique connexion possède déjà le token (adaptateur Telegram)
ET la table de consentement (`correspondance`) — c'est donc ici, et pas dans le Cœur, que
vit l'auth. Le Cœur reste INTERNE : la Mini App parle à cette brique (front public gardé),
la brique relaie au Cœur sur le réseau privé.

Conception MULTI-UTILISATEUR dès le départ (cf. roadmap : un seul user aujourd'hui, plusieurs
demain) : `autoriser()` résout l'utilisateur Workplace via `correspondance` (le même modèle
de consentement que le pont). Une allowlist d'IDs Telegram (`TELEGRAM_MINIAPP_USERS`) sert de
garde-fou de transition : si elle est définie, elle est FAIL-CLOSED (seuls ces IDs entrent) ;
vide → on s'en remet au consentement de `correspondance`. Aucun secret en dur, repli honnête.

Référence : https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

import correspondance

RESEAU = "telegram"


def _allowlist() -> set[str]:
    return {x.strip() for x in os.getenv("TELEGRAM_MINIAPP_USERS", "").split(",") if x.strip()}


def valider_init_data(init_data: str, token: str, *, age_max_s: int = 86400) -> dict | None:
    """Valide la signature d'un `initData` Telegram. Renvoie les champs (dont `user` parsé en
    dict) si AUTHENTIQUE et frais, sinon `None`.

    Algorithme officiel : secret = HMAC_SHA256(clé="WebAppData", message=token) ; le hash
    attendu = HMAC_SHA256(clé=secret, message=data_check_string), où data_check_string est la
    liste des champs (hors `hash`) « clé=valeur » triés et joints par '\\n'. Comparaison en
    temps constant. Refus si `auth_date` est trop vieux (anti-rejeu)."""
    if not init_data or not token:
        return None
    paires = dict(parse_qsl(init_data, keep_blank_values=True))
    recu = paires.pop("hash", None)
    if not recu:
        return None
    # `signature` (validation par tiers) ne fait pas partie du data-check-string du bot.
    paires.pop("signature", None)
    chaine = "\n".join(f"{k}={paires[k]}" for k in sorted(paires))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calcule = hmac.new(secret, chaine.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calcule, recu):
        return None
    # Fraîcheur : un initData rejoué indéfiniment serait un risque.
    try:
        if age_max_s and (time.time() - int(paires.get("auth_date", "0"))) > age_max_s:
            return None
    except ValueError:
        return None
    donnees = dict(paires)
    if "user" in donnees:
        try:
            donnees["user"] = json.loads(donnees["user"])
        except (json.JSONDecodeError, TypeError):
            return None
    return donnees


def autoriser(init_data: str, *, token: str | None = None) -> dict:
    """Valide l'`initData` puis résout/contrôle l'utilisateur. Verdict HONNÊTE et explicite.

    Renvoie {ok, raison?, utilisateur?, nom?, user?, statut?, code?}. `utilisateur` = compte
    Workplace résolu via `correspondance` ; `code` = code de liaison à communiquer si le
    consentement manque (comme l'accueil du pont)."""
    token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"ok": False, "raison": "bot_non_configure"}
    donnees = valider_init_data(init_data, token)
    if donnees is None:
        return {"ok": False, "raison": "init_data_invalide"}
    user = donnees.get("user") or {}
    uid = str(user.get("id") or "").strip()
    if not uid:
        return {"ok": False, "raison": "utilisateur_absent"}
    nom = user.get("first_name") or user.get("username")
    allow = _allowlist()
    if allow and uid not in allow:
        return {"ok": False, "raison": "non_autorise_allowlist", "user": user, "nom": nom}
    corr = correspondance.resoudre(RESEAU, uid, nom)
    if not corr["autorise"]:
        return {"ok": False, "raison": "consentement_requis", "statut": corr.get("statut"),
                "code": corr.get("code"), "user": user, "nom": nom}
    return {"ok": True, "utilisateur": corr.get("utilisateur"), "nom": nom,
            "statut": corr.get("statut"), "user": user}
