"""Brique « telephonie » — le canal TÉLÉPHONIQUE de Workplace (SMS + voix), multi-tenant.

Produit autonome (port 6050). Donne à l'assistant un vrai téléphone : acheter un numéro,
envoyer/recevoir des SMS, passer des appels vocaux. Réutilisable par plusieurs solutions, chacune
isolée par sa **clé API** (le `solution`). Fournisseur **mock honnête** par défaut (rien ne part
sur le réseau), **Twilio réel** dès qu'une clé est fournie (cf. `fournisseurs.py`).

Les capacités du manifest sont auto-découvertes par le Cœur (S63/S64) et deviennent des outils
du LLM — l'assistant peut donc « envoyer un SMS à … » en parlant, avec gate de confirmation
(`confirme=true`) imposé par le Cœur sur les actions. On ne contourne aucun garde-fou.
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import domaine
import fournisseurs
import stockage

app = FastAPI(title="Téléphonie — SMS & voix multi-tenant", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


# ── Multi-tenant : la clé API identifie la SOLUTION (le tenant) ───
def solution_actuelle(x_api_key: Optional[str] = Header(None),
                      authorization: Optional[str] = Header(None)) -> str:
    """Résout la solution depuis la clé API (X-API-Key ou Bearer). La clé reste secrète : le
    tenant est son **empreinte** sha256 tronquée. Fail-closed si `API_KEYS` est défini."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if API_KEYS:
        if presentee not in API_KEYS:
            raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    elif not presentee:
        return "public"
    return hashlib.sha256((presentee or "public").encode()).hexdigest()[:16]


# ── Modèles ──────────────────────────────────────────────────────
class NumeroEntree(BaseModel):
    pays: str = "FR"


class SmsEntree(BaseModel):
    de: str
    vers: str
    corps: str


class AppelEntree(BaseModel):
    de: str
    vers: str
    message: str = ""


# ── Santé & config ───────────────────────────────────────────────
@app.get("/sante")
def sante():
    return {"ok": True, "brique": "telephonie", "version": "0.1.0"}


@app.get("/config")
def config(_sol: str = Depends(solution_actuelle)):
    """État honnête du canal (mock / Twilio), jamais le token en clair."""
    return fournisseurs.etat_config()


# ── Numéros possédés ─────────────────────────────────────────────
@app.get("/numeros")
def lister_numeros(sol: str = Depends(solution_actuelle)):
    return {"numeros": stockage.lister_numeros(sol)}


@app.post("/numeros", status_code=201)
def acheter_numero(corps: NumeroEntree, sol: str = Depends(solution_actuelle)):
    """Achète un numéro de téléphone (capable SMS + voix) chez le fournisseur, puis le persiste
    pour cette solution. En mock : numéro factice plausible (aucun achat). En Twilio : numéro
    local réel (facturé)."""
    try:
        res = fournisseurs.fournisseur().acheter_numero(corps.pays)
    except Exception as e:  # noqa: BLE001 — erreur fournisseur → 502 lisible
        raise HTTPException(502, f"Achat de numéro impossible : {e}")
    num = stockage.creer_numero(sol, res["ref_externe"], res["numero"],
                                corps.pays, res.get("statut", "actif"))
    return num | {"mode": res.get("mode")}


# ── SMS ──────────────────────────────────────────────────────────
@app.get("/sms")
def lister_sms(sol: str = Depends(solution_actuelle)):
    return {"messages": stockage.lister_messages(sol)}


@app.post("/sms", status_code=201)
def envoyer_sms(corps: SmsEntree, sol: str = Depends(solution_actuelle)):
    """Envoie un SMS depuis un numéro POSSÉDÉ par la solution. ACTION (un SMS part si Twilio ;
    mock sinon) : le gate `confirme=true` est imposé par le Cœur, pas ici."""
    try:
        de = domaine.normaliser_numero(corps.de)
        vers = domaine.normaliser_numero(corps.vers)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not domaine.sms_valide(corps.corps):
        raise HTTPException(400, f"Message vide ou trop long (max {domaine.SMS_MAX} caractères).")
    if not stockage.numero_possede(sol, de):
        raise HTTPException(409, f"Le numéro émetteur {de} n'est pas possédé par cette solution "
                                 "(acheter un numéro d'abord).")
    try:
        res = fournisseurs.fournisseur().envoyer_sms(de, vers, corps.corps)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Envoi du SMS impossible : {e}")
    msg = stockage.creer_message(sol, res["ref_externe"], domaine.SORTANT, de, vers,
                                 corps.corps, domaine.segments_sms(corps.corps), res["statut"])
    extras = {k: res[k] for k in ("mode", "message") if k in res}
    return msg | extras


# ── Appels ───────────────────────────────────────────────────────
@app.get("/appels")
def lister_appels(sol: str = Depends(solution_actuelle)):
    return {"appels": stockage.lister_appels(sol)}


@app.post("/appels", status_code=201)
def passer_appel(corps: AppelEntree, sol: str = Depends(solution_actuelle)):
    """Passe un appel vocal depuis un numéro POSSÉDÉ ; `message` est énoncé (TwiML <Say>).
    ACTION (un appel part si Twilio ; mock sinon) : gate `confirme=true` imposé par le Cœur."""
    try:
        de = domaine.normaliser_numero(corps.de)
        vers = domaine.normaliser_numero(corps.vers)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not stockage.numero_possede(sol, de):
        raise HTTPException(409, f"Le numéro émetteur {de} n'est pas possédé par cette solution "
                                 "(acheter un numéro d'abord).")
    try:
        res = fournisseurs.fournisseur().passer_appel(de, vers, corps.message)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Appel impossible : {e}")
    appel = stockage.creer_appel(sol, res["ref_externe"], de, vers, corps.message, res["statut"])
    extras = {k: res[k] for k in ("mode", "message") if k in res}
    return appel | extras


# ── Webhook entrant Twilio (SMS reçu) — signature vérifiée ───────
@app.post("/webhooks/twilio")
async def webhook_twilio(request: Request,
                         x_twilio_signature: str = Header(None),
                         sol: str = Depends(solution_actuelle)):
    """Reçoit un SMS entrant Twilio (form-encodé) sur un de nos numéros. Signature vérifiée :
    on ne traite jamais un webhook non signé. Enregistre le message comme RECU."""
    form = dict((await request.form()))
    url = str(request.url)
    try:
        ok = fournisseurs.verifier_webhook(url, form, x_twilio_signature or "")
    except ValueError:
        raise HTTPException(503, "Webhook non configuré (TWILIO_AUTH_TOKEN absent).")
    if not ok:
        raise HTTPException(400, "Signature de webhook invalide.")
    de, vers, corps = form.get("From", ""), form.get("To", ""), form.get("Body", "")
    stockage.creer_message(sol, form.get("MessageSid"), domaine.ENTRANT, de, vers, corps,
                           domaine.segments_sms(corps), domaine.SMS_RECU)
    return {"recu": True}
