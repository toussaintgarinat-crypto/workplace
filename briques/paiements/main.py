"""Brique « paiements » — le RAIL d'argent, multi-tenant et provider-agnostique.

Produit autonome (port 6020). Possède : comptes connectés des vendeurs (onboarding hébergé),
encaissement avec **commission plateforme**, remboursement, webhooks signés. Réutilisable par
plusieurs solutions (restaurant, Forge, marketplaces) — chacune isolée par sa **clé API**
(le `solution`). Le SPLIT/addition partagée reste dans la brique appelante (ex. restaurant) ;
ici on tient le rail.

Fournisseur : **mock honnête** par défaut (aucune clé, aucun argent ne bouge, tout étiqueté
« mock »), **Stripe réel** dès qu'une clé est fournie (test puis live = étape externe). Voir
`fournisseurs.py`. On ne renvoie/loggue JAMAIS la clé (règles de sécurité Stripe)."""
from __future__ import annotations

import hashlib
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import domaine
import fournisseurs
import stockage

app = FastAPI(title="Paiements — rail multi-tenant (Connect)", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}

# Le schéma est créé à l'import de `stockage` (idempotent) — rien à faire au démarrage.


# ── Multi-tenant : la clé API identifie la SOLUTION (le tenant) ───
def solution_actuelle(x_api_key: Optional[str] = Header(None),
                      authorization: Optional[str] = Header(None)) -> str:
    """Résout la solution depuis la clé API (X-API-Key ou Bearer). La clé reste secrète : le
    tenant est son **empreinte** (sha256 tronquée), stable et non réversible. Fail-closed : si
    `API_KEYS` est défini, seule une clé connue passe ; sinon (dev) un espace « public » unique."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if API_KEYS:
        if presentee not in API_KEYS:
            raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    elif not presentee:
        return "public"
    return hashlib.sha256((presentee or "public").encode()).hexdigest()[:16]


# ── Modèles ──────────────────────────────────────────────────────
class CompteEntree(BaseModel):
    nom: str = ""
    email: str = ""
    pays: str = "FR"


class PaiementEntree(BaseModel):
    compte_connecte_id: str
    montant_cents: int
    devise: str = "EUR"
    commission_bps: int = 0            # commission en points de base (250 = 2,5 %)
    commission_cents: Optional[int] = None  # …ou un montant fixe (prioritaire si fourni)
    description: str = ""


# ── Santé & config ───────────────────────────────────────────────
@app.get("/sante")
def sante():
    return {"ok": True, "brique": "paiements", "version": "0.1.0"}


@app.get("/config")
def config(_sol: str = Depends(solution_actuelle)):
    """État honnête du rail (mock / stripe test / live), jamais la clé en clair."""
    return fournisseurs.etat_config()


# ── Comptes connectés (vendeurs) ─────────────────────────────────
@app.post("/comptes-connectes", status_code=201)
def creer_compte(corps: CompteEntree, sol: str = Depends(solution_actuelle)):
    """Crée un compte connecté (un vendeur, ex. un restaurateur) chez le fournisseur, puis le
    persiste pour cette solution. Statut initial : onboarding à terminer."""
    res = fournisseurs.fournisseur().creer_compte(
        {"nom": corps.nom, "email": corps.email, "pays": corps.pays, "solution": sol})
    compte = stockage.creer_compte(sol, res["ref_externe"], res["statut"],
                                   nom=corps.nom, email=corps.email, pays=corps.pays)
    return compte


@app.get("/comptes-connectes")
def lister_comptes(sol: str = Depends(solution_actuelle)):
    return {"comptes": stockage.lister_comptes(sol)}


@app.get("/comptes-connectes/{compte_id}")
def lire_compte(compte_id: str, sol: str = Depends(solution_actuelle)):
    """Statut du compte, RAFRAÎCHI depuis le fournisseur (capacités d'encaissement à jour),
    puis persisté. 404 si le compte n'est pas à cette solution (cloisonnement)."""
    compte = stockage.lire_compte(sol, compte_id)
    if not compte:
        raise HTTPException(404, "Compte connecté introuvable.")
    etat = fournisseurs.fournisseur().statut_compte(compte)
    if etat["statut"] != compte["statut"]:
        stockage.maj_statut_compte(compte_id, etat["statut"])
        compte["statut"] = etat["statut"]
    return compte | {"peut_encaisser": etat["peut_encaisser"]}


@app.post("/comptes-connectes/{compte_id}/onboarding")
def onboarding(compte_id: str, sol: str = Depends(solution_actuelle)):
    """Lien d'onboarding HÉBERGÉ (Stripe Account Link en réel ; page mock en démo). On ne
    collecte aucune donnée KYC nous-mêmes."""
    compte = stockage.lire_compte(sol, compte_id)
    if not compte:
        raise HTTPException(404, "Compte connecté introuvable.")
    return fournisseurs.fournisseur().lien_onboarding(compte)


@app.get("/demo/onboarding/{compte_id}", response_class=HTMLResponse)
def demo_onboarding(compte_id: str):
    """Page d'onboarding MOCK : active le compte au clic (aucun KYC réel — c'est dit). Atteinte
    via le lien mock (la connaissance de l'id = la capability). En mode Stripe réel, l'onboarding
    se fait chez Stripe, pas ici."""
    stockage.maj_statut_compte(compte_id, domaine.COMPTE_ACTIF)
    return HTMLResponse(
        "<html><body style='font-family:system-ui;max-width:520px;margin:60px auto;text-align:center'>"
        "<h2>✅ Compte activé (mock)</h2>"
        "<p>Ceci est un onboarding <b>simulé</b> : aucune vérification d'identité réelle n'a eu lieu. "
        "En production, cette étape est hébergée par Stripe (Account Link).</p>"
        f"<p style='color:#64748b'>Compte : <code>{compte_id}</code></p></body></html>")


# ── Paiements ────────────────────────────────────────────────────
@app.post("/paiements", status_code=201)
def creer_paiement(corps: PaiementEntree, sol: str = Depends(solution_actuelle)):
    """Encaisse un montant pour le compte d'un vendeur, en prélevant la **commission plateforme**
    (recalculée serveur, bornée). Refuse si le vendeur ne peut pas encore encaisser (onboarding
    non terminé). En mock : paiement simulé « payé ». En Stripe : destination charge +
    application_fee (le net part au vendeur)."""
    compte = stockage.lire_compte(sol, corps.compte_connecte_id)
    if not compte:
        raise HTTPException(404, "Compte connecté introuvable.")
    if not domaine.compte_peut_encaisser(compte["statut"]):
        raise HTTPException(409, "Le compte vendeur ne peut pas encore encaisser "
                                 "(onboarding non terminé).")
    if int(corps.montant_cents) <= 0:
        raise HTTPException(400, "Montant invalide.")
    rep = domaine.calculer_commission(corps.montant_cents, commission_bps=corps.commission_bps,
                                      commission_cents=corps.commission_cents)
    res = fournisseurs.fournisseur().creer_paiement(
        compte, rep["brut"], corps.devise, rep["commission"], corps.description)
    paiement = stockage.creer_paiement(
        sol, compte["id"], res["ref_externe"], rep["brut"], rep["commission"], rep["net"],
        corps.devise, res["statut"], corps.description)
    # Extras non persistés du fournisseur (client_secret Stripe, libellé mock).
    extras = {k: res[k] for k in ("client_secret", "mode", "message") if k in res}
    return paiement | extras


@app.get("/paiements")
def lister_paiements(sol: str = Depends(solution_actuelle)):
    return {"paiements": stockage.lister_paiements(sol)}


@app.get("/paiements/{paiement_id}")
def lire_paiement(paiement_id: str, sol: str = Depends(solution_actuelle)):
    p = stockage.lire_paiement(sol, paiement_id)
    if not p:
        raise HTTPException(404, "Paiement introuvable.")
    return p


@app.post("/paiements/{paiement_id}/rembourser")
def rembourser(paiement_id: str, sol: str = Depends(solution_actuelle)):
    """Rembourse un paiement encaissé (transition gardée : seul un paiement PAYÉ peut l'être)."""
    p = stockage.lire_paiement(sol, paiement_id)
    if not p:
        raise HTTPException(404, "Paiement introuvable.")
    if not domaine.transition_paiement_permise(p["statut"], domaine.PAIEMENT_REMBOURSE):
        raise HTTPException(409, f"Remboursement impossible depuis l'état « {p['statut']} ».")
    fournisseurs.fournisseur().rembourser(p)
    stockage.maj_statut_paiement(paiement_id, domaine.PAIEMENT_REMBOURSE)
    return stockage.lire_paiement(sol, paiement_id)


# ── Webhooks Stripe (signature vérifiée) ─────────────────────────
@app.post("/webhooks/stripe")
async def webhook_stripe(request: Request, stripe_signature: str = Header(None)):
    """Reçoit les événements Stripe (corps BRUT + signature vérifiée). Met à jour le statut des
    comptes (capacités) et des paiements (succès/remboursement). Jamais traité sans signature."""
    payload = await request.body()
    try:
        evt = fournisseurs.verifier_webhook(payload, stripe_signature or "")
    except ValueError as e:
        if str(e) == "non_configure":
            raise HTTPException(503, "Webhook non configuré (STRIPE_WEBHOOK_SECRET absent).")
        raise HTTPException(400, "Signature ou contenu de webhook invalide.")
    _traiter_evenement(evt)
    return {"recu": True}


def _traiter_evenement(evt: dict) -> None:
    """Applique l'effet d'un événement vérifié (compte mis à jour / paiement payé / remboursé)."""
    type_ = evt.get("type", "")
    objet = (evt.get("data") or {}).get("object") or {}
    if type_ == "account.updated":
        compte = stockage.compte_par_ref(objet.get("id", ""))
        if compte:
            statut = domaine.COMPTE_ACTIF if objet.get("charges_enabled") else domaine.COMPTE_INCOMPLET
            stockage.maj_statut_compte(compte["id"], statut)
    elif type_ in ("payment_intent.succeeded", "charge.refunded"):
        ref = objet.get("payment_intent") or objet.get("id", "")
        p = stockage.paiement_par_ref(ref)
        if p:
            statut = (domaine.PAIEMENT_REMBOURSE if type_ == "charge.refunded"
                      else domaine.PAIEMENT_PAYE)
            stockage.maj_statut_paiement(p["id"], statut)
