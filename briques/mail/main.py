"""Brique « mail » — l'assistant s'occupe de la BOÎTE DE RÉCEPTION (entrant), v0.1.1 lecture seule.

Produit autonome (port 6030), multi-tenant par **clé API** (chaque tenant = ses boîtes isolées),
provider-agnostique. Un tenant peut connecter **plusieurs adresses** (perso, pro…) : l'assistant
voit une **boîte unifiée**, filtrable par compte. Par défaut (aucune boîte connectée) : boîte
**mock honnête** (simulée, 0 réseau). Chaque boîte IMAP connectée (mot de passe d'application,
chiffré au repos) est lue en **lecture seule**.

Ce que sait faire la v0.1.x : **lister/filtrer (catégorie, compte, non-lus), lire, résumer
(IA + repli honnête), trier** et **préparer un brouillon de réponse — JAMAIS envoyé**. L'envoi
(SMTP) est la v0.2.0.

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

app = FastAPI(title="Mail — boîtes de réception multi-tenant (lecture seule)", version="0.1.1")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


# ── Multi-tenant : la clé API identifie le PROPRIÉTAIRE (le tenant) ───────────
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


# ── Synchronisation (cache ← fournisseur, boîte unifiée) ─────────────────────
def _sync_compte(tenant: str, compte: dict, connus: set[str]) -> int:
    """Synchronise UNE boîte IMAP : récupère, tague (compte_id + adresse), enrichit, remplace sa
    part de cache. Lève si la connexion échoue (identifiants/serveur)."""
    bruts = fournisseurs.Imap(compte).recuperer()
    for m in bruts:
        m["compte_id"] = compte["id"]
        m["compte"] = compte["utilisateur"]
    enrichis = domaine.trier(bruts, connus)
    return stockage.remplacer_messages_compte(tenant, compte["id"], enrichis)


def _synchroniser(tenant: str) -> dict:
    """Rafraîchit la boîte unifiée du tenant. Aucune boîte connectée → boîte mock honnête.
    Sinon, synchronise chaque boîte indépendamment ; une boîte en échec n'efface pas les autres
    (son ancien cache est conservé) et est signalée dans `echecs`."""
    comptes = stockage.lister_comptes(tenant, avec_secret=True)
    connus = stockage.expediteurs_connus(tenant)
    if not comptes:
        bruts = fournisseurs.Mock().recuperer()
        for m in bruts:
            m["compte_id"] = None
            m["compte"] = "simulé"
        stockage.remplacer_messages(tenant, domaine.trier(bruts, connus))
        return {"comptes": 0, "messages": len(bruts), "echecs": []}
    total, echecs = 0, []
    for cpt in comptes:
        try:
            total += _sync_compte(tenant, cpt, connus)
        except Exception:  # noqa: BLE001 — une boîte KO ne casse pas la synchro des autres
            echecs.append(cpt["utilisateur"])
    return {"comptes": len(comptes), "messages": total, "echecs": echecs}


def _assurer_cache(tenant: str) -> None:
    """Garantit un cache non vide pour la première lecture (sync paresseuse)."""
    if not stockage.lister_messages(tenant, limite=1):
        _synchroniser(tenant)


# ── Santé & config ───────────────────────────────────────────────────────────
@app.get("/sante")
def sante():
    return {"ok": True, "brique": "mail", "version": "0.1.1"}


@app.get("/config")
def config(tenant: str = Depends(tenant_actuel)):
    """État honnête : les boîtes connectées (sans secret) ou le mode mock."""
    comptes = stockage.lister_comptes(tenant)
    if not comptes:
        return {"configure": False, "fournisseur": "mock", "comptes": [],
                "message": "Aucune boîte connectée : boîte SIMULÉE (mock), aucune connexion réseau."}
    return {"configure": True, "fournisseur": "imap",
            "comptes": [{"id": c["id"], "adresse": c["utilisateur"], "hote": c["host"]} for c in comptes],
            "message": f"{len(comptes)} boîte(s) connectée(s), lecture seule."}


# ── Comptes : connecter / lister / déconnecter ───────────────────────────────
@app.get("/comptes")
def lister_comptes(tenant: str = Depends(tenant_actuel)):
    """Liste les boîtes connectées (sans aucun secret)."""
    return {"comptes": [{"id": c["id"], "adresse": c["utilisateur"], "hote": c["host"],
                         "port": c["port"], "cree_le": c["cree_le"]}
                        for c in stockage.lister_comptes(tenant)]}


@app.post("/comptes", status_code=201)
def connecter_compte(corps: CompteEntree, tenant: str = Depends(tenant_actuel)):
    """AJOUTE une boîte IMAP (plusieurs possibles ; réajouter la même adresse met à jour ses
    identifiants). Mot de passe d'app chiffré au repos. On VÉRIFIE la connexion en synchronisant
    tout de suite : identifiants faux → échec propre, rien n'est conservé pour cette boîte."""
    if not os.getenv("MAIL_VAULT_SECRET"):
        raise HTTPException(503, "MAIL_VAULT_SECRET non configuré : impossible de stocker le "
                                 "mot de passe en sécurité.")
    deja = any(c["utilisateur"] == corps.utilisateur for c in stockage.lister_comptes(tenant))
    compte = stockage.enregistrer_compte(tenant, corps.host, corps.utilisateur, corps.mot_de_passe,
                                         port=corps.port, dossier=corps.dossier)
    try:
        n = _sync_compte(tenant, stockage.lire_compte(tenant, compte["id"], avec_secret=True),
                         stockage.expediteurs_connus(tenant))
    except Exception as e:  # noqa: BLE001 — identifiants/serveur KO
        if not deja:  # on n'avait pas cette boîte avant : on n'en garde pas une cassée
            stockage.supprimer_compte(tenant, compte["id"])
        raise HTTPException(400, "Connexion IMAP refusée (hôte ou identifiants incorrects). "
                                 "Astuce : utilise un MOT DE PASSE D'APPLICATION, pas ton mot de "
                                 "passe principal.") from e
    return {"ok": True, "compte": {"id": compte["id"], "adresse": compte["utilisateur"]},
            "messages_synchronises": n,
            "message": f"Boîte « {corps.utilisateur} » connectée. {n} message(s), lecture seule."}


@app.delete("/comptes/{compte_id}")
def deconnecter_compte(compte_id: str, tenant: str = Depends(tenant_actuel)):
    """Déconnecte UNE boîte (et purge ses messages cachés). Les autres boîtes restent."""
    if not stockage.supprimer_compte(tenant, compte_id):
        raise HTTPException(404, "Boîte introuvable.")
    return {"ok": True, "message": "Boîte déconnectée."}


# ── Synchronisation (cible de la tâche d'horloge `sync-mail`) ────────────────
@app.post("/mail/sync")
def sync(tenant: str = Depends(tenant_actuel)):
    """Rafraîchit la boîte unifiée. Tolère l'échec d'une boîte (signalé dans `echecs`)."""
    res = _synchroniser(tenant)
    return {"ok": True, **res}


# ── Lecture de la boîte unifiée ──────────────────────────────────────────────
@app.get("/mail")
def lister(non_lus: bool = False, categorie: str = "", compte: str = "", limite: int = 50,
           tenant: str = Depends(tenant_actuel)):
    """Liste la boîte UNIFIÉE (toutes adresses), triée par importance. Sync paresseuse au 1er appel.

    Filtres optionnels : `categorie` (facture, rendez_vous, personnel, notification, newsletter =
    pubs/promos, autre ; libellés humains tolérés) et `compte` (une adresse précise, ex.
    « perso@gmail.com »)."""
    _assurer_cache(tenant)
    cat = domaine.normaliser_categorie(categorie) if categorie else ""
    msgs = stockage.lister_messages(tenant, non_lus=non_lus, categorie=cat, compte=compte,
                                    limite=limite)
    return {"messages": msgs, "total": len(msgs), "categorie": cat or None, "compte": compte or None,
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
    """Renvoie la boîte unifiée regroupée par catégorie (factures, rdv, perso, notifs, newsletters)."""
    _assurer_cache(tenant)
    msgs = stockage.lister_messages(tenant, limite=200)
    groupes = domaine.grouper_par_categorie(msgs)
    return {"groupes": {c: {"etiquette": resume._ETIQUETTES.get(c, c), "messages": v}
                        for c, v in groupes.items()},
            "total": len(msgs)}


@app.post("/mail/resumer")
async def resumer(corps: ResumerEntree = ResumerEntree(), tenant: str = Depends(tenant_actuel)):
    """Digest de la boîte unifiée (LLM si dispo, repli factuel honnête sinon). Lecture seule."""
    _assurer_cache(tenant)
    msgs = stockage.lister_messages(tenant, limite=200)
    return await resume.resumer(msgs, lang=corps.lang)


# ── Brouillon de réponse (action, mais JAMAIS envoyé en v0.1.x) ──────────────
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


# ── Back-office minimal : gérer ses boîtes sans passer le mdp par le chat ─────
@app.get("/", response_class=HTMLResponse)
def back_office():
    """Petite page pour connecter/déconnecter des boîtes IMAP. On préfère taper le mot de passe
    d'application ICI plutôt que dans la conversation (le chat journalise les messages)."""
    return HTMLResponse(_PAGE)


_PAGE = """<!doctype html><html lang=fr><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Mail — mes boîtes</title>
<style>
 body{font-family:system-ui;max-width:600px;margin:48px auto;padding:0 16px;color:#1e293b}
 h1{font-size:1.4rem} h2{font-size:1.05rem;margin-top:2rem}
 label{display:block;margin:.7rem 0 .2rem;font-weight:600;font-size:.9rem}
 input{width:100%;padding:.6rem;border:1px solid #cbd5e1;border-radius:8px;font-size:1rem}
 button{margin-top:1rem;padding:.6rem 1.1rem;border:0;border-radius:8px;background:#4f46e5;
   color:#fff;font-size:.95rem;cursor:pointer} button.x{background:#e11d48;margin:0;padding:.3rem .6rem;font-size:.8rem}
 .note{background:#f1f5f9;padding:.8rem;border-radius:8px;font-size:.85rem;color:#475569;margin-top:1rem}
 #res{margin-top:1rem;font-size:.9rem} ul{list-style:none;padding:0}
 li{display:flex;justify-content:space-between;align-items:center;padding:.6rem .8rem;border:1px solid #e2e8f0;
   border-radius:8px;margin:.4rem 0} .vide{color:#94a3b8;font-style:italic}
</style>
<h1>📬 Mes boîtes mail (lecture seule)</h1>
<p class=note>Tes boîtes sont lues en <b>lecture seule</b> : rien n'est jamais supprimé ni déplacé.
 Utilise un <b>mot de passe d'application</b> (Gmail : Compte → Sécurité → Mots de passe des
 applications), pas ton mot de passe principal. Il est chiffré au repos, jamais affiché. Tu peux
 connecter <b>plusieurs adresses</b> : l'assistant les voit en une boîte unifiée.</p>

<h2>Boîtes connectées</h2>
<ul id=liste><li class=vide>Chargement…</li></ul>

<h2>Ajouter une boîte</h2>
<label>Serveur IMAP <input id=host placeholder="imap.gmail.com"></label>
<label>Port <input id=port value="993"></label>
<label>Adresse / utilisateur <input id=user placeholder="toi@gmail.com"></label>
<label>Mot de passe d'application <input id=pass type=password placeholder="xxxx xxxx xxxx xxxx"></label>
<label>Clé API (si la brique est protégée — sinon laisse vide) <input id=key placeholder="(vide en local)"></label>
<button onclick=connecter()>Connecter & synchroniser</button>
<div id=res></div>

<script>
function entetes(){const h={'Content-Type':'application/json'};const k=document.getElementById('key').value.trim();if(k)h['X-API-Key']=k;return h;}
async function charger(){
 const r=await fetch('/comptes',{headers:entetes()}); const j=await r.json();
 const ul=document.getElementById('liste');
 if(!j.comptes||!j.comptes.length){ul.innerHTML='<li class=vide>Aucune boîte connectée — boîte simulée par défaut.</li>';return;}
 ul.innerHTML=j.comptes.map(c=>`<li><span>📥 <b>${c.adresse}</b> <small>(${c.hote})</small></span>`
   +`<button class=x onclick="deco('${c.id}')">Déconnecter</button></li>`).join('');
}
async function connecter(){
 const r=await fetch('/comptes',{method:'POST',headers:entetes(),body:JSON.stringify({
   host:host.value.trim(),port:+port.value||993,utilisateur:user.value.trim(),mot_de_passe:pass.value})});
 const j=await r.json();
 res.innerHTML = r.ok ? '✅ '+(j.message||'Connecté.') : '❌ '+(j.detail||'Échec.');
 if(r.ok){pass.value='';user.value='';host.value='';charger();}
}
async function deco(id){
 if(!confirm('Déconnecter cette boîte ?'))return;
 await fetch('/comptes/'+id,{method:'DELETE',headers:entetes()}); charger();
}
charger();
</script></html>"""
