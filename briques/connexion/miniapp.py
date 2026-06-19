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
import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

import correspondance

RESEAU = "telegram"
COOKIE_SESSION = "mp_session"


# ── Session signée (S79) : initData validé UNE fois → cookie court, vérifié ensuite ──
# La Mini App ouvre l'app Workplace COMPLÈTE (le dashboard du Cœur) via un reverse-proxy
# gardé. On ne revalide pas l'initData à chaque image/fetch : on valide une fois, on pose
# un cookie de session SIGNÉ (HMAC), et le proxy ne laisse passer que les requêtes qui le
# présentent. Secret dédié (MINIAPP_SESSION_SECRET) ou dérivé du token bot (stable).
def _secret_session() -> bytes:
    s = os.getenv("MINIAPP_SESSION_SECRET")
    if s:
        return s.encode()
    return hashlib.sha256(b"miniapp-session:" + os.getenv("TELEGRAM_BOT_TOKEN", "").encode()).digest()


def creer_session(user: dict, utilisateur: str | None, *, duree_s: int = 86400) -> str:
    """Jeton de session signé : base64(charge) + '.' + HMAC. Charge = qui + expiration."""
    charge = {"uid": str((user or {}).get("id") or ""), "utilisateur": utilisateur,
              "exp": int(time.time()) + max(60, duree_s)}
    brut = base64.urlsafe_b64encode(json.dumps(charge).encode()).decode().rstrip("=")
    sig = hmac.new(_secret_session(), brut.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{brut}.{sig}"


def verifier_session(jeton: str | None) -> dict | None:
    """Renvoie la charge si le jeton est authentique ET non expiré, sinon None."""
    if not jeton or "." not in jeton:
        return None
    brut, sig = jeton.rsplit(".", 1)
    attendu = hmac.new(_secret_session(), brut.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, attendu):
        return None
    try:
        pad = brut + "=" * (-len(brut) % 4)
        charge = json.loads(base64.urlsafe_b64decode(pad.encode()))
    except Exception:  # noqa: BLE001
        return None
    if float(charge.get("exp", 0)) < time.time():
        return None
    return charge


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
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()

    def _hash(champs: dict) -> str:
        chaine = "\n".join(f"{k}={champs[k]}" for k in sorted(champs))
        return hmac.new(secret, chaine.encode(), hashlib.sha256).hexdigest()

    # Telegram calcule le hash sur TOUS les champs sauf `hash`. Les versions récentes
    # ajoutent `signature` (validation tierce Ed25519) : il est INCLUS dans le
    # data-check-string du bot. On tolère les deux variantes (avec / sans `signature`)
    # pour rester robuste quelle que soit la version du client.
    candidats = [paires]
    if "signature" in paires:
        candidats.append({k: v for k, v in paires.items() if k != "signature"})
    if not any(hmac.compare_digest(_hash(c), recu) for c in candidats):
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
