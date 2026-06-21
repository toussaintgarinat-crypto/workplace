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
import envoi
import fournisseurs
import resume
import stockage

app = FastAPI(title="Mail — boîtes de réception multi-tenant + réponse sur validation", version="0.3.0")

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
    smtp_host: str = ""   # pour l'envoi (v0.2.0) ; vide = deviné depuis l'hôte IMAP
    smtp_port: int = 0


class EnvoiEntree(BaseModel):
    sujet: str | None = None   # override « validé » optionnel avant envoi
    corps: str | None = None


class FiltreEntree(BaseModel):
    nom: str
    mots: list[str] = []
    expediteur: str = ""


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
    return {"ok": True, "brique": "mail", "version": "0.3.0"}


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
                                         port=corps.port, dossier=corps.dossier,
                                         smtp_host=corps.smtp_host, smtp_port=corps.smtp_port)
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
def lister(non_lus: bool = False, categorie: str = "", compte: str = "", filtre: str = "",
           limite: int = 50, tenant: str = Depends(tenant_actuel)):
    """Liste la boîte UNIFIÉE (toutes adresses), triée par importance. Sync paresseuse au 1er appel.

    Filtres optionnels : `categorie` (facture, rendez_vous, personnel, notification, newsletter,
    autre ; libellés humains tolérés), `compte` (une adresse précise) et `filtre` (id d'un FILTRE
    PERSONNALISÉ, ex. un filtre par entreprise) qui applique ses mots-clés/expéditeur."""
    _assurer_cache(tenant)
    cat = domaine.normaliser_categorie(categorie) if categorie else ""
    if filtre:
        f = stockage.resoudre_filtre(tenant, filtre)   # par id OU par nom (ex. « Acme »)
        if not f:
            raise HTTPException(404, "Filtre introuvable.")
        bruts = stockage.lister_messages(tenant, non_lus=non_lus, categorie=cat, compte=compte,
                                         limite=500)
        msgs = [m for m in bruts
                if domaine.correspond_filtre(m, f["mots"], f["expediteur"])][:limite]
        return {"messages": msgs, "total": len(msgs), "filtre": f["nom"], "compte": compte or None,
                "non_lus": sum(1 for m in msgs if not m.get("lu"))}
    msgs = stockage.lister_messages(tenant, non_lus=non_lus, categorie=cat, compte=compte,
                                    limite=limite)
    return {"messages": msgs, "total": len(msgs), "categorie": cat or None, "compte": compte or None,
            "non_lus": sum(1 for m in msgs if not m.get("lu"))}


# ── Filtres personnalisés (ex. un filtre par entreprise) ─────────────────────
@app.get("/filtres")
def lister_filtres(tenant: str = Depends(tenant_actuel)):
    return {"filtres": stockage.lister_filtres(tenant)}


@app.post("/filtres", status_code=201)
def creer_filtre(corps: FiltreEntree, tenant: str = Depends(tenant_actuel)):
    """Crée un filtre personnalisé : un nom + des mots-clés et/ou un expéditeur (sous-chaîne, ex.
    un domaine « @acme.com » pour « les mails de l'entreprise Acme »)."""
    if not corps.nom.strip():
        raise HTTPException(400, "Donne un nom au filtre.")
    if not (corps.mots or corps.expediteur.strip()):
        raise HTTPException(400, "Un filtre a besoin d'au moins un mot-clé ou un expéditeur.")
    return stockage.enregistrer_filtre(tenant, nom=corps.nom, mots=corps.mots,
                                       expediteur=corps.expediteur)


@app.delete("/filtres/{filtre_id}")
def supprimer_filtre(filtre_id: str, tenant: str = Depends(tenant_actuel)):
    if not stockage.supprimer_filtre(tenant, filtre_id):
        raise HTTPException(404, "Filtre introuvable.")
    return {"ok": True}


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
    # On retient la boîte d'où la réponse partira (celle qui a reçu le message d'origine).
    enr = stockage.enregistrer_brouillon(
        tenant, en_reponse_a=corps.message_id, a=msg.get("de", ""), sujet=sujet,
        corps=redige["corps"], compte=msg.get("compte", ""))
    return {"ok": True, "envoye": False, "brouillon": enr,
            "genere_par": redige["genere_par"], "note": redige.get("note", ""),
            "message": "Brouillon préparé (NON envoyé). Relis/ajuste-le, puis demande l'envoi."}


@app.get("/brouillons")
def lister_brouillons(tenant: str = Depends(tenant_actuel)):
    return {"brouillons": stockage.lister_brouillons(tenant)}


def _compte_du_brouillon(tenant: str, br: dict) -> dict | None:
    """Retrouve la boîte réelle (avec secret) d'où envoyer ce brouillon, ou None (→ envoi simulé)."""
    if not br.get("compte"):
        return None
    for c in stockage.lister_comptes(tenant):
        if c["utilisateur"] == br["compte"]:
            return stockage.lire_compte(tenant, c["id"], avec_secret=True)
    return None


@app.post("/brouillons/{brouillon_id}/envoyer")
def envoyer_brouillon(brouillon_id: str, corps: EnvoiEntree = EnvoiEntree(),
                      tenant: str = Depends(tenant_actuel)):
    """ENVOIE un brouillon validé (SMTP réel si la boîte est réelle, sinon envoi SIMULÉ honnête).
    On peut passer un `sujet`/`corps` « validé » qui remplace le brouillon avant l'envoi. ACTION à
    effet de bord réel : confirme=true requis (géré par le Cœur)."""
    br = stockage.lire_brouillon(tenant, brouillon_id)
    if not br:
        raise HTTPException(404, "Brouillon introuvable.")
    if br["statut"] == "envoye":
        raise HTTPException(409, "Ce brouillon a déjà été envoyé.")
    if corps.sujet is not None or corps.corps is not None:
        br = stockage.maj_brouillon(tenant, brouillon_id, sujet=corps.sujet, corps=corps.corps)
    compte = _compte_du_brouillon(tenant, br)
    try:
        res = envoi.envoyer(compte, a=br["a"], sujet=br["sujet"], corps=br["corps"],
                            en_reponse_a_uid=str(br.get("en_reponse_a") or ""))
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from e
    stockage.marquer_brouillon_envoye(tenant, brouillon_id)
    return {"ok": True, "envoye": True, "mode": res["mode"], "de": res["de"],
            "a": br["a"], "message": res["message"]}


# ── Front-end : un vrai client mail (liste + lecture + réponse + gestion comptes) ─
@app.get("/", response_class=HTMLResponse)
def front_end():
    """Client mail complet (boîte unifiée, lecture, réponse, gestion des boîtes). Pensé pour être
    embarqué en iframe dans le dashboard du Cœur. Le mot de passe d'app se saisit ICI (la modale
    Comptes), pas dans le chat (qui journalise les messages)."""
    return HTMLResponse(_PAGE)


_PAGE = r"""<!doctype html><html lang=fr><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Mail</title>
<style>
 *{box-sizing:border-box} :root{--ac:#4f46e5;--bd:#e2e8f0;--mut:#64748b;--bg:#f8fafc}
 body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#0f172a;
   background:#fff;height:100vh;display:flex;flex-direction:column;font-size:14px}
 .top{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--bd);flex-wrap:wrap}
 .top h1{font-size:1rem;margin:0;display:flex;align-items:center;gap:6px}
 .badge{font-size:.72rem;padding:2px 8px;border-radius:999px;font-weight:600}
 .badge.mock{background:#fef9c3;color:#854d0e} .badge.reel{background:#dcfce7;color:#166534}
 .grow{flex:1}
 select,input,button,textarea{font:inherit}
 select,.btn{padding:6px 10px;border:1px solid var(--bd);border-radius:8px;background:#fff;cursor:pointer;color:#0f172a}
 .btn:hover{background:var(--bg)} .btn.pri{background:var(--ac);color:#fff;border-color:var(--ac)}
 .btn.pri:hover{filter:brightness(1.06)} .btn.sm{padding:4px 8px;font-size:.8rem}
 .search{padding:6px 10px;border:1px solid var(--bd);border-radius:8px;min-width:160px}
 .filtres{display:flex;gap:6px;padding:8px 14px;border-bottom:1px solid var(--bd);flex-wrap:wrap}
 .chip{padding:4px 10px;border:1px solid var(--bd);border-radius:999px;background:#fff;cursor:pointer;font-size:.82rem;color:var(--mut)}
 .chip.on{background:var(--ac);color:#fff;border-color:var(--ac)}
 .chip.add{border-style:dashed;color:var(--ac);font-weight:600}
 .xchip{margin-left:6px;opacity:.55;font-size:.7rem} .xchip:hover{opacity:1;color:#e11d48}
 .hint{font-size:.78rem;color:var(--mut);margin:2px 0 0}
 .body{flex:1;display:grid;grid-template-columns:minmax(280px,360px) 1fr;min-height:0}
 .liste{border-right:1px solid var(--bd);overflow:auto}
 .it{padding:10px 14px;border-bottom:1px solid #f1f5f9;cursor:pointer;display:flex;gap:8px}
 .it:hover{background:var(--bg)} .it.sel{background:#eef2ff}
 .it .dot{width:8px;height:8px;border-radius:50%;margin-top:6px;flex:none;background:transparent}
 .it.nl .dot{background:var(--ac)} .it.nl .de{font-weight:700}
 .it .mid{min-width:0;flex:1} .it .de{font-size:.86rem;display:flex;justify-content:space-between;gap:6px}
 .it .suj{font-size:.88rem;margin:1px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .it .ex{font-size:.78rem;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .it .meta{font-size:.7rem;color:var(--mut);display:flex;gap:6px;align-items:center;margin-top:3px}
 .cat{font-size:.68rem;padding:1px 6px;border-radius:999px;background:#f1f5f9;color:#475569}
 .pri-h{color:#b91c1c;font-weight:700}
 .lec{overflow:auto;padding:18px 22px} .lec .vide{color:var(--mut);margin-top:30vh;text-align:center}
 .lec h2{font-size:1.15rem;margin:0 0 4px} .lec .from{color:var(--mut);font-size:.85rem;margin-bottom:14px}
 .lec .corps{white-space:pre-wrap;line-height:1.5;border-top:1px solid var(--bd);padding-top:14px}
 .rep{margin-top:18px;border-top:1px dashed var(--bd);padding-top:14px}
 textarea{width:100%;border:1px solid var(--bd);border-radius:8px;padding:10px;min-height:130px;resize:vertical}
 .row{display:flex;gap:8px;align-items:center;margin:8px 0;flex-wrap:wrap}
 .res{font-size:.85rem;margin-left:8px}
 .modal{position:fixed;inset:0;background:rgba(15,23,42,.45);display:none;align-items:center;justify-content:center;padding:16px}
 .modal.on{display:flex} .card{background:#fff;border-radius:14px;max-width:520px;width:100%;max-height:90vh;overflow:auto;padding:20px}
 .card h3{margin:0 0 10px} .note{background:var(--bg);padding:10px;border-radius:8px;font-size:.82rem;color:#475569;margin:10px 0}
 .note a{color:var(--ac);font-weight:600;text-decoration:none} .note a:hover{text-decoration:underline}
 .acc{display:flex;justify-content:space-between;align-items:center;border:1px solid var(--bd);border-radius:8px;padding:8px 10px;margin:6px 0}
 label{display:block;font-size:.82rem;font-weight:600;margin:8px 0 3px} .fld{width:100%;padding:8px;border:1px solid var(--bd);border-radius:8px}
 .muted{color:var(--mut)}
</style></head><body>
<div class=top>
  <h1>📬 Mail <span id=mode class="badge mock">…</span></h1>
  <div class=grow></div>
  <select id=fCompte onchange=recharger()><option value="">Toutes les adresses</option></select>
  <input id=q class=search placeholder="Rechercher…" oninput=recharger()>
  <button class=btn onclick=synchroniser() title="Synchroniser">🔄</button>
  <button class=btn onclick=resumer()>✨ Résumé</button>
  <button class="btn pri" onclick=ouvrirComptes()>⚙ Comptes</button>
</div>
<div class=filtres id=filtres></div>
<div class=body>
  <div class=liste id=liste></div>
  <div class=lec id=lec><div class=vide>Sélectionne un message pour le lire.</div></div>
</div>

<div class=modal id=mComptes>
  <div class=card>
    <div style="display:flex;justify-content:space-between;align-items:center">
      <h3>Mes boîtes mail</h3><button class="btn sm" onclick=fermerComptes()>✕</button></div>
    <p class=note><b>Comment connecter ton adresse — 3 étapes :</b><br>
      <b>1.</b> Choisis ton fournisseur ci-dessous (les serveurs se remplissent tout seuls).<br>
      <b>2.</b> Sur le site de ta messagerie, génère un <b>mot de passe d'application</b> (l'aide
      s'affiche selon le fournisseur) — c'est un code DÉDIÉ à cette appli, différent de ton mot de
      passe habituel.<br>
      <b>3.</b> Saisis ton adresse + ce mot de passe d'application, puis « Connecter ».<br>
      <span class=muted>Lecture seule : rien n'est jamais supprimé ni déplacé. Le mot de passe est
      chiffré au repos, jamais affiché. Tu peux connecter plusieurs adresses.</span></p>
    <div id=accs></div>
    <h3 style="font-size:.95rem;margin-top:16px">Ajouter une boîte</h3>
    <label>Fournisseur</label>
    <select id=fourn class=fld onchange=preremplir()>
      <option value="">— Choisis ton fournisseur —</option>
      <option value=gmail>Gmail</option>
      <option value=outlook>Outlook / Hotmail / Live</option>
      <option value=icloud>iCloud / Apple</option>
      <option value=yahoo>Yahoo</option>
      <option value=autre>Autre (réglage manuel)</option>
    </select>
    <div id=aideFourn class=note style="display:none"></div>
    <label>Serveur IMAP</label><input id=host class=fld placeholder="imap.gmail.com">
    <div class=row>
      <div style=flex:1><label>Port IMAP</label><input id=port class=fld value=993></div>
      <div style=flex:2><label>Adresse</label><input id=user class=fld placeholder="toi@gmail.com"></div>
    </div>
    <label>Mot de passe d'application</label><input id=pass type=password class=fld placeholder="xxxx xxxx xxxx xxxx">
    <div class=row>
      <div style=flex:2><label>Serveur SMTP <span class=muted>(deviné sinon)</span></label><input id=smtp class=fld placeholder="smtp.gmail.com"></div>
      <div style=flex:1><label>Port SMTP</label><input id=smtpport class=fld value=587></div>
    </div>
    <label>Clé API <span class=muted>(vide en local)</span></label><input id=key class=fld placeholder="(vide)">
    <div class=row><button class="btn pri" onclick=connecter()>Connecter & synchroniser</button><span id=accres class=res></span></div>
  </div>
</div>

<div class=modal id=mFiltre>
  <div class=card>
    <div style="display:flex;justify-content:space-between;align-items:center">
      <h3>Nouveau filtre</h3><button class="btn sm" onclick=fermerFiltre()>✕</button></div>
    <p class=note>Crée un filtre sur mesure — par exemple <b>un filtre par entreprise</b> : mets le
      domaine de la société dans « Expéditeur » (ex. <code>@acme.com</code>), tu verras alors
      uniquement les mails d'Acme. Tu peux aussi viser des mots-clés.</p>
    <label>Nom du filtre</label><input id=fNom class=fld placeholder="Entreprise Acme">
    <label>Expéditeur contient <span class=muted>(optionnel)</span></label>
    <input id=fExp class=fld placeholder="@acme.com">
    <label>Mots-clés <span class=muted>(optionnel, séparés par des virgules)</span></label>
    <input id=fMots class=fld placeholder="facture, devis, commande">
    <p class=hint>Au moins un expéditeur OU un mot-clé. Un mail correspond s'il contient l'un des
      mots ET (si rempli) l'expéditeur.</p>
    <div class=row><button class="btn pri" onclick=creerFiltre()>Créer le filtre</button><span id=fres class=res></span></div>
  </div>
</div>

<script>
const CATS=[['','Tout'],['__nl','Non lus'],['facture','💶 Factures'],['rendez_vous','📅 RDV'],
  ['personnel','👤 Perso'],['notification','🔔 Notifs'],['newsletter','📰 Newsletters'],['autre','✉️ Autres']];
let FILTRES=[];
const ETIQ={facture:'💶 facture',rendez_vous:'📅 rdv',personnel:'👤 perso',notification:'🔔 notif',newsletter:'📰 pub',autre:'✉️ autre'};
let filtre='', selId=null, MSGS=[];
function esc(s){return (s||'').replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));}
function entetes(){const h={'Content-Type':'application/json'};const k=(document.getElementById('key')||{}).value;if(k&&k.trim())h['X-API-Key']=k.trim();return h;}
function dateCourte(s){if(!s)return '';const d=new Date(s);if(isNaN(d))return '';const au=new Date();
  return d.toDateString()===au.toDateString()?d.toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'}):d.toLocaleDateString('fr-FR',{day:'2-digit',month:'short'});}

function dessinerFiltres(){
  const base=CATS.map(([v,l])=>
    `<span class="chip ${filtre===v?'on':''}" onclick="setFiltre('${v}')">${l}</span>`).join('');
  const perso=FILTRES.map(f=>{const v='f:'+f.id;
    return `<span class="chip ${filtre===v?'on':''}" onclick="setFiltre('${v}')" title="${esc((f.mots||[]).join(', '))}${f.expediteur?(' · '+esc(f.expediteur)):''}">⭐ ${esc(f.nom)}`
      +`<span class="xchip" onclick="event.stopPropagation();supprimerFiltre('${f.id}')">✕</span></span>`;}).join('');
  document.getElementById('filtres').innerHTML=base+perso+
    `<span class="chip add" onclick="ouvrirFiltre()">+ Filtre</span>`;
}
function setFiltre(v){filtre=v;dessinerFiltres();recharger();}

async function chargerConfig(){
  const j=await fetch('/config',{headers:entetes()}).then(r=>r.json());
  const el=document.getElementById('mode');
  if(j.fournisseur==='imap'){el.className='badge reel';el.textContent=(j.comptes.length)+' boîte(s)';}
  else{el.className='badge mock';el.textContent='boîte simulée';}
  const sel=document.getElementById('fCompte');const cur=sel.value;
  sel.innerHTML='<option value="">Toutes les adresses</option>'+
    (j.comptes||[]).map(c=>`<option value="${esc(c.adresse)}">${esc(c.adresse)}</option>`).join('');
  sel.value=cur;
}

async function recharger(){
  const p=new URLSearchParams();
  if(filtre==='__nl')p.set('non_lus','true');
  else if(filtre.startsWith('f:'))p.set('filtre',filtre.slice(2));
  else if(filtre)p.set('categorie',filtre);
  const compte=document.getElementById('fCompte').value; if(compte)p.set('compte',compte);
  p.set('limite','200');
  const j=await fetch('/mail?'+p,{headers:entetes()}).then(r=>r.json());
  let msgs=j.messages||[]; const q=document.getElementById('q').value.trim().toLowerCase();
  if(q)msgs=msgs.filter(m=>((m.sujet||'')+' '+(m.de_nom||'')+' '+(m.de||'')+' '+(m.extrait||'')).toLowerCase().includes(q));
  MSGS=msgs;
  const L=document.getElementById('liste');
  if(!msgs.length){L.innerHTML='<div class=vide style="padding:30px;color:#94a3b8">Aucun message.</div>';return;}
  L.innerHTML=msgs.map(m=>`<div class="it ${m.lu?'':'nl'} ${m.id===selId?'sel':''}" onclick="ouvrir('${m.id}')">
    <span class=dot></span><div class=mid>
      <div class=de><span class=de>${esc(m.de_nom||m.de)}</span><span class=muted style="font-size:.72rem">${dateCourte(m.date)}</span></div>
      <div class=suj>${esc(m.sujet||'(sans sujet)')}</div>
      <div class=ex>${esc(m.extrait||'')}</div>
      <div class=meta><span class=cat>${ETIQ[m.categorie]||m.categorie||''}</span>
        ${m.score>=70?'<span class=pri-h>● prioritaire</span>':''}
        ${m.compte?('<span class=muted>'+esc(m.compte)+'</span>'):''}</div>
    </div></div>`).join('');
}

async function ouvrir(id){
  selId=id; recharger();
  const m=await fetch('/mail/'+id,{headers:entetes()}).then(r=>r.json());
  if(m.detail){document.getElementById('lec').innerHTML='<div class=vide>Message introuvable.</div>';return;}
  document.getElementById('lec').innerHTML=`
    <h2>${esc(m.sujet||'(sans sujet)')}</h2>
    <div class=from><b>${esc(m.de_nom||m.de)}</b> &lt;${esc(m.de)}&gt; · ${dateCourte(m.date)}
      ${m.compte?(' · <span class=muted>reçu sur '+esc(m.compte)+'</span>'):''}</div>
    <div class=corps>${esc(m.corps||m.extrait||'')}</div>
    <div class=rep id=rep>
      <div class=row>
        <input id=consigne class=search style="flex:1" placeholder="Consigne (optionnel) : « décline poliment », « propose jeudi 14h »…">
        <button class=btn onclick="preparer('${m.id}')">✍️ Préparer une réponse</button>
      </div>
      <div id=compose></div>
    </div>`;
}

async function preparer(mid){
  const consigne=document.getElementById('consigne').value;
  document.getElementById('compose').innerHTML='<p class=muted>Rédaction…</p>';
  const j=await fetch('/mail/brouillon',{method:'POST',headers:entetes(),
    body:JSON.stringify({message_id:mid,instruction:consigne})}).then(r=>r.json());
  if(!j.brouillon){document.getElementById('compose').innerHTML='<p class=muted>Échec.</p>';return;}
  const b=j.brouillon;
  document.getElementById('compose').innerHTML=`
    <div class=muted style="font-size:.78rem;margin:6px 0">Brouillon ${j.genere_par==='ia'?'(assistant)':'(modèle local)'}${b.compte?'':' · envoi simulé (boîte mock)'}. Relis/ajuste avant d'envoyer.</div>
    <textarea id=corps>${esc(b.corps)}</textarea>
    <div class=row><button class="btn pri" onclick="envoyer('${b.id}')">📤 Envoyer la réponse</button>
      <span id=envres class=res></span></div>`;
}

async function envoyer(bid){
  if(!confirm('Envoyer cette réponse ?'))return;
  const corps=document.getElementById('corps').value;
  const r=await fetch('/brouillons/'+bid+'/envoyer',{method:'POST',headers:entetes(),body:JSON.stringify({corps})});
  const j=await r.json();
  document.getElementById('envres').innerHTML = r.ok
    ? (j.mode==='reel'?'✅ ':'🟡 ')+esc(j.message||'Envoyé.')
    : '❌ '+esc(j.detail||'Échec.');
}

async function synchroniser(){
  const j=await fetch('/mail/sync',{method:'POST',headers:entetes()}).then(r=>r.json());
  recharger();
  if(j.echecs&&j.echecs.length)alert('Boîtes en échec : '+j.echecs.join(', '));
}

async function resumer(){
  document.getElementById('lec').innerHTML='<p class=muted style="padding:20px">Résumé en cours…</p>';
  const j=await fetch('/mail/resumer',{method:'POST',headers:entetes(),body:JSON.stringify({lang:'fr'})}).then(r=>r.json());
  document.getElementById('lec').innerHTML=`<h2>✨ Le point sur ta boîte</h2>
    <div class=muted style="font-size:.78rem;margin-bottom:8px">${j.genere_par==='ia'?'Résumé par l’assistant':'Résumé local'}</div>
    <div class=corps style="border:0;padding:0">${esc(j.texte||'')}</div>`;
}

// ── Modale Comptes ──────────────────────────────────────────────────────────
function ouvrirComptes(){document.getElementById('mComptes').classList.add('on');chargerComptes();}
function fermerComptes(){document.getElementById('mComptes').classList.remove('on');chargerConfig();recharger();}
async function chargerComptes(){
  const j=await fetch('/comptes',{headers:entetes()}).then(r=>r.json());
  const box=document.getElementById('accs');
  box.innerHTML=(j.comptes&&j.comptes.length)
    ? j.comptes.map(c=>`<div class=acc><span>📥 <b>${esc(c.adresse)}</b> <span class=muted>(${esc(c.hote)})</span></span>
        <button class="btn sm" onclick="deco('${c.id}')">Déconnecter</button></div>`).join('')
    : '<p class=muted>Aucune boîte connectée — boîte simulée par défaut.</p>';
}
async function connecter(){
  const g=id=>document.getElementById(id).value;
  document.getElementById('accres').textContent='Connexion…';
  const r=await fetch('/comptes',{method:'POST',headers:entetes(),body:JSON.stringify({
    host:g('host').trim(),port:+g('port')||993,utilisateur:g('user').trim(),mot_de_passe:g('pass'),
    smtp_host:g('smtp').trim(),smtp_port:+g('smtpport')||0})});
  const j=await r.json();
  document.getElementById('accres').innerHTML = r.ok?'✅ '+esc(j.message||'Connecté.'):'❌ '+esc(j.detail||'Échec.');
  if(r.ok){['host','user','pass','smtp'].forEach(i=>document.getElementById(i).value='');chargerComptes();chargerConfig();}
}
async function deco(id){
  if(!confirm('Déconnecter cette boîte ?'))return;
  await fetch('/comptes/'+id,{method:'DELETE',headers:entetes()});chargerComptes();
}
const PROVIDERS={
 gmail:{imap:'imap.gmail.com',smtp:'smtp.gmail.com',aide:`<b>Gmail</b> — active d'abord la <b>validation en 2 étapes</b>, puis génère un mot de passe d'application : <a href="https://myaccount.google.com/apppasswords" target=_blank rel=noopener>myaccount.google.com/apppasswords</a>. Colle ici le code de 16 lettres (sans les espaces).`},
 outlook:{imap:'outlook.office365.com',smtp:'smtp.office365.com',aide:`<b>Outlook / Hotmail / Live</b> — active la vérification en 2 étapes, puis crée un mot de passe d'application : <a href="https://account.microsoft.com/security" target=_blank rel=noopener>account.microsoft.com/security</a> → Options de sécurité avancées → Mots de passe d'application.`},
 icloud:{imap:'imap.mail.me.com',smtp:'smtp.mail.me.com',aide:`<b>iCloud / Apple</b> — active l'authentification à deux facteurs, puis crée un « mot de passe pour app » : <a href="https://appleid.apple.com" target=_blank rel=noopener>appleid.apple.com</a> → Connexion et sécurité → Mots de passe d'app.`},
 yahoo:{imap:'imap.mail.yahoo.com',smtp:'smtp.mail.yahoo.com',aide:`<b>Yahoo</b> — sécurité du compte : <a href="https://login.yahoo.com/account/security" target=_blank rel=noopener>login.yahoo.com/account/security</a> → Générer un mot de passe d'application.`},
 autre:{imap:'',smtp:'',aide:`<b>Autre fournisseur</b> — renseigne à la main les serveurs IMAP (port 993) et SMTP (port 587). Utilise un <b>mot de passe d'application</b> si ton fournisseur en propose ; sinon ton mot de passe habituel.`},
};
function preremplir(){
  const v=document.getElementById('fourn').value, p=PROVIDERS[v], aide=document.getElementById('aideFourn');
  if(!p){aide.style.display='none';return;}
  document.getElementById('host').value=p.imap;
  document.getElementById('smtp').value=p.smtp;
  document.getElementById('port').value=993;
  document.getElementById('smtpport').value=587;
  aide.style.display='block'; aide.innerHTML=p.aide+' <span class=muted>Les serveurs ont été remplis pour toi.</span>';
}

// ── Filtres personnalisés (ex. un par entreprise) ───────────────────────────
async function chargerFiltres(){
  const j=await fetch('/filtres',{headers:entetes()}).then(r=>r.json());
  FILTRES=j.filtres||[]; dessinerFiltres();
}
function ouvrirFiltre(){document.getElementById('mFiltre').classList.add('on');}
function fermerFiltre(){document.getElementById('mFiltre').classList.remove('on');}
async function creerFiltre(){
  const nom=document.getElementById('fNom').value.trim();
  const exp=document.getElementById('fExp').value.trim();
  const mots=document.getElementById('fMots').value.split(',').map(s=>s.trim()).filter(Boolean);
  if(!nom){document.getElementById('fres').textContent='Donne un nom.';return;}
  if(!exp&&!mots.length){document.getElementById('fres').textContent='Mets un expéditeur ou un mot-clé.';return;}
  const r=await fetch('/filtres',{method:'POST',headers:entetes(),
    body:JSON.stringify({nom,expediteur:exp,mots})});
  if(!r.ok){const j=await r.json();document.getElementById('fres').textContent='❌ '+(j.detail||'Échec.');return;}
  ['fNom','fExp','fMots'].forEach(i=>document.getElementById(i).value='');
  document.getElementById('fres').textContent='';
  fermerFiltre(); await chargerFiltres();
}
async function supprimerFiltre(id){
  if(!confirm('Supprimer ce filtre ?'))return;
  if(filtre==='f:'+id)filtre='';
  await fetch('/filtres/'+id,{method:'DELETE',headers:entetes()});
  await chargerFiltres(); recharger();
}

dessinerFiltres(); chargerFiltres(); chargerConfig().then(recharger);
</script></body></html>"""
