"""Fournisseurs de téléphonie — interface PROVIDER-AGNOSTIQUE.

La brique expose UN canal téléphonique (acheter un numéro, envoyer un SMS, passer un appel) ;
Twilio en est la 1re implémentation réelle. Deux fournisseurs, même logique que `paiements` :

  • `Mock`   : par défaut, **honnête**. Aucune clé requise, RIEN ne part sur le réseau, tout est
               étiqueté « mock » (jamais un faux envoi présenté comme réel). Sert démo/tests/dev.
  • `Twilio` : réel dès que `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` sont fournis. Appels REST
               directs en `httpx` (pas de SDK lourd) : recherche+achat de numéro, Messages,
               Calls. La validation des webhooks entrants utilise la signature `X-Twilio-Signature`.

Le choix se fait comme ailleurs : credentials présents ⇒ Twilio, sinon ⇒ mock. On ne met
JAMAIS le token en clair dans une réponse, un log ou une erreur.

S'inspire du pattern de référence d'AgentPhone-MCP (acheter un numéro / SMS / appel via langage
naturel) mais en **brique Workplace native** : capacités au manifest → outils du Cœur, plutôt
qu'un serveur MCP externe (le Cœur est MCP *serveur*, pas client).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import random
import string
import time
from urllib.parse import urlencode

import httpx

import domaine

TWILIO_BASE = "https://api.twilio.com/2010-04-01"


def _ref(prefixe: str) -> str:
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=14))
    return f"{prefixe}_{int(time.time() * 1000)}_{rand}"


def resoudre_credentials() -> tuple[str, str] | None:
    """(account_sid, auth_token) Twilio depuis l'env, ou None → mode mock honnête."""
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    return (sid, token) if (sid and token) else None


def _mask(v: str) -> str:
    return v[:4] + "…" + v[-4:] if len(v) > 8 else "***"


def etat_config() -> dict:
    """État HONNÊTE de la configuration (jamais le token en clair). Sert /config et le bandeau."""
    creds = resoudre_credentials()
    if not creds:
        return {"configure": False, "fournisseur": "mock",
                "message": "Aucune clé Twilio : canal SIMULÉ (mock), aucun SMS/appel réel."}
    sid, _ = creds
    return {"configure": True, "fournisseur": "twilio", "indice_compte": _mask(sid),
            "numero_par_defaut": os.getenv("TWILIO_FROM") or None,
            "message": "Twilio configuré (envois réels facturés)."}


# ── Fournisseur MOCK (honnête) ───────────────────────────────────
class Mock:
    """Simulation locale. Achat de numéro → numéro factice plausible (E.164). SMS « envoyé »
    immédiatement, appel « terminé » immédiatement — tout étiqueté mock. RIEN ne part."""

    nom = "mock"

    def acheter_numero(self, pays: str) -> dict:
        indicatif = {"FR": "+336", "US": "+1201", "GB": "+447", "BE": "+324"}.get(
            (pays or "FR").upper(), "+336")
        numero = indicatif + "".join(random.choices(string.digits, k=12 - len(indicatif) + 1))[:9]
        return {"ref_externe": _ref("PN_mock"), "numero": numero, "statut": "actif",
                "mode": "mock"}

    def envoyer_sms(self, de: str, vers: str, corps: str) -> dict:
        return {"ref_externe": _ref("SM_mock"), "statut": domaine.SMS_ENVOYE, "mode": "mock",
                "message": "SMS SIMULÉ (mock) : rien n'a été envoyé sur le réseau."}

    def passer_appel(self, de: str, vers: str, message: str) -> dict:
        return {"ref_externe": _ref("CA_mock"), "statut": domaine.APPEL_TERMINE, "mode": "mock",
                "message": "Appel SIMULÉ (mock) : aucun appel réel passé."}


# ── Correspondance des statuts Twilio → domaine ──────────────────
def _statut_sms_twilio(s: str) -> str:
    s = (s or "").lower()
    if s in ("queued", "accepted", "sending", "scheduled"):
        return domaine.SMS_FILE
    if s in ("sent", "delivered"):
        return domaine.SMS_ENVOYE
    return domaine.SMS_ECHOUE                      # failed / undelivered / inconnu


def _statut_appel_twilio(s: str) -> str:
    s = (s or "").lower()
    if s in ("queued", "initiated"):
        return domaine.APPEL_INITIE
    if s in ("ringing", "in-progress"):
        return domaine.APPEL_EN_COURS
    if s == "completed":
        return domaine.APPEL_TERMINE
    return domaine.APPEL_ECHOUE                    # busy / no-answer / failed / canceled


# ── Fournisseur TWILIO (réel, REST httpx) ────────────────────────
class Twilio:
    """Canal réel via l'API REST Twilio (auth Basic SID/token). Aucun SDK : `httpx` suffit."""

    nom = "twilio"
    timeout = 30

    def __init__(self, sid: str, token: str):
        self._sid = sid
        self._auth = (sid, token)

    def _post(self, ressource: str, data: dict) -> dict:
        url = f"{TWILIO_BASE}/Accounts/{self._sid}/{ressource}"
        with httpx.Client(timeout=self.timeout) as c:
            r = c.post(url, data=data, auth=self._auth)
            r.raise_for_status()
            return r.json()

    def _get(self, ressource: str, params: dict) -> dict:
        url = f"{TWILIO_BASE}/Accounts/{self._sid}/{ressource}"
        with httpx.Client(timeout=self.timeout) as c:
            r = c.get(url, params=params, auth=self._auth)
            r.raise_for_status()
            return r.json()

    def acheter_numero(self, pays: str) -> dict:
        # 1) chercher un numéro local disponible (SMS + voix), 2) l'acheter.
        pays = (pays or "FR").upper()
        dispo = self._get(f"AvailablePhoneNumbers/{pays}/Local.json",
                          {"SmsEnabled": "true", "VoiceEnabled": "true", "PageSize": 1})
        liste = dispo.get("available_phone_numbers") or []
        if not liste:
            raise RuntimeError(f"Aucun numéro local disponible en {pays} chez Twilio.")
        numero = liste[0]["phone_number"]
        achat = self._post("IncomingPhoneNumbers.json", {"PhoneNumber": numero})
        return {"ref_externe": achat.get("sid"), "numero": achat.get("phone_number", numero),
                "statut": "actif", "mode": "twilio"}

    def envoyer_sms(self, de: str, vers: str, corps: str) -> dict:
        rep = self._post("Messages.json", {"From": de, "To": vers, "Body": corps})
        return {"ref_externe": rep.get("sid"),
                "statut": _statut_sms_twilio(rep.get("status")), "mode": "twilio"}

    def passer_appel(self, de: str, vers: str, message: str) -> dict:
        # TwiML inline : l'appel énonce `message` (voix). Sinon, brancher une URL TwiML/webhook.
        twiml = f"<Response><Say language=\"fr-FR\">{_echappe_xml(message)}</Say></Response>"
        rep = self._post("Calls.json", {"From": de, "To": vers, "Twiml": twiml})
        return {"ref_externe": rep.get("sid"),
                "statut": _statut_appel_twilio(rep.get("status")), "mode": "twilio"}


def _echappe_xml(texte: str) -> str:
    return (texte or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fournisseur():
    """Le fournisseur ACTIF : Twilio si des credentials sont configurés, sinon le mock honnête."""
    creds = resoudre_credentials()
    return Twilio(*creds) if creds else Mock()


def verifier_webhook(url: str, params: dict, signature: str) -> bool:
    """Valide la signature `X-Twilio-Signature` d'un webhook entrant.

    Twilio signe `url + concat(clé+valeur des params triés par clé)` en HMAC-SHA1 (clé = auth
    token), encodé base64. On ne traite JAMAIS un webhook non signé/invalide (pas de trou).
    Lève `ValueError('non_configure')` si aucun token (on ne peut pas vérifier → on refuse)."""
    creds = resoudre_credentials()
    if not creds:
        raise ValueError("non_configure")
    _, token = creds
    base = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    attendue = base64.b64encode(
        hmac.new(token.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(attendue, signature or "")
