"""Brique « dev » — l'auto-atelier souverain (port 5950), v0.2.0 — S87 : fusion contrôlée.

Permet de modifier les briques de Workplace et d'ajouter des features DEPUIS l'assistant, avec
le **filet git** comme garantie « ne casse pas la prod » : chaque chantier vit dans un
**worktree jetable** sur une **branche dédiée** (jamais `main`), l'agent y code, on relit le
**diff**, puis on fusionne (gate humain, incrément 4) ou on **jette** — sans trace.

Atelier PERSO SOUVERAIN : mono-user, local/self-host, jamais exposé à un client (comme la
brique paiements est cloisonnée exprès). Un agent de code = exécution arbitraire ; le filet +
le gate sont ce qui rend ça sûr. Garde-fou minimal : si `DEV_KEY` est défini, on l'exige
(en-tête `X-API-Key`).

Ce que fait la v0.1.0 (incrément 1) :
  • POST /chantiers          → ouvre un worktree + branche neuve (preuve : prod intacte)
  • POST /chantiers/{id}/lancer → l'agent (Claude Code / OpenCode, sinon mock honnête) code
  • GET  /chantiers/{id}/diff → le diff à relire (jamais déployé)
  • DELETE /chantiers/{id}   → jette le worktree (chantier effacé)

Nouveau en v0.2.0 (S87 — ferme la boucle, SEUL sprint qui touche `main`) :
  • POST /chantiers/{id}/fusionner → GATE humain (`confirme=true`) : après revue, `git merge
    --no-ff` la branche dans `main`, puis rebuild CIBLÉ de la seule brique modifiée
    (simulé honnête par défaut, réel si `DEV_REBUILD=1`), puis jette le worktree. Refuse les
    briques sensibles (paiements/connexion/auth) sauf déblocage explicite ; un conflit est
    remonté proprement, jamais forcé.

À venir : flux BMAD (plan d'abord), task trace activable, porte skills/MCP + caching,
IDE code-server, outil Cœur `dev_demander`.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import agents
import domaine
import git_atelier
import rebuild

DEV_DB = os.environ.get("DEV_DB", os.path.join(os.path.dirname(__file__), "chantiers.json"))
DEV_KEY = os.environ.get("DEV_KEY", "")  # vide = ouvert (atelier local) ; défini = exigé


def _debloquees() -> frozenset:
    """Briques sensibles débloquées au cas par cas (env `DEV_BRIQUES_DEBLOQUEES`, CSV)."""
    brut = os.environ.get("DEV_BRIQUES_DEBLOQUEES", "")
    return frozenset(b.strip() for b in brut.split(",") if b.strip())


app = FastAPI(title="Workplace — auto-atelier dev", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o] or ["*"],
    allow_methods=["*"], allow_headers=["*"],
)


# ── Garde-fou minimal (souverain, mono-user) ───────────────────────────────────
def garde(x_api_key: Optional[str] = Header(None)) -> None:
    if DEV_KEY and x_api_key != DEV_KEY:
        raise HTTPException(status_code=401, detail="clé requise (X-API-Key)")


# ── Stockage JSON simple (un seul utilisateur, un seul dépôt) ───────────────────
def _charger() -> dict:
    try:
        with open(DEV_DB, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _sauver(d: dict) -> None:
    tmp = DEV_DB + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DEV_DB)


def _chantier(cid: str) -> domaine.Chantier:
    d = _charger()
    if cid not in d:
        raise HTTPException(status_code=404, detail="chantier introuvable")
    return domaine.Chantier(**d[cid])


def _ranger(ch: domaine.Chantier) -> None:
    d = _charger()
    d[ch.id] = ch.to_dict()
    _sauver(d)


# ── Modèles d'entrée ────────────────────────────────────────────────────────────
class ChantierEntree(BaseModel):
    intention: str
    brique_cible: str = ""
    base: str = "HEAD"
    agent: str = ""          # "claude_code" | "opencode" | "" (auto)
    trace: bool = False      # task trace (narration), incrément 3
    sprint: str = ""


# ── Endpoints ───────────────────────────────────────────────────────────────────
@app.get("/sante")
def sante():
    """Vivant ? + état du filet (le dépôt cible est-il bien un dépôt git ?)."""
    return {
        "ok": True,
        "version": app.version,
        "depot_git": git_atelier.est_un_depot(),
        "agents_disponibles": [a().nom for a in (agents.ClaudeCode, agents.OpenCode, agents.Factice)
                               if a().disponible()],
    }


@app.post("/chantiers", dependencies=[Depends(garde)], status_code=201)
def ouvrir(corps: ChantierEntree):
    """Ouvre un chantier : worktree isolé + branche neuve depuis la base. Prod intacte."""
    if not git_atelier.est_un_depot():
        raise HTTPException(status_code=503, detail="dépôt git introuvable : pas de filet")
    if not corps.intention.strip():
        raise HTTPException(status_code=422, detail="intention requise")
    cid = uuid.uuid4().hex[:12]
    branche = domaine.nom_branche(corps.brique_cible, corps.intention)
    if domaine.branche_protegee(branche):
        raise HTTPException(status_code=400, detail="branche protégée refusée")
    try:
        worktree = git_atelier.ouvrir_chantier(branche, corps.base)
    except git_atelier.ErreurGit as e:
        raise HTTPException(status_code=409, detail=str(e))
    ch = domaine.Chantier(
        id=cid, intention=corps.intention, brique_cible=corps.brique_cible,
        branche=branche, base=corps.base, agent=corps.agent or "auto",
        trace_active=corps.trace, sprint=corps.sprint, worktree=worktree,
    )
    _ranger(ch)
    return ch.to_dict()


@app.get("/chantiers", dependencies=[Depends(garde)])
def lister():
    """Liste les chantiers connus (tous états confondus)."""
    return list(_charger().values())


@app.get("/chantiers/{cid}", dependencies=[Depends(garde)])
def voir(cid: str):
    return _chantier(cid).to_dict()


@app.post("/chantiers/{cid}/lancer", dependencies=[Depends(garde)])
def lancer(cid: str):
    """Lance l'agent dans le worktree : il code, commite sur SA branche. Diff prêt à relire."""
    ch = _chantier(cid)
    if not ch.peut_lancer:
        raise HTTPException(status_code=409, detail=f"chantier en état {ch.statut} : non relançable")
    agent = agents.choisir(ch.agent if ch.agent != "auto" else "")
    res = agent.executer(ch.worktree, ch.intention, trace=ch.trace_active,
                         brique_cible=ch.brique_cible)
    ch.agent = res["agent"]
    ch.resume = res["resume"]
    ch.journal = res.get("journal") or []
    if ch.statut == domaine.CREE:
        ch.avancer(domaine.EN_COURS)
    if res.get("diff_pret"):
        ch.avancer(domaine.REVUE)
    _ranger(ch)
    return ch.to_dict()


@app.get("/chantiers/{cid}/diff", dependencies=[Depends(garde)])
def diff(cid: str):
    """Le diff de la branche par rapport à la base (ce que l'humain relit au gate)."""
    ch = _chantier(cid)
    try:
        texte = git_atelier.diff_chantier(ch.branche, ch.base)
        stats = git_atelier.resume_diff(ch.branche, ch.base)
    except git_atelier.ErreurGit as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"branche": ch.branche, "base": ch.base, "stats": stats, "diff": texte}


class FusionEntree(BaseModel):
    confirme: bool = False   # gate humain : la fusion touche `main`, jamais sans confirmation


@app.post("/chantiers/{cid}/fusionner", dependencies=[Depends(garde)])
def fusionner(cid: str, corps: FusionEntree):
    """GATE : relire le diff → confirmer → fusionner dans `main` + rebuild ciblé → jeter.

    Le seul endpoint qui touche la base. Refus en cascade (le filet) :
      • état ≠ `revue`       → 409 (on ne fusionne pas un chantier non relu) ;
      • `confirme` ≠ true    → 428 (effet de bord : on exige la confirmation explicite) ;
      • brique sensible non débloquée → 403 (paiements/connexion/auth) ;
      • conflit de fusion    → 409 (remonté tel quel, jamais forcé)."""
    ch = _chantier(cid)
    if not ch.peut_fusionner:
        raise HTTPException(status_code=409,
                            detail=f"chantier en état {ch.statut} : fusion possible seulement après revue")
    if not corps.confirme:
        raise HTTPException(status_code=428,
                            detail="confirmation requise (confirme=true) : la fusion modifie main")

    # Garde-fou briques sensibles : on lit le diff pour savoir ce qui serait touché.
    try:
        touchees = git_atelier.briques_touchees(ch.branche, ch.base)
    except git_atelier.ErreurGit as e:
        raise HTTPException(status_code=409, detail=str(e))
    autorisee, bloquantes = domaine.fusion_autorisee(touchees, _debloquees())
    if not autorisee:
        raise HTTPException(
            status_code=403,
            detail=f"briques sensibles non débloquées : {', '.join(bloquantes)} "
                   f"(débloque-les via DEV_BRIQUES_DEBLOQUEES)")

    # Fusion réelle dans main (merge --no-ff, jamais de force). Un conflit est remonté propre.
    try:
        sortie = git_atelier.fusionner(ch.branche, ch.base)
    except git_atelier.ErreurGit as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Rebuild CIBLÉ des briques modifiées (simulé honnête par défaut ; réel si DEV_REBUILD=1).
    rebuilds = [rebuild.rebuild_brique(b) for b in touchees]

    # La branche est fusionnée → on transite et on jette le worktree (le chantier est clos).
    ch.avancer(domaine.FUSIONNE)
    git_atelier.jeter_chantier(ch.branche)
    _ranger(ch)
    return {"ok": True, "statut": ch.statut, "fusion": sortie,
            "briques_touchees": touchees, "rebuilds": rebuilds}


@app.delete("/chantiers/{cid}", dependencies=[Depends(garde)])
def jeter(cid: str):
    """Jette le worktree + la branche : le chantier disparaît, la prod n'a jamais bougé."""
    ch = _chantier(cid)
    git_atelier.jeter_chantier(ch.branche)
    ch.statut = domaine.JETE
    _ranger(ch)
    return {"ok": True, "statut": ch.statut}


@app.get("/", response_class=HTMLResponse)
def accueil():
    """Page minimale (l'IDE code-server en iframe est l'incrément 6)."""
    return (
        "<!doctype html><meta charset=utf-8><title>Atelier dev</title>"
        "<body style='font-family:system-ui;max-width:42rem;margin:3rem auto;color:#222'>"
        "<h1>🛠️ Auto-atelier dev</h1>"
        "<p>Brique souveraine (port 5950) — v0.2.0 (S87) : socle git + <b>fusion contrôlée</b>. "
        "Chaque chantier vit dans un <b>worktree jetable</b>, jamais sur <code>main</code> ; "
        "la fusion exige le gate humain et rebuild la <b>seule</b> brique modifiée.</p>"
        "<p>Voir <code>/sante</code> et l'API <code>/chantiers</code>.</p></body>"
    )
