"""Brique « dev » — l'auto-atelier souverain (port 5950), v0.6.0 — S92 : pilotage Cœur + IDE.

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

Nouveau en v0.3.0 (S88 — flux BMAD léger : le PLAN d'abord, opt-in via `plan_requis`) :
  • POST /chantiers/{id}/planifier → l'« Architect » conçoit un plan (mini-PRD + stories +
    note de domaine DDD) AVANT de coder (LLM Gateway, repli honnête local).
  • POST /chantiers/{id}/plan/valider → 1er gate du DOUBLE gate (`confirme=true`) : valide le
    plan, ce qui débloque le codage. `lancer` est VERROUILLÉ (409) tant que ce n'est pas fait.
  Le plan validé est ensuite injecté à l'agent codeur (la story porte le contexte).

Nouveau en v0.4.0 (S89 — task trace activable, pour APPRENDRE en regardant) :
  • Interrupteur `trace` par chantier : ON → l'agent raconte chaque pas en français (factice
    narre ses pas ; Claude Code via un hook `PreToolUse` qui traduit ses outils) → archivé dans
    `chantier.journal` ET diffusé en direct.
  • GET /chantiers/{id}/trace → flux SSE de la narration en temps réel (`suivre=false` = relire
    l'archive). Trace OFF → l'agent bosse en silence, flux vide.

Nouveau en v0.5.0 (S91 — création de skills + accroche MCP, branché sur la porte S90) :
  • POST /skills (gate) → fabrique une skill « façon Claude Code » (dossier + SKILL.md avec
    frontmatter name/description/allowed-tools/mcp) ; POST /skills/persona/{role} en raccourci
    (personas BMAD Analyst/Architect/Dev/QA). GET /skills (descripteurs = niveau-0 de la porte),
    GET /skills/{nom} (complet), GET /skills/{nom}/corps (instructions + MCP = ce que charge la
    capacité `skill_<nom>` via `competence_charger`). DELETE /skills/{nom}.
  • Le Cœur découvre `dev_skills_lister`/`dev_skill_charger`/`dev_skill_creer` (manifest) → on
    liste puis on charge une skill À LA DEMANDE depuis l'assistant, sans code en dur.

Nouveau en v0.6.0 (S92 — pilotage du Cœur « à la voix » + IDE web, le sprint d'intégration) :
  • POST /demander → l'ORCHESTRATEUR en un geste : ouvre un chantier puis fait le bon premier
    pas. `plan_requis=true` → ouvre + PLANIFIE et s'arrête au gate du PLAN ; sinon → ouvre +
    LANCE l'agent et s'arrête au gate du DIFF. JAMAIS de fusion auto : les deux gates restent
    des actions confirmées à part. C'est l'outil que le Cœur appelle quand on parle à
    l'assistant (« ajoute un champ X à la brique mail ») ; il renvoie la `prochaine_etape`.
  • Le manifest expose la BOÎTE À OUTILS de pilotage découverte par le Cœur (organisme vivant
    S63) : `dev_demander` (niveau-0) + `dev_chantiers`/`dev_diff`/`dev_plan_valider`/`dev_lancer`/
    `dev_fusionner`/`dev_jeter` (niveau-1, chargées à la demande par la porte S90) → on pilote
    tout le cycle plan→code→gate→fusion EN PARLANT, gate dans le chat (boutons S76).
  • IDE web : un conteneur `code-server` monté sur le dépôt → onglet iframe « Atelier dev » au
    dashboard du Cœur (cf. briques/dev/docker-compose.yml), avec la task trace S89 à côté.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Optional

import time

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

import agents
import domaine
import git_atelier
import plan as plan_mod
import rebuild
import skills_atelier
import traceur

DEV_DB = os.environ.get("DEV_DB", os.path.join(os.path.dirname(__file__), "chantiers.json"))
DEV_KEY = os.environ.get("DEV_KEY", "")  # vide = ouvert (atelier local) ; défini = exigé


def _debloquees() -> frozenset:
    """Briques sensibles débloquées au cas par cas (env `DEV_BRIQUES_DEBLOQUEES`, CSV)."""
    brut = os.environ.get("DEV_BRIQUES_DEBLOQUEES", "")
    return frozenset(b.strip() for b in brut.split(",") if b.strip())


app = FastAPI(title="Workplace — auto-atelier dev", version="0.6.0")
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
    trace: bool = False      # task trace (narration), S89
    sprint: str = ""
    plan_requis: bool = False  # flux BMAD (S88) : exiger un plan validé avant de coder
    lang: str = "fr"         # langue du plan (Architect)


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
        plan_requis=corps.plan_requis,
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


class PlanEntree(BaseModel):
    lang: str = "fr"


class ValiderPlanEntree(BaseModel):
    confirme: bool = False   # gate de plan (BMAD) : on valide AVANT de débloquer le codage


@app.post("/chantiers/{cid}/planifier", dependencies=[Depends(garde)])
async def planifier(cid: str, corps: PlanEntree = PlanEntree()):
    """BMAD : l'« Architect » conçoit le plan (mini-PRD + stories + domaine DDD) AVANT de coder.

    Replanifiable tant qu'on n'a pas commencé à coder (`cree`/`planifie`). Un nouveau plan
    REMET À ZÉRO sa validation : on revalide ce qu'on relit."""
    ch = _chantier(cid)
    if not ch.peut_planifier:
        raise HTTPException(status_code=409,
                            detail=f"chantier en état {ch.statut} : on ne planifie qu'avant de coder")
    if ch.trace_active:
        traceur.Traceur(traceur.fichier_pour(cid)).noter(
            "L'Architect conçoit le plan : mini-PRD, stories, note de domaine (DDD).")
    ch.plan = await plan_mod.concevoir(ch.intention, ch.brique_cible, corps.lang)
    ch.plan_valide = False
    if ch.trace_active:
        traceur.Traceur(traceur.fichier_pour(cid)).noter(
            f"Plan {ch.plan.get('genere_par', '?')} prêt ({len(ch.plan.get('stories', []))} stories) "
            "— en attente de validation.")
    if ch.statut == domaine.CREE:
        ch.avancer(domaine.PLANIFIE)
    _ranger(ch)
    return ch.to_dict()


@app.post("/chantiers/{cid}/plan/valider", dependencies=[Depends(garde)])
def valider_plan(cid: str, corps: ValiderPlanEntree):
    """GATE de plan : relire le plan → confirmer → débloque le codage (`lancer`).

    409 s'il n'y a pas de plan à valider ; 428 sans confirmation explicite (premier gate du
    double gate BMAD : valide le plan, puis valide le diff)."""
    ch = _chantier(cid)
    if ch.statut != domaine.PLANIFIE or not ch.plan:
        raise HTTPException(status_code=409, detail="aucun plan à valider (planifie d'abord)")
    if not corps.confirme:
        raise HTTPException(status_code=428, detail="confirmation requise (confirme=true) pour valider le plan")
    ch.plan_valide = True
    _ranger(ch)
    return ch.to_dict()


@app.post("/chantiers/{cid}/lancer", dependencies=[Depends(garde)])
def lancer(cid: str):
    """Lance l'agent dans le worktree : il code, commite sur SA branche. Diff prêt à relire.

    BMAD : si un plan est requis mais pas validé, le codage est VERROUILLÉ (409) — c'est tout
    l'intérêt du « plan d'abord »."""
    ch = _chantier(cid)
    if ch.code_verrouille_par_plan:
        raise HTTPException(status_code=409,
                            detail="plan BMAD requis : planifie puis valide le plan avant de coder")
    if not ch.peut_lancer:
        raise HTTPException(status_code=409, detail=f"chantier en état {ch.statut} : non relançable")
    agent = agents.choisir(ch.agent if ch.agent != "auto" else "")
    tf = traceur.fichier_pour(cid) if ch.trace_active else ""
    res = agent.executer(ch.worktree, ch.intention, trace=ch.trace_active,
                         brique_cible=ch.brique_cible, plan=(ch.plan or {}).get("texte", ""),
                         trace_fichier=tf)
    ch.agent = res["agent"]
    ch.resume = res["resume"]
    ch.journal = res.get("journal") or []
    if ch.statut in (domaine.CREE, domaine.PLANIFIE):
        ch.avancer(domaine.EN_COURS)
    if res.get("diff_pret"):
        ch.avancer(domaine.REVUE)
    _ranger(ch)
    return ch.to_dict()


@app.post("/demander", dependencies=[Depends(garde)], status_code=201)
async def demander(corps: ChantierEntree):
    """PILOTAGE EN UN GESTE (S92) : ouvre un chantier puis fait le bon PREMIER pas.

    C'est l'outil que le Cœur appelle quand on lui parle (« ajoute un champ X à la brique
    mail »). Selon le flux :
      • `plan_requis=true`  → ouvre + PLANIFIE (l'Architect) → s'arrête au **gate du plan**
        (relire, puis `dev_plan_valider` confirme=true, puis `dev_lancer`) ;
      • `plan_requis=false` → ouvre + LANCE l'agent → s'arrête au **gate du diff**
        (relire `dev_diff`, puis `dev_fusionner` confirme=true, sinon `dev_jeter`).
    JAMAIS de fusion automatique : les deux gates restent des actions confirmées à part. On
    réutilise tels quels `ouvrir`/`planifier`/`lancer` (mêmes gardes, mêmes états) et on
    renvoie l'état + une `prochaine_etape` lisible pour guider l'assistant (et l'humain)."""
    ch_dict = ouvrir(corps)            # toutes les gardes d'ouverture (422/400/409/503)
    cid = ch_dict["id"]
    if ch_dict.get("plan_requis"):
        ch_dict = await planifier(cid, PlanEntree(lang=corps.lang))
        prochaine = ("Relis le plan, puis valide-le (dev_plan_valider, confirme=true) "
                     "avant de coder (dev_lancer).")
    else:
        ch_dict = lancer(cid)
        prochaine = ("Relis le diff (dev_diff), puis fusionne sur validation "
                     "(dev_fusionner, confirme=true) ou jette (dev_jeter).")
    extra = {"prochaine_etape": prochaine}
    ch = _chantier(cid)
    if ch.statut == domaine.REVUE:     # diff prêt → on joint le résumé pour la revue au chat
        try:
            extra["diff_stats"] = git_atelier.resume_diff(ch.branche, ch.base)
        except git_atelier.ErreurGit:
            pass
    return {**ch_dict, **extra}


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


@app.get("/chantiers/{cid}/trace", dependencies=[Depends(garde)])
def trace_sse(cid: str, suivre: bool = True):
    """SSE : la narration pas-à-pas EN DIRECT (S89). `suivre=false` = renvoyer l'archive puis clore.

    Quand la trace du chantier est active, l'agent y raconte ses pas en français ; ce flux les
    pousse au navigateur au fil de l'eau (apprendre en regardant). Trace OFF → flux vide."""
    _chantier(cid)  # 404 si le chantier est inconnu
    fichier = traceur.fichier_pour(cid)

    def flux():
        envoyes = 0
        fin = time.time() + 120  # garde-fou : on ne suit pas indéfiniment
        while True:
            evts = traceur.lire(fichier)
            for e in evts[envoyes:]:
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
            envoyes = len(evts)
            if not suivre or time.time() > fin:
                break
            time.sleep(0.4)
        yield "event: fin\ndata: {}\n\n"

    return StreamingResponse(flux(), media_type="text/event-stream")


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
    traceur.Traceur(traceur.fichier_pour(cid)).effacer()  # la trace live disparaît avec le chantier
    ch.statut = domaine.JETE
    _ranger(ch)
    return {"ok": True, "statut": ch.statut}


# ── Skills (S91) : fabriquer des skills façon Claude Code + les exposer à la porte ──
class SkillEntree(BaseModel):
    name: str
    description: str
    corps: str = ""                       # les INSTRUCTIONS du workflow
    outils_autorises: list[str] = []      # → frontmatter allowed-tools
    mcp: list[str] = []                   # MCP accrochés
    scripts: dict[str, str] = {}          # fichiers annexes optionnels (rel → contenu)
    ecraser: bool = False
    confirme: bool = False                # gate : écrire une skill = effet de bord (disque)


@app.get("/skills", dependencies=[Depends(garde)])
def skills_lister():
    """Liste les skills (descripteurs SANS corps = le « niveau-0 » bon marché de la porte)."""
    return {"skills": skills_atelier.lister()}


@app.get("/skills/{nom}", dependencies=[Depends(garde)])
def skills_voir(nom: str):
    """Descripteur COMPLET d'une skill (frontmatter + corps + MCP accrochés)."""
    sk = skills_atelier.lire(nom)
    if not sk:
        raise HTTPException(status_code=404, detail="skill introuvable")
    return sk


@app.get("/skills/{nom}/corps", dependencies=[Depends(garde)])
def skills_corps(nom: str):
    """Le CORPS d'une skill (instructions + MCP) — la cible de la capacité-porte (S90).

    C'est ce que renvoie la capacité `skill_<nom>` une fois chargée via `competence_charger` :
    les instructions à suivre et les MCP à utiliser. Lecture seule."""
    sk = skills_atelier.lire(nom)
    if not sk:
        raise HTTPException(status_code=404, detail="skill introuvable")
    return {"name": sk["name"], "instructions": sk["corps"],
            "outils_autorises": sk["allowed-tools"], "mcp": sk["mcp"]}


@app.post("/skills", dependencies=[Depends(garde)], status_code=201)
def skills_creer(corps: SkillEntree):
    """Fabrique une skill (gate `confirme=true` → 428) : valide le descripteur puis l'écrit.

    422 si le descripteur est invalide ; 409 si la skill existe déjà (sauf `ecraser`)."""
    if not corps.confirme:
        raise HTTPException(status_code=428,
                            detail="confirmation requise (confirme=true) : écrire une skill sur le disque")
    meta = {"name": corps.name, "description": corps.description,
            "allowed-tools": corps.outils_autorises, "mcp": corps.mcp}
    try:
        skill = skills_atelier.creer(meta, corps.corps, scripts=corps.scripts,
                                     ecraser=corps.ecraser)
    except skills_atelier.ErreurSkill as e:
        # doublon → 409 ; descripteur invalide → 422 (deux refus métier distincts).
        code = 409 if "existe déjà" in str(e) else 422
        raise HTTPException(status_code=code, detail=str(e))
    return {"ok": True, "skill": skill, "capacite": skills_atelier.capacite_pour(skill)}


class PersonaEntree(BaseModel):
    confirme: bool = False


@app.post("/skills/persona/{role}", dependencies=[Depends(garde)], status_code=201)
def skills_persona(role: str, corps: PersonaEntree = PersonaEntree()):
    """Raccourci : fabrique une **persona BMAD** (analyst/architect/dev/qa) en une skill."""
    if not corps.confirme:
        raise HTTPException(status_code=428, detail="confirmation requise (confirme=true)")
    try:
        meta, texte = skills_atelier.persona_bmad(role)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        skill = skills_atelier.creer(meta, texte, ecraser=True)  # une persona se régénère
    except skills_atelier.ErreurSkill as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "skill": skill, "capacite": skills_atelier.capacite_pour(skill)}


@app.delete("/skills/{nom}", dependencies=[Depends(garde)])
def skills_supprimer(nom: str):
    """Supprime une skill (son dossier). 404 si elle n'existe pas."""
    if not skills_atelier.supprimer(nom):
        raise HTTPException(status_code=404, detail="skill introuvable")
    return {"ok": True, "supprimee": nom}


@app.get("/", response_class=HTMLResponse)
def accueil():
    """Page minimale (l'IDE code-server est servi à part, en iframe au dashboard — S92)."""
    return (
        "<!doctype html><meta charset=utf-8><title>Atelier dev</title>"
        "<body style='font-family:system-ui;max-width:42rem;margin:3rem auto;color:#222'>"
        "<h1>🛠️ Auto-atelier dev</h1>"
        "<p>Brique souveraine (port 5950) — v0.6.0 (S92) : socle git + fusion contrôlée + "
        "flux BMAD + <b>task trace</b> + <b>fabrique de skills</b> + <b>pilotage par le Cœur</b>. "
        "Chaque chantier vit dans un <b>worktree jetable</b>, jamais sur <code>main</code> ; "
        "double gate <i>valide le plan</i> puis <i>valide le diff</i> ; trace ON → l'agent "
        "<b>raconte chaque pas en français</b>. Nouveau : <code>POST /demander</code> = pilote "
        "tout le cycle <b>en parlant à l'assistant</b> (ouvre → planifie/code → gate), et un "
        "<b>IDE web</b> (code-server) en onglet « Atelier dev » du dashboard.</p>"
        "<p>Voir <code>/sante</code>, l'API <code>/chantiers</code>, <code>/demander</code> et "
        "<code>/skills</code>.</p></body>"
    )
