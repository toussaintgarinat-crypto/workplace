"""Brique « mail » — l'assistant s'occupe de la BOÎTE DE RÉCEPTION (entrant), v0.1.0 lecture seule.

Produit autonome (port 6030), multi-tenant par **clé API** (chaque tenant = une boîte isolée),
provider-agnostique. Par défaut : boîte **mock honnête** (simulée, 0 réseau). Dès qu'un compte
IMAP est connecté (mot de passe d'application, chiffré au repos) : boîte **réelle, lecture seule**.

Ce que sait faire la v0.1.0 : **lister, lire, résumer (IA + repli honnête), trier par importance**
et **préparer un brouillon de réponse — JAMAIS envoyé**. L'envoi (SMTP) est la v0.2.0.

Le Cœur découvre ces capacités via le `manifest.json` et les appelle en s'authentifiant avec
`X-API-Key = MAIL_KEY`. Le mot de passe IMAP ne transite jamais en clair dans une réponse/log.
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import domaine
import fournisseurs
import resume
import stockage

app = FastAPI(title="Mail — boîte de réception multi-tenant (lecture seule)", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


# ── Multi-tenant : la clé API identifie la BOÎTE (le tenant) ─────────────────
def tenant_actuel(x_api_key: Optional[str] = Header(None),
                  authorization: Optional[str] = Header(None)) -> str:
    """Résout le tenant depuis la clé API (X-API-Key ou Bearer). La clé reste secrète : le tenant
    est son **empreinte** (sha256 tronquée). Fail-closed si `API_KEYS` défini ; sinon (dev) « public »."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if API_KEYS:
        if presentee not in API_KEYS:
            raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    elif not presentee:
        return "public"
    return hashlib.sha256((presentee or "public").encode()).hexdigest()[:16]


# ── Modèles ──────────────────────────────────────────────────────────────────
class CompteEntree(BaseModel):
    host: str
    utilisateur: str
    mot_de_passe: str
    port: int = 993
    dossier: str = "INBOX"


class ResumerEntree(BaseModel):
    lang: str = "fr"


class BrouillonEntree(BaseModel):
    message_id: str
    instruction: str = ""
    lang: str = "fr"


# ── Synchronisation (cache ← fournisseur) ────────────────────────────────────
def _synchroniser(tenant: str) -> int:
    """Récupère la boîte du fournisseur (mock ou IMAP réel), enrichit (catégorie+score) et
    remplace le cache. Renvoie le nombre de messages. Lecture seule côté serveur de mail."""
    compte = stockage.lire_compte(tenant, avec_secret=True)
    bruts = fournisseurs.fournisseur_pour(compte).recuperer()
    connus = stockage.expediteurs_connus(tenant)
    enrichis = domaine.trier(bruts, connus)
    return stockage.remplacer_messages(tenant, enrichis)


def _assurer_cache(tenant: str) -> None:
    """Garantit un cache non vide pour la première lecture (sync paresseuse)."""
    if not stockage.lister_messages(tenant, limite=1):
        _synchroniser(tenant)


# ── Santé & config ───────────────────────────────────────────────────────────
@app.get("/sante")
def sante():
    return {"ok": True, "brique": "mail", "version": "0.1.0"}


@app.get("/config")
def config(tenant: str = Depends(tenant_actuel)):
    """État honnête de la boîte (mock vs IMAP réel), jamais d'identifiant en clair."""
    return fournisseurs.etat_config(stockage.lire_compte(tenant))


# ── Connexion d'un compte IMAP (action : manipule un secret) ─────────────────
@app.post("/comptes", status_code=201)
def connecter_compte(corps: CompteEntree, tenant: str = Depends(tenant_actuel)):
    """Connecte une boîte IMAP réelle (mot de passe d'app, chiffré au repos). On VÉRIFIE la
    connexion en synchronisant tout de suite : si les identifiants sont faux, on échoue proprement
    et on ne garde rien."""
    if not os.getenv("MAIL_VAULT_SECRET"):
        raise HTTPException(503, "MAIL_VAULT_SECRET non configuré : impossible de stocker le "
                                 "mot de passe en sécurité.")
    stockage.enregistrer_compte(tenant, corps.host, corps.utilisateur, corps.mot_de_passe,
                                port=corps.port, dossier=corps.dossier)
    try:
        n = _synchroniser(tenant)
    except Exception as e:  # noqa: BLE001 — identifiants/serveur KO : on n'enferme pas l'erreur brute
        stockage.supprimer_compte(tenant)
        raise HTTPException(400, "Connexion IMAP refusée (hôte ou identifiants incorrects). "
                                 "Astuce : utilise un MOT DE PASSE D'APPLICATION, pas ton mot de "
                                 "passe principal.") from e
    return {"ok": True, "fournisseur": "imap", "messages_synchronises": n,
            "message": f"Boîte connectée ({corps.host}). {n} message(s) récupéré(s), lecture seule."}


@app.delete("/comptes")
def deconnecter_compte(tenant: str = Depends(tenant_actuel)):
    """Déconnecte la boîte IMAP (revient au mock) et vide le cache du tenant."""
    stockage.supprimer_compte(tenant)
    stockage.remplacer_messages(tenant, [])
    return {"ok": True, "message": "Boîte déconnectée ; retour à la boîte simulée."}


# ── Synchronisation (cible de la tâche d'horloge `sync-mail`) ────────────────
@app.post("/mail/sync")
def sync(tenant: str = Depends(tenant_actuel)):
    """Rafraîchit le cache depuis le fournisseur. Tolère l'échec (boîte non connectée → mock)."""
    n = _synchroniser(tenant)
    return {"ok": True, "messages": n}


# ── Lecture de la boîte ──────────────────────────────────────────────────────
@app.get("/mail")
def lister(non_lus: bool = False, categorie: str = "", limite: int = 50,
           tenant: str = Depends(tenant_actuel)):
    """Liste la boîte, triée par importance (score) décroissante. Sync paresseuse au 1er appel.

    `categorie` (optionnel) filtre par type : facture, rendez_vous, personnel, notification,
    newsletter (= pubs/promos), autre. Les libellés humains (« pub », « rdv »…) sont tolérés."""
    _assurer_cache(tenant)
    cat = domaine.normaliser_categorie(categorie) if categorie else ""
    msgs = stockage.lister_messages(tenant, non_lus=non_lus, categorie=cat, limite=limite)
    return {"messages": msgs, "total": len(msgs), "categorie": cat or None,
            "non_lus": sum(1 for m in msgs if not m.get("lu"))}


@app.get("/mail/{message_id}")
def lire(message_id: str, tenant: str = Depends(tenant_actuel)):
    """Lit un message complet (avec corps). 404 si absent ou appartenant à un autre tenant."""
    _assurer_cache(tenant)
    msg = stockage.lire_message(tenant, message_id)
    if not msg:
        raise HTTPException(404, "Message introuvable.")
    return msg


@app.post("/mail/trier")
def trier(tenant: str = Depends(tenant_actuel)):
    """Renvoie la boîte regroupée par catégorie (factures, rdv, perso, notifs, newsletters)."""
    _assurer_cache(tenant)
    msgs = stockage.lister_messages(tenant, limite=200)
    groupes = domaine.grouper_par_categorie(msgs)
    return {"groupes": {c: {"etiquette": resume._ETIQUETTES.get(c, c), "messages": v}
                        for c, v in groupes.items()},
            "total": len(msgs)}


@app.post("/mail/resumer")
async def resumer(corps: ResumerEntree = ResumerEntree(), tenant: str = Depends(tenant_actuel)):
    """Digest de la boîte (LLM si dispo, repli factuel honnête sinon). Lecture seule."""
    _assurer_cache(tenant)
    msgs = stockage.lister_messages(tenant, limite=200)
    return await resume.resumer(msgs, lang=corps.lang)


# ── Brouillon de réponse (action, mais JAMAIS envoyé en v0.1.0) ──────────────
@app.post("/mail/brouillon", status_code=201)
async def brouillon(corps: BrouillonEntree, tenant: str = Depends(tenant_actuel)):
    """Prépare un brouillon de réponse à un message reçu. NE L'ENVOIE PAS (rangé dans les
    brouillons). L'envoi réel viendra en v0.2.0."""
    _assurer_cache(tenant)
    msg = stockage.lire_message(tenant, corps.message_id)
    if not msg:
        raise HTTPException(404, "Message introuvable.")
    redige = await resume.rediger_brouillon(msg, corps.instruction, corps.lang)
    sujet = msg.get("sujet") or ""
    if not sujet.lower().startswith("re:"):
        sujet = "Re: " + sujet
    enr = stockage.enregistrer_brouillon(tenant, en_reponse_a=corps.message_id,
                                         a=msg.get("de", ""), sujet=sujet, corps=redige["corps"])
    return {"ok": True, "envoye": False, "brouillon": enr,
            "genere_par": redige["genere_par"], "note": redige.get("note", ""),
            "message": "Brouillon préparé (NON envoyé). L'envoi sera disponible en v0.2.0."}


@app.get("/brouillons")
def lister_brouillons(tenant: str = Depends(tenant_actuel)):
    return {"brouillons": stockage.lister_brouillons(tenant)}


# ── Back-office minimal : connecter une boîte sans passer le mdp par le chat ──
@app.get("/", response_class=HTMLResponse)
def back_office():
    """Petite page pour connecter une boîte IMAP. On préfère taper le mot de passe d'application
    ICI plutôt que dans la conversation (le chat journalise les messages)."""
    return HTMLResponse(_PAGE)


_PAGE = """<!doctype html><html lang=fr><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Mail — connecter une boîte</title>
<style>
 body{font-family:system-ui;max-width:560px;margin:48px auto;padding:0 16px;color:#1e293b}
 h1{font-size:1.4rem} label{display:block;margin:.8rem 0 .2rem;font-weight:600;font-size:.9rem}
 input{width:100%;padding:.6rem;border:1px solid #cbd5e1;border-radius:8px;font-size:1rem}
 button{margin-top:1.2rem;padding:.7rem 1.2rem;border:0;border-radius:8px;background:#4f46e5;
   color:#fff;font-size:1rem;cursor:pointer} .note{background:#f1f5f9;padding:.8rem;border-radius:8px;
   font-size:.85rem;color:#475569;margin-top:1rem} #res{margin-top:1rem;font-size:.9rem}
 code{background:#f1f5f9;padding:.1rem .3rem;border-radius:4px}
</style>
<h1>📬 Connecter une boîte mail (lecture seule)</h1>
<p class=note>Cette boîte est lue en <b>lecture seule</b> : rien n'est jamais supprimé ni déplacé.
 Utilise un <b>mot de passe d'application</b> (Gmail : Compte → Sécurité → Mots de passe des
 applications), pas ton mot de passe principal. Il est chiffré au repos, jamais affiché.</p>
<label>Serveur IMAP <input id=host placeholder="imap.gmail.com"></label>
<label>Port <input id=port value="993"></label>
<label>Adresse / utilisateur <input id=user placeholder="toi@gmail.com"></label>
<label>Mot de passe d'application <input id=pass type=password placeholder="xxxx xxxx xxxx xxxx"></label>
<label>Clé API (si la brique est protégée — sinon laisse vide) <input id=key placeholder="(vide en local)"></label>
<button onclick=connecter()>Connecter & synchroniser</button>
<div id=res></div>
<script>
async function connecter(){
 const h={'Content-Type':'application/json'}; const k=document.getElementById('key').value.trim();
 if(k) h['X-API-Key']=k;
 const r=await fetch('/comptes',{method:'POST',headers:h,body:JSON.stringify({
   host:host.value.trim(),port:+port.value||993,utilisateur:user.value.trim(),
   mot_de_passe:pass.value})});
 const j=await r.json();
 res.innerHTML = r.ok ? '✅ '+(j.message||'Connecté.') : '❌ '+(j.detail||'Échec.');
}
</script></html>"""
