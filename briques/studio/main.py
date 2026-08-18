"""Brique « studio » — atelier d'audio-séries co-créées, en API (S51).

Produit autonome extrait d'Oria : la même usine narrative (bible → épisodes → audio →
livre → arbre des choix), mais sans dépendance à la base, à l'auth Keycloak ni au
`world_id` d'Oria. L'équipe créative (6 agents) est INTERNALISÉE (`agents.py`) ; les
séries sont persistées en JSON dans un volume propre (`STUDIO_DIR`).

Le studio COMPOSE d'autres briques (il ne les absorbe pas) :
  • voix (5810, service hôte say+ffmpeg) → sonorisation ;
  • images (5950) → portraits & couvertures ;
  • Gateway LLM (4001) → l'équipe créative.

Auth BYO optionnelle (API_KEYS) pour vendre la brique seule ; mode ouvert par défaut.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional

import agents
import composition
import studio as S

app = FastAPI(title="Studio — atelier d'audio-séries", version="0.4.0")
# Origines navigateur autorisées : liste explicite via CORS_ORIGINS (CSV). Défaut "*"
# = comportement historique. En contexte MULTI-TENANT (même local : autre tenant/
# assistant sur la machine), définir CORS_ORIGINS=http://localhost:5100,... pour
# qu'une page web tierce ne puisse pas appeler cette brique depuis le navigateur.
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

# Clés API acceptées (séparées par virgule). Vide = mode OUVERT (dev) : tenant unique "public".
# `API_KEYS` = vente standalone (BYO), chaque clé cliente = son propre tenant (motif historique).
API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None),
            x_user_id: Optional[str] = Header(None)) -> str:
    """Valide la clé API (X-API-Key ou Authorization: Bearer) et sert d'identité créateur.

    Trois dialectes (S187) :
    - clé == `STUDIO_KEY` (compte de service du Cœur, LUE FRAÎCHE à chaque appel via
      `os.environ` — motif ECOUTE_KEY/MAIL_KEY, monkeypatchable en test) → identité =
      `X-User-Id` transmis par le Cœur (repli `"perso"` si absent) : isolation PAR PERSONNE
      dans le cercle privé.
    - clé dans `API_KEYS` mais ≠ `STUDIO_KEY` (vente BYO standalone) → identité = la clé
      elle-même (motif historique, inchangé — `X-User-Id` est ignoré, ce n'est pas le Cœur
      qui appelle).
    - Mode ouvert (aucune clé configurée du tout) → identité = la clé présentée ou `"public"`
      (comportement actuel, inchangé).
    """
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    studio_key = os.environ.get("STUDIO_KEY", "").strip()
    if studio_key and presentee == studio_key:
        return x_user_id or "perso"
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


def _identite_effective(serie: dict) -> str:
    """Normalise `cree_par` à la LECTURE (jamais réécrit dans le fichier, S187) : une valeur
    legacy — mode ouvert historique (`"public"`) ou ancienne `STUDIO_KEY` brute d'avant ce
    sprint — est traitée comme `"perso"`, le bucket mono-user par défaut du dialecte par
    personne. N'affecte PAS le dialecte BYO : la clé d'un client reste sa propre identité."""
    valeur = serie.get("cree_par")
    studio_key = os.environ.get("STUDIO_KEY", "").strip()
    if studio_key and (valeur in (None, "public") or valeur == studio_key):
        return "perso"
    return valeur if valeur is not None else "public"


def charger(serie_id: str, identite: str) -> dict:
    """Charge une série (404 si absente OU si elle n'appartient pas à `identite`) — wrap
    honnête de la persistance fichier. 404 (pas 403, motif mail/ecoute) : ne révèle jamais
    l'existence d'une série à quelqu'un d'autre."""
    try:
        serie = S._load(serie_id)
    except FileNotFoundError:
        raise HTTPException(404, "Série introuvable")
    if _identite_effective(serie) != identite:
        raise HTTPException(404, "Série introuvable")
    return serie


def _profil_de(profil_id: str, identite: str) -> dict:
    """Charge un profil lecteur (404 si absent OU d'une autre identité) — même motif que
    `charger()` pour les séries (S187) : ne révèle jamais l'existence d'un profil étranger."""
    try:
        profil = S._load_profil(profil_id)
    except FileNotFoundError:
        raise HTTPException(404, "Profil introuvable")
    if profil.get("cree_par") != identite:
        raise HTTPException(404, "Profil introuvable")
    return profil


def _agent(mot: str):
    """Agent interne par mot-clé (l'équipe est toujours présente)."""
    try:
        return agents.agent(mot)
    except KeyError as e:
        raise HTTPException(500, str(e))


def _description_portrait(portrait: dict) -> str:
    """Petite description de casting dérivée du portrait holistique (forces / à travailler)."""
    forces = [str(f).strip() for f in (portrait.get("forces") or []) if str(f).strip()]
    faiblesse = str(portrait.get("faiblesse") or "").strip()
    bouts = []
    if forces:
        bouts.append("Forces : " + " · ".join(forces[:3]))
    if faiblesse:
        bouts.append("à travailler : " + faiblesse)
    return " — ".join(bouts)


def _empreinte_texte(empreinte: list) -> list:
    """Aplati l'empreinte holistique ([{cle, valeur, sens}]) en lignes lisibles (max 20)."""
    lignes = []
    for e in empreinte or []:
        if isinstance(e, dict):
            cle, val = str(e.get("cle") or "").strip(), str(e.get("valeur") or "").strip()
            ligne = f"{cle} : {val}" if cle and val else (cle or val)
        else:
            ligne = str(e).strip()
        if ligne:
            lignes.append(ligne)
    return lignes[:20]


# ── Front (servi PAR la brique : démo autonome + iframe Hub Oria) ─
_FRONT = Path(__file__).parent / "front.html"
_LECTURE = Path(__file__).parent / "lecture.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/atelier", response_class=HTMLResponse, include_in_schema=False)
def front():
    """Atelier Studio en une page (vanilla). Parle à CETTE brique (port 6060).

    Sert deux rôles : démo de la brique vendue seule ET contenu de l'iframe que le Hub
    Créations d'Oria embarque (comme Personnages 5900 / Images 5950)."""
    return _FRONT.read_text(encoding="utf-8")


@app.get("/lecture", response_class=HTMLResponse, include_in_schema=False)
def lecture():
    """Mode enfant : lecture interactive d'une série (?serie=&profil=), séparée de
    l'atelier de co-création."""
    return _LECTURE.read_text(encoding="utf-8")


# Socle partagé « manipulation directe » (S101) : menu contextuel + modale + cliquer-déposer.
# Source unique = shared/manipulation_directe.js, copié ici par outils/sync_socle.sh.
_SOCLE = Path(__file__).parent / "manipulation_directe.js"


@app.get("/manipulation_directe.js", include_in_schema=False)
def socle():
    return FileResponse(_SOCLE, media_type="application/javascript")


# Design system partagé (S123) : tokens visuels du monorepo.
# Source unique = shared/static/workplace.css, copié ici par outils/sync_socle.sh.
@app.get("/workplace.css", include_in_schema=False)
def design_system():
    return FileResponse(Path(__file__).parent / "workplace.css", media_type="text/css")


# ── Santé & équipe ───────────────────────────────────────────────
@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok", "service": "studio", "version": app.version,
            "auth": "cle_api" if API_KEYS else "ouvert",
            "equipe": [a.nom for a in agents.AGENTS],
            "langues": [c for c in S.LANGUES],
            "llm_defaut": agents.GATEWAY_MODEL,
            "compose": {"voix": S.VOIX_URL, "images": S.IMAGES_URL,
                        "video": S.VIDEO_URL,
                        "personnages": composition.PERSONNAGES_URL,
                        "gateway": agents.GATEWAY_URL}}


@app.get("/equipe", tags=["système"])
def equipe(_cle: str = Depends(cle_api)):
    """L'équipe créative internalisée (remplace l'installation d'agents par monde)."""
    return [{"nom": a.nom, "avatar": a.avatar_emoji, "x": a.map_x, "y": a.map_y}
            for a in agents.AGENTS]


# ── Modèles de requête ───────────────────────────────────────────
class CreerSerie(BaseModel):
    titre:    Optional[str] = None
    genre:    Optional[str] = None   # semence facultative
    idee:     Optional[str] = None   # idée libre de départ
    cible:    Optional[str] = None   # public cible (âge du lecteur), ex. "0-3"
    langue:   Optional[str] = None   # langue de TRAVAIL ; défaut "fr"
    world_id: Optional[str] = None   # rattachement Oria FACULTATIF (hook S53)


class ReordonnerSeries(BaseModel):
    ids: list[str] = []              # nouvelle suite des id de séries (S104 cliquer-déposer)


class Proposer(BaseModel):
    dimension: str
    mon_idee:  Optional[str] = None


class Decider(BaseModel):
    dimension: str
    choix:     str


class FaireEpisode(BaseModel):
    branche:       Optional[str] = None
    n:             Optional[int] = None
    langue_sortie: Optional[str] = None
    profil_id:     Optional[str] = None


class CibleEpisode(BaseModel):
    minutes: int


class DefinirCible(BaseModel):
    cible: Optional[str] = None


class DefinirLangue(BaseModel):
    langue: str


class MajValeur(BaseModel):
    valeur: Optional[str] = None


class MajFamille(BaseModel):
    nom_famille: Optional[str] = None


class CreerProfil(BaseModel):
    nom: str
    cible: str


class MajProfil(BaseModel):
    nom:   Optional[str] = None
    cible: Optional[str] = None


class CreerPerso(BaseModel):
    nom:         str
    role:        Optional[str] = None
    description: Optional[str] = None
    voix:        Optional[dict] = None


class MajPerso(BaseModel):
    nom:           Optional[str] = None
    nom_naissance: Optional[str] = None   # nom cosmique d'origine (renommer = nom de scène)
    role:          Optional[str] = None
    description:   Optional[str] = None
    voix:          Optional[dict] = None


class ProposerDistribution(BaseModel):
    mon_idee: Optional[str] = None
    combien:  Optional[int] = 4


class ImporterPerso(BaseModel):
    nom:           str
    nom_naissance: Optional[str] = None   # nom cosmique d'origine (figé si absent → = nom)
    role:          Optional[str] = None
    description:   Optional[str] = None
    archetype:     Optional[str] = None
    empreinte:     Optional[list] = None
    source:        Optional[str] = "personnages"


class ImporterFiche(BaseModel):
    """Ajoute à la série un personnage ENREGISTRÉ dans l'atelier holistique (5900), en lui
    donnant un nom de scène. Le Studio va chercher la fiche complète par son id."""
    fiche_id: str
    nom:      Optional[str] = None         # nom de scène ; défaut = nom de la fiche


class CreerCycle(BaseModel):
    titre:  Optional[str] = None
    resume: Optional[str] = None


class CreerTome(BaseModel):
    titre:  Optional[str] = None
    resume: Optional[str] = None


class Renommer(BaseModel):
    titre:  Optional[str] = None
    resume: Optional[str] = None
    statut: Optional[str] = None


class TomeActif(BaseModel):
    tome_id: str


class Express(BaseModel):
    idee: Optional[str] = None


class Arbre(BaseModel):
    profondeur: int = 3


class Etendre(BaseModel):
    choix: str


class MarquerLu(BaseModel):
    profil_id: str


# ── Séries (CRUD) ────────────────────────────────────────────────
@app.post("/series", tags=["séries"])
def creer_serie(body: CreerSerie, cle: str = Depends(cle_api)):
    serie = {
        "id": uuid.uuid4().hex,
        "world_id": body.world_id,
        "titre": body.titre or "Série sans titre",
        "cible": body.cible if body.cible in S.CIBLES else None,
        "langue": S._norm_langue(body.langue),
        "bible": {},
        "personnages": [],
        "episodes": [],
        "cree_par": cle,
        "cree_le": datetime.now(timezone.utc).isoformat(),
    }
    if body.genre:
        serie["bible"]["genre"] = body.genre
    if body.idee:
        serie["bible"]["idée de départ"] = body.idee
    S._normaliser(serie)
    S._save(serie)
    return serie


@app.get("/series", tags=["séries"])
def lister_series(world_id: Optional[str] = None, cle: str = Depends(cle_api)):
    """Liste toutes les séries (résumé), filtrables par monde (si fourni)."""
    out = []
    for fn in os.listdir(S.ATELIERS_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(S.ATELIERS_DIR, fn), encoding="utf-8") as f:
                s = json.load(f)
        except Exception:
            continue
        if _identite_effective(s) != cle:
            continue
        if world_id and s.get("world_id") != world_id:
            continue
        S._normaliser(s)
        out.append({
            "id": s.get("id"), "titre": s.get("titre"), "world_id": s.get("world_id"),
            "briques": len(s.get("bible", {})), "episodes": len(s.get("episodes", [])),
            "personnages": len(s.get("personnages") or []),
            "cycles": len(s.get("cycles", [])), "tomes": len(S._tous_tomes(s)),
            "cible": s.get("cible"),
            "langue": s.get("langue") or S.LANGUE_DEFAUT,
            "arbre": bool(s.get("arbre")), "cree_le": s.get("cree_le"),
            "ordre": s.get("ordre"),
        })
    # S104 — ordre d'affichage : par défaut la plus récente d'abord ; dès qu'on réordonne
    # à la main (cliquer-déposer), `ordre` prime. Tri stable en 2 passes : récence, puis
    # `ordre` croissant (les séries non rangées — ordre None — restent en tête, par récence).
    out.sort(key=lambda x: x.get("cree_le") or "", reverse=True)
    out.sort(key=lambda x: x["ordre"] if x.get("ordre") is not None else -1)
    return out


@app.post("/series/reordonner", tags=["séries"])
def reordonner_series(body: ReordonnerSeries, cle: str = Depends(cle_api)):
    """Réordonne les séries par cliquer-déposer (S104). `ids` = la nouvelle suite ; chaque
    série reçoit son rang comme `ordre` (persisté dans son fichier d'atelier). Un id qui
    n'appartient pas à l'appelant est IGNORÉ silencieusement (S187) : c'est un
    réordonnancement best-effort de SA propre liste, pas une opération qu'on veut faire
    échouer en bloc pour un id étranger glissé dans la requête."""
    rang = 0
    for sid in body.ids:
        try:
            serie = S._load(sid)
        except FileNotFoundError:
            continue
        if _identite_effective(serie) != cle:
            continue
        serie["ordre"] = rang
        S._save(serie)
        rang += 1
    return {"ok": True, "ordonnees": rang}


@app.get("/series/{serie_id}", tags=["séries"])
def lire_serie(serie_id: str, cle: str = Depends(cle_api)):
    return charger(serie_id, cle)


@app.delete("/series/{serie_id}", status_code=204, tags=["séries"])
def supprimer_serie(serie_id: str, cle: str = Depends(cle_api)):
    charger(serie_id, cle)  # 404 si absente ou pas à `cle` (S187) — jamais de suppression à l'aveugle
    p = S._path(serie_id)
    if os.path.exists(p):
        os.remove(p)
    return None


# ── Épisodes d'écoute (~12 min) ──────────────────────────────────
@app.get("/series/{serie_id}/episodes", tags=["épisodes"])
def decoupage_episodes(serie_id: str, cle: str = Depends(cle_api)):
    return S._decoupage_episodes(charger(serie_id, cle))


@app.post("/series/{serie_id}/cible-episode", tags=["épisodes"])
def definir_cible_episode(serie_id: str, body: CibleEpisode, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    serie["cible_episode_secondes"] = max(1, min(int(body.minutes), 60)) * 60
    S._save(serie)
    return S._decoupage_episodes(serie)


# ── Public cible ─────────────────────────────────────────────────
@app.get("/cibles", tags=["réglages"])
def lister_cibles(_cle: str = Depends(cle_api)):
    return [{"cle": k, "label": v} for k, v in S.CIBLES.items()]


@app.get("/valeurs", tags=["réglages"])
def lister_valeurs(_cle: str = Depends(cle_api)):
    return [{"cle": k, "label": v} for k, v in S.VALEURS.items()]


@app.patch("/series/{serie_id}/episodes/{n}/valeur", tags=["réglages"])
def modifier_valeur_episode(serie_id: str, n: int, body: MajValeur, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    ep = next((e for e in serie.get("episodes", []) if e.get("n") == n), None)
    if not ep:
        raise HTTPException(404, f"Chapitre {n} introuvable.")
    if body.valeur is not None and body.valeur not in S.VALEURS:
        raise HTTPException(400, f"Valeur inconnue : {body.valeur}")
    ep["valeur"] = body.valeur
    S._save(serie)
    return {"valeur": ep["valeur"], "valeur_suggeree": ep.get("valeur_suggeree")}


@app.get("/famille", tags=["famille"])
def lire_famille(cle: str = Depends(cle_api)):
    return S._load_compte(cle)


@app.patch("/famille", tags=["famille"])
def modifier_famille(body: MajFamille, cle: str = Depends(cle_api)):
    nom = body.nom_famille.strip() if body.nom_famille else None
    S._save_compte(cle, {"nom_famille": nom or None})
    return S._load_compte(cle)


@app.post("/series/{serie_id}/cible", tags=["réglages"])
def definir_cible(serie_id: str, body: DefinirCible, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    if body.cible is not None and body.cible not in S.CIBLES:
        raise HTTPException(400, f"Cible inconnue : {body.cible}")
    serie["cible"] = body.cible
    S._save(serie)
    return {"cible": serie["cible"]}


# ── Langue de travail ────────────────────────────────────────────
@app.get("/langues", tags=["réglages"])
def lister_langues(_cle: str = Depends(cle_api)):
    return [{"code": c, "label": label} for c, (_nom, label) in S.LANGUES.items()]


@app.post("/series/{serie_id}/langue", tags=["réglages"])
def definir_langue(serie_id: str, body: DefinirLangue, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    if body.langue not in S.LANGUES:
        raise HTTPException(400, f"Langue inconnue : {body.langue}")
    serie["langue"] = body.langue
    S._save(serie)
    return {"langue": serie["langue"]}


# ── Profils lecteurs (par âge, S231) ──────────────────────────────
@app.get("/profils", tags=["profils"])
def lister_profils(cle: str = Depends(cle_api)):
    out = []
    for fn in os.listdir(S.PROFILS_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(S.PROFILS_DIR, fn), encoding="utf-8") as f:
                p = json.load(f)
        except Exception:
            continue
        if p.get("cree_par") != cle:
            continue
        out.append(p)
    out.sort(key=lambda x: x.get("cree_le") or "")
    return out


@app.post("/profils", tags=["profils"])
def creer_profil(body: CreerProfil, cle: str = Depends(cle_api)):
    if body.cible not in S.CIBLES:
        raise HTTPException(400, f"Cible inconnue : {body.cible}")
    nom = body.nom.strip()
    if not nom:
        raise HTTPException(422, "Le nom du profil ne peut pas être vide.")
    profil = {
        "id": uuid.uuid4().hex, "nom": nom, "cible": body.cible,
        "cree_par": cle, "cree_le": datetime.now(timezone.utc).isoformat(),
    }
    S._save_profil(profil)
    return profil


@app.patch("/profils/{profil_id}", tags=["profils"])
def modifier_profil(profil_id: str, body: MajProfil, cle: str = Depends(cle_api)):
    profil = _profil_de(profil_id, cle)
    if body.nom is not None:
        nom = body.nom.strip()
        if not nom:
            raise HTTPException(422, "Le nom du profil ne peut pas être vide.")
        profil["nom"] = nom
    if body.cible is not None:
        if body.cible not in S.CIBLES:
            raise HTTPException(400, f"Cible inconnue : {body.cible}")
        profil["cible"] = body.cible
    S._save_profil(profil)
    return profil


@app.delete("/profils/{profil_id}", status_code=204, tags=["profils"])
def supprimer_profil(profil_id: str, cle: str = Depends(cle_api)):
    _profil_de(profil_id, cle)  # 404 si absent ou pas à `cle` — jamais de suppression à l'aveugle
    p = S._profil_path(profil_id)
    if os.path.exists(p):
        os.remove(p)
    return None


@app.get("/series/{serie_id}/episodes/{n}/adapte", tags=["profils"])
async def episode_adapte(serie_id: str, n: int, profil_id: str, cle: str = Depends(cle_api)):
    """Texte d'un chapitre adapté au registre du profil (jamais stocké, recalculé à chaque
    appel — même politique que la traduction au rendu)."""
    serie = charger(serie_id, cle)
    profil = _profil_de(profil_id, cle)
    ep = next((e for e in serie.get("episodes", []) if e.get("n") == n), None)
    if not ep:
        raise HTTPException(404, f"Épisode {n} introuvable.")
    texte = ep.get("script_balise") or ep.get("script_brut") or ""
    adapte, ok = await S._adapter_cible(texte, profil["cible"], serie.get("langue"))
    return {"texte": adapte, "adapte": ok, "cible": profil["cible"], "profil_id": profil_id}


# ── Journal d'écoute/choix (V1 saga familiale) ────────────────────
@app.get("/profils/{profil_id}/journal", tags=["journal"])
def journal_profil(profil_id: str, cle: str = Depends(cle_api)):
    _profil_de(profil_id, cle)  # 404 si absent ou pas à `cle` (même garde que /profils)
    return {"evenements": S._load_journal(profil_id)}


@app.post("/series/{serie_id}/episodes/{n}/marquer-lu", tags=["journal"])
def marquer_lu(serie_id: str, n: int, body: MarquerLu, cle: str = Depends(cle_api)):
    """Journalise qu'un profil a écouté/lu ce chapitre. Endpoint DÉDIÉ (pas d'effet de
    bord sur `episode_adapte`, qui sert aussi à la prévisualisation du parent — cf.
    spec 2.2, auto-revue)."""
    serie = charger(serie_id, cle)
    _profil_de(body.profil_id, cle)
    ep = next((e for e in serie.get("episodes", []) if e.get("n") == n), None)
    if not ep:
        raise HTTPException(404, f"Chapitre {n} introuvable.")
    return S._ajouter_evenement(body.profil_id, {
        "type": "chapitre_lu", "serie_id": serie_id, "serie_titre": serie.get("titre"),
        "episode_n": n, "noeud_id": None, "choix": None,
    })


# ── Distribution (personnages structurés) ────────────────────────
@app.get("/voix", tags=["distribution"])
async def voix_disponibles(langue: str = "fr", _cle: str = Depends(cle_api)):
    code = S._norm_langue(langue)
    return {"langue": code, "voix": await S._voix_pool(code)}


@app.get("/series/{serie_id}/personnages", tags=["distribution"])
def lister_personnages(serie_id: str, cle: str = Depends(cle_api)):
    return charger(serie_id, cle).get("personnages") or []


@app.post("/series/{serie_id}/personnages", tags=["distribution"])
def creer_perso(serie_id: str, body: CreerPerso, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    if not (body.nom or "").strip():
        raise HTTPException(400, "Le personnage doit avoir un nom.")
    serie.setdefault("personnages", [])
    pid = S._next_id("p", {p["id"] for p in serie["personnages"]})
    nom = body.nom.strip()
    perso = {
        "id": pid, "nom": nom, "nom_naissance": nom,
        "role": (body.role or "").strip(),
        "description": (body.description or "").strip(),
        "voix": {k: v for k, v in (body.voix or {}).items() if v} if isinstance(body.voix, dict) else {},
    }
    serie["personnages"].append(perso)
    S._save(serie)
    return perso


@app.post("/series/{serie_id}/personnages/importer", tags=["distribution"])
def importer_perso(serie_id: str, body: ImporterPerso, cle: str = Depends(cle_api)):
    """Connexion Personnages→Studio (push iframe) : importe une fiche holistique comme rôle.

    Garde toujours les deux noms : `nom_naissance` (cosmique, figé) + `nom` (de scène)."""
    serie = charger(serie_id, cle)
    if not (body.nom or "").strip():
        raise HTTPException(400, "Le personnage doit avoir un nom.")
    serie.setdefault("personnages", [])
    pid = S._next_id("p", {p["id"] for p in serie["personnages"]})
    nom = body.nom.strip()
    perso = {
        "id": pid, "nom": nom,
        "nom_naissance": (body.nom_naissance or nom).strip(),
        "role": (body.role or "").strip(),
        "description": (body.description or "").strip(),
        "voix": {},
        "archetype": (body.archetype or "").strip(),
        "empreinte": [str(x) for x in (body.empreinte or [])][:20],
        "source": body.source or "personnages",
    }
    serie["personnages"].append(perso)
    S._save(serie)
    return perso


@app.get("/personnages-holistiques", tags=["distribution"])
async def personnages_holistiques(_cle: str = Depends(cle_api)):
    """Liste « mes personnages créés » : les fiches ENREGISTRÉES dans l'atelier holistique
    (brique 5900), pour les piocher dans la distribution. Repli honnête si la brique est
    injoignable (`disponible: false` au lieu d'une erreur, pour ne pas casser la vue)."""
    fiches = await composition.lister_fiches_holistiques()
    if fiches is None:
        return {"disponible": False, "fiches": [], "atelier": composition.PERSONNAGES_URL}
    return {"disponible": True, "fiches": fiches}


@app.post("/series/{serie_id}/personnages/importer-fiche", tags=["distribution"])
async def importer_fiche(serie_id: str, body: ImporterFiche, cle: str = Depends(cle_api)):
    """Ajoute à la série un personnage créé dans l'atelier holistique, avec un nom de scène.

    Le Studio va lire la fiche complète (5900) par son id ; on garde le nom cosmique
    d'origine (`nom_naissance`) et on dérive archétype/empreinte/description du portrait."""
    serie = charger(serie_id, cle)
    fiche = await composition.lire_fiche_holistique(body.fiche_id)
    if not fiche:
        raise HTTPException(502, "Fiche introuvable ou atelier Personnages injoignable.")
    donnees = fiche.get("donnees") or {}
    portrait = donnees.get("portrait") or {}
    nom_naissance = (fiche.get("nom_naissance") or fiche.get("nom") or "Personnage").strip()
    nom = (body.nom or "").strip() or (fiche.get("nom") or nom_naissance).strip()
    serie.setdefault("personnages", [])
    pid = S._next_id("p", {p["id"] for p in serie["personnages"]})
    perso = {
        "id": pid, "nom": nom, "nom_naissance": nom_naissance,
        "role": "",
        "description": _description_portrait(portrait),
        "voix": {},
        "archetype": (portrait.get("archetype") or "").strip(),
        "empreinte": _empreinte_texte(donnees.get("empreinte") or []),
        "source": "personnages",
    }
    serie["personnages"].append(perso)
    S._save(serie)
    return perso


@app.post("/series/{serie_id}/personnages/{pid}/portrait", tags=["distribution"])
async def portrait_perso(serie_id: str, pid: str, cle: str = Depends(cle_api)):
    """Connexion Personnages→images : génère le PORTRAIT d'un personnage de la distribution."""
    serie = charger(serie_id, cle)
    perso = next((p for p in serie.get("personnages", []) if p["id"] == pid), None)
    if not perso:
        raise HTTPException(404, "Personnage introuvable")
    res = await S._appeler_images("/portrait", {"fiche": {
        "nom": perso.get("nom"), "role": perso.get("role"),
        "description": perso.get("description"), "archetype": perso.get("archetype"),
        "empreinte": perso.get("empreinte"),
    }})
    if not res:
        raise HTTPException(502, f"Brique images injoignable ({S.IMAGES_URL}).")
    perso["portrait_url"] = res["url"]
    perso["portrait_placeholder"] = bool(res.get("place_holder"))
    S._save(serie)
    return {"portrait_url": res["url"], "place_holder": res.get("place_holder"),
            "prompt_visuel": res.get("prompt_visuel"), "perso": perso}


@app.post("/series/{serie_id}/personnages/{pid}/animer", tags=["distribution"])
async def animer_perso(serie_id: str, pid: str, cle: str = Depends(cle_api)):
    """Connexion Personnages→video : ANIME le portrait d'un personnage (clip image→vidéo).

    On part du portrait déjà produit (s'il existe) comme image de départ ; sinon text→vidéo
    à partir de la fiche seule. Repli honnête si la brique video est injoignable/non branchée."""
    serie = charger(serie_id, cle)
    perso = next((p for p in serie.get("personnages", []) if p["id"] == pid), None)
    if not perso:
        raise HTTPException(404, "Personnage introuvable")
    res = await S._appeler_video("/animer", {
        "fiche": {
            "nom": perso.get("nom"), "role": perso.get("role"),
            "description": perso.get("description"), "archetype": perso.get("archetype"),
            "empreinte": perso.get("empreinte"),
        },
        "image_url": perso.get("portrait_url") or None,
    })
    if not res:
        raise HTTPException(502, f"Brique video injoignable ({S.VIDEO_URL}).")
    perso["clip_url"] = res["url"]
    perso["clip_placeholder"] = bool(res.get("place_holder"))
    S._save(serie)
    return {"clip_url": res["url"], "place_holder": res.get("place_holder"),
            "prompt_visuel": res.get("prompt_visuel"), "perso": perso}


@app.patch("/series/{serie_id}/personnages/{pid}", tags=["distribution"])
def maj_perso(serie_id: str, pid: str, body: MajPerso, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    perso = next((p for p in serie.get("personnages", []) if p["id"] == pid), None)
    if not perso:
        raise HTTPException(404, "Personnage introuvable")
    # Fige le nom d'origine avant un éventuel renommage (persos créés avant cette mémoire).
    perso.setdefault("nom_naissance", perso.get("nom", ""))
    if body.nom is not None:
        perso["nom"] = body.nom.strip()
    if body.nom_naissance is not None:
        perso["nom_naissance"] = body.nom_naissance.strip()
    if body.role is not None:
        perso["role"] = body.role.strip()
    if body.description is not None:
        perso["description"] = body.description.strip()
    if isinstance(body.voix, dict):
        perso.setdefault("voix", {}).update({k: v for k, v in body.voix.items() if v})
    S._save(serie)
    return perso


@app.delete("/series/{serie_id}/personnages/{pid}", status_code=204, tags=["distribution"])
def supprimer_perso(serie_id: str, pid: str, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    serie["personnages"] = [p for p in serie.get("personnages", []) if p["id"] != pid]
    S._save(serie)
    return None


@app.post("/series/{serie_id}/personnages/proposer", tags=["distribution"])
async def proposer_distribution(serie_id: str, body: ProposerDistribution,
                                cle: str = Depends(cle_api)):
    """Distribution cohérente avec la bible (rien stocké).

    Composée : déléguée à la brique personnages (5900, le Directeur de Casting maison du
    produit) ; repli HONNÊTE sur le Directeur de Casting INTERNALISÉ si la brique est
    absente. `source` indique laquelle a répondu."""
    serie = charger(serie_id, cle)
    combien = max(2, min(int(body.combien or 4), 8))
    deja = S._distribution_texte(serie) or "(distribution vide — c'est le tout début)\n\n"
    idee = f"\n\nPiste de l'utilisateur à intégrer : « {body.mon_idee} »." if body.mon_idee else ""

    # 1) Brique personnages (5900) — le casting est SON métier.
    langue_nom = S.LANGUES[S._norm_langue(serie.get("langue"))][0]
    premisse = (f"{S._consigne_cible(serie)}Série « {serie['titre']} ». "
                f"Bible :\n{S._bible_texte(serie)}{idee}")
    via_brique = await composition.proposer_distribution(premisse, langue_nom, combien, deja)
    if via_brique:
        return {"source": "personnages", "agent": "Directeur de Casting",
                "avatar": "🎭", "personnages": via_brique}

    # 2) Repli : Directeur de Casting INTERNALISÉ (socle S51).
    try:
        ag = _agent("Casting")
    except HTTPException:
        ag = _agent("Showrunner")
    tache = (
        f"{S._consigne_langue(serie)}{S._consigne_cible(serie)}"
        f"Série « {serie['titre']} ». Bible :\n{S._bible_texte(serie)}\n\n"
        f"Distribution déjà retenue :\n{deja}"
        f"Propose {combien} personnages COHÉRENTS et complémentaires (héros, allié, "
        f"antagoniste, second rôle…), distincts de ceux déjà retenus.{idee}\n\n"
        'Réponds UNIQUEMENT par un tableau JSON [{"nom":"...","role":"...","description":"..."}], '
        "sans aucun texte autour."
    )
    brut = await agents.demander(ag, tache)
    options = S._extraire_json(brut) or []
    propositions = [
        {"nom": str(o.get("nom") or "").strip(),
         "role": str(o.get("role") or "").strip(),
         "description": str(o.get("description") or "").strip()}
        for o in options if isinstance(o, dict) and (o.get("nom") or "").strip()
    ]
    return {"source": "studio", "agent": ag.nom, "avatar": ag.avatar_emoji,
            "personnages": propositions}


# ── Cycles & Tomes (structure « livre ») ─────────────────────────
def _cycle(serie: dict, cycle_id: str) -> dict:
    c = next((c for c in serie["cycles"] if c["id"] == cycle_id), None)
    if not c:
        raise HTTPException(404, "Cycle introuvable")
    return c


@app.post("/series/{serie_id}/cycles", tags=["structure"])
def creer_cycle(serie_id: str, body: CreerCycle, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    cid = S._next_id("c", {c["id"] for c in serie["cycles"]})
    numero = len(serie["cycles"]) + 1
    cycle = {"id": cid, "numero": numero, "titre": body.titre or f"Cycle {numero}",
             "resume": body.resume or "", "tomes": []}
    serie["cycles"].append(cycle)
    S._save(serie)
    return cycle


@app.patch("/series/{serie_id}/cycles/{cycle_id}", tags=["structure"])
def renommer_cycle(serie_id: str, cycle_id: str, body: Renommer, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    cycle = _cycle(serie, cycle_id)
    if body.titre is not None:
        cycle["titre"] = body.titre
    if body.resume is not None:
        cycle["resume"] = body.resume
    S._save(serie)
    return cycle


@app.delete("/series/{serie_id}/cycles/{cycle_id}", status_code=204, tags=["structure"])
def supprimer_cycle(serie_id: str, cycle_id: str, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    cycle = _cycle(serie, cycle_id)
    if len(serie["cycles"]) == 1:
        raise HTTPException(409, "Impossible de supprimer le dernier cycle.")
    tomes_du_cycle = {t["id"] for t in cycle.get("tomes", [])}
    if any(ep.get("tome_id") in tomes_du_cycle for ep in serie.get("episodes", [])):
        raise HTTPException(409, "Ce cycle contient des chapitres — déplace ou supprime-les d'abord.")
    serie["cycles"] = [c for c in serie["cycles"] if c["id"] != cycle_id]
    S._normaliser(serie)
    S._save(serie)
    return None


@app.post("/series/{serie_id}/cycles/{cycle_id}/tomes", tags=["structure"])
def creer_tome(serie_id: str, cycle_id: str, body: CreerTome, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    cycle = _cycle(serie, cycle_id)
    tid = S._next_id("t", {t["id"] for t in S._tous_tomes(serie)})
    numero = len(cycle.setdefault("tomes", [])) + 1
    tome = {"id": tid, "numero": numero, "titre": body.titre or f"Tome {numero}",
            "resume": body.resume or "", "statut": "en_cours"}
    cycle["tomes"].append(tome)
    serie["tome_actif"] = tid
    S._save(serie)
    return {"tome": tome, "tome_actif": serie["tome_actif"]}


@app.patch("/series/{serie_id}/tomes/{tome_id}", tags=["structure"])
def renommer_tome(serie_id: str, tome_id: str, body: Renommer, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    tome = next((t for t in S._tous_tomes(serie) if t["id"] == tome_id), None)
    if not tome:
        raise HTTPException(404, "Tome introuvable")
    if body.titre is not None:
        tome["titre"] = body.titre
    if body.resume is not None:
        tome["resume"] = body.resume
    if body.statut is not None:
        if body.statut not in ("en_cours", "termine"):
            raise HTTPException(422, "statut doit être 'en_cours' ou 'termine'.")
        tome["statut"] = body.statut
    S._save(serie)
    return tome


@app.delete("/series/{serie_id}/tomes/{tome_id}", status_code=204, tags=["structure"])
def supprimer_tome(serie_id: str, tome_id: str, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    if len(S._tous_tomes(serie)) == 1:
        raise HTTPException(409, "Impossible de supprimer le dernier tome.")
    if any(ep.get("tome_id") == tome_id for ep in serie.get("episodes", [])):
        raise HTTPException(409, "Ce tome contient des chapitres — déplace ou supprime-les d'abord.")
    for c in serie["cycles"]:
        c["tomes"] = [t for t in c.get("tomes", []) if t["id"] != tome_id]
    S._normaliser(serie)
    S._save(serie)
    return None


@app.post("/series/{serie_id}/tome-actif", tags=["structure"])
def definir_tome_actif(serie_id: str, body: TomeActif, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    if body.tome_id not in {t["id"] for t in S._tous_tomes(serie)}:
        raise HTTPException(404, "Tome introuvable")
    serie["tome_actif"] = body.tome_id
    S._save(serie)
    return {"tome_actif": serie["tome_actif"]}


@app.post("/series/{serie_id}/tomes/{tome_id}/bilan", tags=["structure"])
async def bilan_tome(serie_id: str, tome_id: str, cle: str = Depends(cle_api)):
    """« Le tome est-il fini normalement ? » — arc prévu vs chapitres écrits + canon."""
    serie = charger(serie_id, cle)
    cycle, tome = S._tome_de(serie, tome_id)
    if not tome:
        raise HTTPException(404, "Tome introuvable")

    struct = S._bilan_structurel(serie, tome)
    chapitres = S._chapitres_du_tome(serie, tome_id)
    resultat = {
        "tome_id": tome_id, "titre": tome.get("titre"),
        "statut": struct["statut"], "structure": struct,
        "fini": None, "taux": None, "fils_non_resolus": [], "verdict": "",
    }

    if not struct["a_un_arc"]:
        resultat["verdict"] = ("Aucun arc n'est fixé pour ce tome (champ « resume » vide) : "
                               "impossible de juger s'il est résolu. Renseigne l'arc prévu d'abord.")
        return resultat
    if not chapitres:
        resultat["verdict"] = "Aucun chapitre n'est encore écrit dans ce tome."
        resultat["fini"] = False
        return resultat

    recap = "\n".join(f"- Chapitre {c.get('n')} : {c.get('consigne', '')}" for c in chapitres)
    fin = (chapitres[-1].get("script_brut") or chapitres[-1].get("script_balise") or "")[-1500:]
    acquis = (serie.get("canon") or {}).get("acquis") or []
    try:
        brut = await agents.demander(_agent("Showrunner"),
            f"{S._consigne_langue(serie)}"
            f"Arc PRÉVU du tome « {tome.get('titre')} » :\n{tome.get('resume')}\n\n"
            f"Chapitres écrits dans ce tome :\n{recap}\n\n"
            + ("Faits déjà acquis dans l'histoire :\n" + "\n".join(f"- {a}" for a in acquis) + "\n\n"
               if acquis else "")
            + f"Fin du dernier chapitre :\n{fin}\n\n"
            "L'arc prévu de ce tome est-il RÉSOLU ? Réponds UNIQUEMENT un objet JSON : "
            '{"fini": true|false, "taux": 0-100, "fils_non_resolus": ["..."], '
            '"verdict": "une phrase claire"}')
        obj = S._extraire_obj(brut) or {}
        resultat["fini"] = bool(obj.get("fini")) if obj.get("fini") is not None else None
        if isinstance(obj.get("taux"), (int, float)):
            resultat["taux"] = max(0, min(100, int(obj["taux"])))
        resultat["fils_non_resolus"] = [str(x) for x in (obj.get("fils_non_resolus") or [])][:10]
        resultat["verdict"] = str(obj.get("verdict") or "").strip()
    except Exception as e:  # noqa: BLE001
        resultat["verdict"] = (f"Verdict narratif indisponible (Showrunner injoignable : "
                               f"{str(e)[:120]}). Bilan structurel seul ci-dessus.")
    return resultat


@app.get("/series/{serie_id}/livre", tags=["structure"])
def livre(serie_id: str, tome_id: Optional[str] = None, cycle_id: Optional[str] = None,
          cle: str = Depends(cle_api)):
    """Compile la version « vrai livre » : texte narratif sans balises son (Markdown)."""
    serie = charger(serie_id, cle)
    par_tome: dict = {}
    for ep in serie.get("episodes", []):
        par_tome.setdefault(ep.get("tome_id"), []).append(ep)
    for v in par_tome.values():
        v.sort(key=lambda e: e.get("n", 0))

    lignes = [f"# {serie['titre']}"]
    nb_chapitres = 0
    for c in serie["cycles"]:
        if cycle_id and c["id"] != cycle_id:
            continue
        bloc = [f"\n## {c['titre']}"]
        cycle_rempli = False
        for t in c.get("tomes", []):
            if tome_id and t["id"] != tome_id:
                continue
            chapitres = par_tome.get(t["id"], [])
            if not chapitres:
                continue
            cycle_rempli = True
            bloc.append(f"\n### {t['titre']}")
            for i, ep in enumerate(chapitres, 1):
                titre_ch = f"Chapitre {i}"
                if ep.get("titre"):
                    titre_ch += f" — {ep['titre']}"
                bloc.append(f"\n#### {titre_ch}\n\n{S._texte_livre(ep)}")
                nb_chapitres += 1
        if cycle_rempli:
            lignes.extend(bloc)

    return {"titre": serie["titre"], "format": "markdown",
            "chapitres": nb_chapitres, "texte": "\n".join(lignes)}


# ── Co-création de la bible ──────────────────────────────────────
@app.post("/series/{serie_id}/proposer", tags=["bible"])
async def proposer(serie_id: str, body: Proposer, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    role = S.DIMENSION_AGENT.get(body.dimension.lower(), "Showrunner")
    ag = _agent(role)

    consigne_user = ""
    if body.mon_idee:
        consigne_user = (
            f"\n\nL'utilisateur PROPOSE de son côté : « {body.mon_idee} ». "
            "Tiens-en compte : rebondis dessus, propose des variantes ou un mélange, "
            "et n'hésite pas à enrichir son idée."
        )

    tache = (
        f"{S._consigne_langue(serie)}{S._consigne_cible(serie)}"
        f"On co-crée une série audio interactive intitulée « {serie['titre']} ».\n"
        f"Bible actuelle :\n{S._bible_texte(serie)}\n\n"
        f"Propose 3 options DISTINCTES et inspirantes pour la dimension : « {body.dimension} »."
        f"{consigne_user}\n\n"
        "Réponds UNIQUEMENT par un tableau JSON, sans aucun texte autour, au format : "
        '[{"titre": "...", "description": "..."}]'
    )
    brut = await agents.demander(ag, tache)
    options = S._extraire_json(brut)
    if not options:
        options = [{"titre": "Proposition", "description": brut.strip()[:1500]}]
    return {"dimension": body.dimension, "agent": ag.nom, "avatar": ag.avatar_emoji,
            "options": options}


@app.post("/series/{serie_id}/decider", tags=["bible"])
def decider(serie_id: str, body: Decider, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    serie["bible"][body.dimension.lower()] = body.choix
    S._save(serie)
    faits = set(serie["bible"].keys())
    suite = next((d for d in S.ORDRE if d not in faits), None)
    return {"bible": serie["bible"], "prochaine_etape": suite}


# ── Production d'épisodes ────────────────────────────────────────
@app.post("/series/{serie_id}/episode", tags=["production"])
async def faire_episode(serie_id: str, body: FaireEpisode, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    scenariste = _agent("Scénariste")
    doctor     = _agent("Script Doctor")

    deja = serie.get("episodes", [])
    numero = len(deja) + 1
    if body.branche:
        consigne = body.branche
    elif numero == 1:
        consigne = serie["bible"].get("choix") or serie["bible"].get("intrigue") \
            or "le premier épisode de la série"
    else:
        consigne = f"l'épisode {numero}, suite directe de l'épisode {numero - 1}"

    finale = S._est_fin_episode(serie, numero)
    script = await agents.demander(scenariste,
        S._tache_scenariste(serie, numero, consigne, S._recap_episodes(deja), finale=finale))
    balise = await agents.demander(doctor, S._tache_doctor(serie, script))

    episode = {
        "n": numero,
        "tome_id": serie.get("tome_actif"),
        "consigne": consigne,
        "script_brut": script,
        "script_balise": balise,
        "fin_episode": finale,
        "anglicismes": S._anglicismes(balise, serie),
        "le": datetime.now(timezone.utc).isoformat(),
    }
    episode["valeur_suggeree"] = await S._suggerer_valeur(script)
    episode["valeur"] = episode["valeur_suggeree"]
    serie["episodes"].append(episode)
    await S._recolter_canon(serie, script)
    S._save(serie)
    return episode


@app.post("/series/{serie_id}/episode/{n}/couverture", tags=["production"])
async def couverture_episode(serie_id: str, n: int, cle: str = Depends(cle_api)):
    """Connexion Studio→images : génère la COUVERTURE d'un épisode."""
    serie = charger(serie_id, cle)
    ep = next((e for e in serie.get("episodes", []) if e.get("n") == n), None)
    if not ep:
        raise HTTPException(404, f"Chapitre {n} introuvable.")
    synopsis = (ep.get("consigne") or "")
    extrait = (ep.get("script_brut") or "")[:400]
    res = await S._appeler_images("/couverture", {
        "titre": f"{serie['titre']} — chapitre {n}",
        "synopsis": f"{synopsis}. {extrait}".strip(". "),
        "personnages": [{"nom": p.get("nom")} for p in (serie.get("personnages") or [])],
    })
    if not res:
        raise HTTPException(502, f"Brique images injoignable ({S.IMAGES_URL}).")
    ep["cover_url"] = res["url"]
    ep["cover_placeholder"] = bool(res.get("place_holder"))
    S._save(serie)
    return {"cover_url": res["url"], "place_holder": res.get("place_holder"),
            "prompt_visuel": res.get("prompt_visuel"), "n": n}


@app.post("/series/{serie_id}/episode/{n}/teaser", tags=["production"])
async def teaser_episode(serie_id: str, n: int, cle: str = Depends(cle_api)):
    """Connexion Studio→video : génère la BANDE-ANNONCE (clip teaser) d'un épisode.

    Repli honnête si la brique video est injoignable/non branchée (placeholder annoncé)."""
    serie = charger(serie_id, cle)
    ep = next((e for e in serie.get("episodes", []) if e.get("n") == n), None)
    if not ep:
        raise HTTPException(404, f"Chapitre {n} introuvable.")
    synopsis = (ep.get("consigne") or "")
    extrait = (ep.get("script_brut") or "")[:400]
    res = await S._appeler_video("/teaser", {
        "titre": f"{serie['titre']} — chapitre {n}",
        "synopsis": f"{synopsis}. {extrait}".strip(". "),
        "personnages": [{"nom": p.get("nom")} for p in (serie.get("personnages") or [])],
    })
    if not res:
        raise HTTPException(502, f"Brique video injoignable ({S.VIDEO_URL}).")
    ep["teaser_url"] = res["url"]
    ep["teaser_placeholder"] = bool(res.get("place_holder"))
    S._save(serie)
    return {"teaser_url": res["url"], "place_holder": res.get("place_holder"),
            "prompt_visuel": res.get("prompt_visuel"), "n": n}


@app.post("/series/{serie_id}/audio", tags=["production"])
async def produire_audio(serie_id: str, body: FaireEpisode, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    if not serie.get("episodes"):
        raise HTTPException(400, "Aucun épisode à sonoriser — génère d'abord un épisode.")
    ep = next((e for e in serie["episodes"] if e.get("n") == body.n), None) if body.n \
        else serie["episodes"][-1]
    if not ep:
        raise HTTPException(404, f"Épisode {body.n} introuvable.")
    script = ep.get("script_balise") or ep.get("script_brut") or ""

    adapte_ok = None  # non applicable : pas de profil demandé, pas de succès/échec à rapporter
    if body.profil_id:
        profil = _profil_de(body.profil_id, cle)
        script, adapte_ok = await S._adapter_cible(script, profil["cible"], serie.get("langue"))

    brut = await agents._gateway_answer(
        agents.GATEWAY_URL, agents.GATEWAY_MODEL,
        "Tu structures des scripts audio en JSON, sans rien inventer.",
        "Convertis ce script en un tableau JSON [{\"perso\":\"NOM\",\"texte\":\"...\"}] : une entrée "
        "par réplique PARLÉE, dans l'ordre. Ignore les didascalies entre parenthèses et les balises "
        "[SFX]/[AMBIANCE]/[MUSIQUE]. 'perso' = qui parle (ou 'NARRATEUR'). Réponds UNIQUEMENT le JSON.\n\n"
        + script[:3500])
    repliques = S._extraire_json(brut) or []
    if not repliques:
        raise HTTPException(422, "Le script n'a pas pu être découpé en répliques.")

    audibles = []
    for r in repliques:
        perso = (r.get("perso") or "NARRATEUR").strip().upper()
        texte = (r.get("texte") or "").strip()
        if texte:
            audibles.append((perso, texte))
    if not audibles:
        raise HTTPException(422, "Le script n'a pas pu être découpé en répliques.")

    langue_travail = S._norm_langue(serie.get("langue"))
    vers = S._norm_langue(body.langue_sortie or serie.get("langue"))
    traduit = False
    if vers != langue_travail:
        textes, traduit = await S._traduire([t for _, t in audibles], S.LANGUES[vers][0])
        audibles = [(p, textes[i]) for i, (p, _) in enumerate(audibles)]

    pool = await S._voix_pool(vers)
    casting, casting_source = await _casting_stable(serie, vers, audibles, pool)
    segments = [{"voix": casting[perso], "texte": texte} for perso, texte in audibles]

    # Rendu scopé au profil : sans ça, produire l'audio du profil « Fille » puis « Fils » sur le
    # MÊME chapitre écrase le même fichier .mp3 côté brique voix (episode_id identique). On NE
    # scope PAS aussi par `vers` (langue de sortie) — même classe de bug côté langue, mais
    # pré-existante et hors périmètre de cette revue (S231 revue finale, C1).
    suffixe_profil = f"-p{body.profil_id}" if body.profil_id else ""
    episode_id_render = f"{serie_id}-ep{ep['n']}{suffixe_profil}"

    try:
        async with S.httpx.AsyncClient(timeout=180) as c:
            r = await c.post(f"{S.VOIX_URL}/rendre",
                             json={"episode_id": episode_id_render,
                                   "segments": segments, "langue": vers})
            r.raise_for_status()
            res = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Service voix injoignable ({S.VOIX_URL}) : {str(e)[:150]}")

    cle_stockage = body.profil_id or "reference"
    audios = ep.setdefault("audios", {})
    audios[cle_stockage] = {
        "url": res.get("url"), "duree": res.get("duree"),
        "casting": casting, "casting_source": casting_source,
        "langue_audio": vers, "profil_id": body.profil_id,
    }
    # Rétrocompat : les champs plats de l'épisode restent le rendu de RÉFÉRENCE uniquement —
    # jamais écrasés par un rendu profil-spécifique (S231 revue finale, C1).
    if not body.profil_id:
        ep["audio_url"] = res.get("url")
        ep["duree"] = res.get("duree")
        ep["casting"] = casting
        ep["casting_source"] = casting_source
        ep["langue_audio"] = vers
    S._save(serie)
    return {"url": res.get("url"), "duree": res.get("duree"),
            "casting": casting, "casting_source": casting_source,
            "repliques": len(segments),
            "langue_sortie": vers, "traduit": traduit,
            "profil_id": body.profil_id,
            "adapte": adapte_ok if body.profil_id else None}


async def _casting_stable(serie: dict, langue: str, audibles: list, pool: list) -> tuple:
    """Casting vocal : délègue à la brique personnages (5900), repli interne HONNÊTE.

    Retourne (casting {NOM→voix}, source) où source = "personnages" (brique composée) ou
    "studio" (logique internalisée S51). Dans les deux cas les voix figées sont persistées
    dans la série pour rester stables d'un épisode à l'autre."""
    intervenants = [perso for perso, _ in audibles]
    res = await composition.caster(serie.get("personnages") or [], langue, intervenants, pool)
    if res is not None:
        casting, enrichis = res
        if composition.fusionner_voix(serie, enrichis):
            S._save(serie)
        # Un intervenant absent du casting renvoyé (ex. figurant) : on complète au repli interne.
        if all(p in casting for p in intervenants):
            return casting, "personnages"
    return S._caster(serie, langue, audibles, pool), "studio"


@app.post("/series/{serie_id}/express", tags=["production"])
async def episode_express(serie_id: str, body: Express, cle: str = Depends(cle_api)):
    """Le Showrunner décide lui-même les briques manquantes, puis on produit l'épisode."""
    serie = charger(serie_id, cle)
    showrunner = _agent("Showrunner")
    for dim in S.ORDRE:
        if dim in serie["bible"]:
            continue
        seed = f" Tiens compte de l'idée de départ : « {body.idee} »." if (body.idee and not serie["bible"]) else ""
        rep = await agents.demander(
            showrunner,
            f"{S._consigne_langue(serie)}{S._consigne_cible(serie)}"
            f"Série « {serie['titre']} ». Bible actuelle :\n{S._bible_texte(serie)}\n\n"
            f"Décide toi-même la dimension « {dim} » en 2-3 phrases concises et cohérentes.{seed} "
            "Réponds directement le contenu, sans préambule ni liste d'options.")
        serie["bible"][dim] = rep.strip()
        S._save(serie)

    scenariste = _agent("Scénariste")
    doctor = _agent("Script Doctor")
    deja = serie.get("episodes", [])
    numero = len(deja) + 1
    consigne = serie["bible"].get("choix") or serie["bible"].get("intrigue") or "le premier épisode" \
        if numero == 1 else f"l'épisode {numero}, suite directe de l'épisode {numero - 1}"
    finale = S._est_fin_episode(serie, numero)
    script = await agents.demander(
        scenariste, S._tache_scenariste(serie, numero, consigne, S._recap_episodes(deja), finale=finale))
    balise = await agents.demander(doctor, S._tache_doctor(serie, script))
    episode = {
        "n": numero, "tome_id": serie.get("tome_actif"), "consigne": consigne,
        "script_brut": script, "script_balise": balise, "express": True,
        "fin_episode": finale,
        "anglicismes": S._anglicismes(balise, serie),
        "le": datetime.now(timezone.utc).isoformat(),
    }
    episode["valeur_suggeree"] = await S._suggerer_valeur(script)
    episode["valeur"] = episode["valeur_suggeree"]
    serie["episodes"].append(episode)
    await S._recolter_canon(serie, script)
    S._save(serie)
    return {"bible": serie["bible"], "episode": episode}


# ── Arbre des choix ──────────────────────────────────────────────
@app.get("/series/{serie_id}/arbre/{noeud_id}/lire", tags=["arbre"])
async def lire_noeud(serie_id: str, noeud_id: str, profil_id: str, cle: str = Depends(cle_api)):
    """Lecture SEULE d'un nœud pour un profil (mode enfant) : texte adapté au registre,
    audio si déjà produit pour ce profil, et pour chaque choix s'il mène déjà à une
    branche écrite (le front désactive les autres). N'écrit rien, ne journalise rien."""
    serie = charger(serie_id, cle)
    profil = _profil_de(profil_id, cle)
    arbre = serie.get("arbre")
    if not arbre:
        raise HTTPException(404, "Aucun arbre pour cette série.")
    noeud, _chemin = S._trouver_noeud(arbre, noeud_id)
    if not noeud or not noeud.get("script"):
        raise HTTPException(404, "Ce chapitre n'est pas encore écrit.")
    ep = next((e for e in serie.get("episodes", []) if e.get("n") == noeud.get("episode_n")), None)
    texte = (ep.get("script_brut") if ep else noeud["script"]) or ""
    adapte, ok = await S._adapter_cible(texte, profil["cible"], serie.get("langue"))
    audio = (ep.get("audios") or {}).get(profil_id) if ep else None
    choix_ecrits = {e["choix"]: bool(e["noeud"].get("script")) for e in noeud.get("enfants", [])}
    choix = [{"texte": c, "ecrit": choix_ecrits.get(c, False)} for c in noeud.get("choix", [])]
    return {
        "noeud_id": noeud_id, "synopsis": noeud.get("synopsis"), "texte": adapte,
        "adapte": ok, "audio_url": audio.get("url") if audio else None,
        "choix": choix, "episode_n": noeud.get("episode_n"),
    }


class Choisir(BaseModel):
    profil_id: str
    choix: str


@app.post("/series/{serie_id}/arbre/{noeud_id}/choisir", tags=["arbre"])
def choisir_branche(serie_id: str, noeud_id: str, body: Choisir, cle: str = Depends(cle_api)):
    """Fait progresser un profil dans l'arbre : refuse (404) une branche pas encore
    écrite par le parent — jamais de génération à la volée pendant que l'enfant écoute."""
    serie = charger(serie_id, cle)
    _profil_de(body.profil_id, cle)
    arbre = serie.get("arbre")
    if not arbre:
        raise HTTPException(404, "Aucun arbre pour cette série.")
    noeud, _chemin = S._trouver_noeud(arbre, noeud_id)
    if not noeud:
        raise HTTPException(404, "Nœud introuvable.")
    enfant = next((e for e in noeud.get("enfants", []) if e["choix"] == body.choix), None)
    if not enfant or not enfant["noeud"].get("script"):
        raise HTTPException(404, "Cette suite n'est pas encore écrite.")
    S._ajouter_evenement(body.profil_id, {
        "type": "arbre_choix", "serie_id": serie_id, "serie_titre": serie.get("titre"),
        "episode_n": enfant["noeud"].get("episode_n"), "noeud_id": enfant["noeud"]["id"],
        "choix": body.choix,
    })
    return {"noeud_id": enfant["noeud"]["id"]}


@app.post("/series/{serie_id}/arbre", tags=["arbre"])
async def cartographier(serie_id: str, body: Arbre, cle: str = Depends(cle_api)):
    serie = charger(serie_id, cle)
    showrunner = _agent("Showrunner")
    prof_max = max(1, min(body.profondeur, 4))
    compteur = [0]

    def _nid():
        compteur[0] += 1
        return f"n{compteur[0]}"

    async def _construire(chemin: list, niveau: int) -> dict:
        syn, choix = await S._noeud(showrunner, serie, chemin)
        noeud = {"id": _nid(), "niveau": niveau, "synopsis": syn, "choix": choix, "enfants": []}
        if niveau < prof_max:
            for c in choix:
                enfant = await _construire(chemin + [c], niveau + 1)
                noeud["enfants"].append({"choix": c, "noeud": enfant})
        return noeud

    arbre = await _construire([], 1)
    serie["arbre"] = arbre
    serie["arbre_nb_noeuds"] = compteur[0]
    S._save(serie)
    return {"arbre": arbre, "nb_noeuds": compteur[0], "profondeur": prof_max}


@app.post("/series/{serie_id}/arbre/{noeud_id}/jouer", tags=["arbre"])
async def jouer_noeud(serie_id: str, noeud_id: str, cle: str = Depends(cle_api)):
    """Écrit la scène jouable d'un nœud (= la branche choisie) ET la grave comme chapitre."""
    serie = charger(serie_id, cle)
    arbre = serie.get("arbre")
    if not arbre:
        raise HTTPException(400, "Aucun arbre — cartographie d'abord.")
    noeud, chemin = S._trouver_noeud(arbre, noeud_id)
    if not noeud:
        raise HTTPException(404, "Nœud introuvable.")

    deja = bool(noeud.get("script"))
    if not deja:
        scenariste = _agent("Scénariste")
        ctx = " → ".join(chemin) if chemin else "(ouverture de la série)"
        noeud["script"] = await agents.demander(
            scenariste,
            f"{S._consigne_langue(serie)}{S._consigne_cible(serie)}"
            f"Bible de « {serie['titre']} » :\n{S._bible_texte(serie)}\n\n"
            f"{S._distribution_texte(serie)}"
            f"{S._contexte_volume(serie)}"
            f"Chemin de choix du lecteur jusqu'ici : {ctx}.\n"
            f"Synopsis de CE moment : {noeud['synopsis']}\n\n"
            "Écris la SCÈNE jouable de ce moment (dialogues + action, ~15 répliques), immersive, "
            f"qui se termine en amenant naturellement les 2 choix proposés : {noeud['choix']}.")

    episode_n = S._materialiser_chapitre(serie, noeud, chemin)
    ep = next(e for e in serie["episodes"] if e["n"] == episode_n)
    if "valeur_suggeree" not in ep:
        ep["valeur_suggeree"] = await S._suggerer_valeur(ep.get("script_brut", ""))
        ep["valeur"] = ep["valeur_suggeree"]
    S._save(serie)
    return {"script": noeud["script"], "synopsis": noeud["synopsis"],
            "choix": noeud["choix"], "deja": deja, "episode_n": episode_n}


@app.post("/series/{serie_id}/arbre/{noeud_id}/etendre", tags=["arbre"])
async def etendre_branche(serie_id: str, noeud_id: str, body: Etendre,
                          cle: str = Depends(cle_api)):
    """Projette une branche : génère le nœud SUIVANT pour un choix donné."""
    serie = charger(serie_id, cle)
    arbre = serie.get("arbre")
    if not arbre:
        raise HTTPException(400, "Aucun arbre — cartographie d'abord.")
    noeud, chemin = S._trouver_noeud(arbre, noeud_id)
    if not noeud:
        raise HTTPException(404, "Nœud introuvable.")
    for e in noeud.get("enfants", []):
        if e["choix"] == body.choix:
            return {"noeud": e["noeud"], "deja": True}

    showrunner = _agent("Showrunner")
    syn, choix = await S._noeud(showrunner, serie, chemin + [body.choix])
    serie["arbre_nb_noeuds"] = serie.get("arbre_nb_noeuds", 0) + 1
    nouveau = {
        "id": f"n{serie['arbre_nb_noeuds']}", "niveau": noeud.get("niveau", 1) + 1,
        "synopsis": syn, "choix": choix, "enfants": [],
    }
    noeud.setdefault("enfants", []).append({"choix": body.choix, "noeud": nouveau})
    S._save(serie)
    return {"noeud": nouveau, "deja": False}
