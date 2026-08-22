"""Brique « personnages » — création de distributions & casting vocal, en API.

Produit autonome (vendable seul), sans dépendance à Oria/Workplace :
  • STATELESS (le moteur) : /distribution/proposer, /casting — entrée→sortie, rien stocké ;
  • STATEFUL (optionnel) : /distributions/* — distributions persistées, cloisonnées par clé API ;
  • LLM : Gateway Workplace par défaut, ou Bring-Your-Own-Key par appel (champ `llm`).

Le casting vocal (affectation STABLE d'identifiants de voix opaques, agnostique TTS) est
le module « voix » — activable à la demande, c'est le différenciateur du produit.
"""
import os
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional

import llm
import moteur
import significations
import stockage
import synthese
import theme_complet
import traditions

app = FastAPI(title="Personnages — distribution & casting", version="0.8.0")
# Origines navigateur autorisées : liste explicite via CORS_ORIGINS (CSV). Défaut "*"
# = comportement historique. En contexte MULTI-TENANT (même local : autre tenant/
# assistant sur la machine), définir CORS_ORIGINS=http://localhost:5100,... pour
# qu'une page web tierce ne puisse pas appeler cette brique depuis le navigateur.
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

# Clés API acceptées (séparées par virgule). Vide = mode OUVERT (dev) : tenant unique "public".
# `API_KEYS` = vente standalone (BYO). `PERSONNAGES_KEY` = clé d'intégration Workplace,
# injectée par le Cœur en X-API-Key (motif `_entetes_brique`, style « clé fusionnée » de
# l'ADR surface-de-service, S167) : on l'ajoute aux clés acceptées pour que l'assistant
# pilote la brique MÊME quand l'auth BYO est activée (sinon il serait rejeté).
API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}
if os.getenv("PERSONNAGES_KEY", "").strip():
    API_KEYS.add(os.getenv("PERSONNAGES_KEY").strip())


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    """Valide la clé API (header X-API-Key ou Authorization: Bearer) et sert de tenant.

    Si aucune clé n'est configurée (API_KEYS vide), on tourne en mode ouvert → tenant
    "public" (pratique en dev/démo, à ne pas laisser tel quel en prod)."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


# ── Modèles de requête ───────────────────────────────────────────
class Proposer(BaseModel):
    premisse:   str = ""
    langue:     str = "français"
    combien:    int = 4
    deja:       str = ""
    voix_dispo: Optional[list] = None     # si fourni → casting suggéré (module voix)
    llm:        Optional[dict] = None      # BYO : {base_url, cle, modele}


class Casting(BaseModel):
    personnages: list = []
    repliques:   list = []                # [{perso, texte}] ou ["NOM", ...]
    langue:      str = "fr"
    pool_voix:   list = []                # identifiants de voix opaques (TTS du client)


class CreerDistribution(BaseModel):
    titre:    str = ""
    langue:   str = "fr"
    premisse: str = ""


class MajDistribution(BaseModel):
    titre:       Optional[str] = None
    langue:      Optional[str] = None
    premisse:    Optional[str] = None
    personnages: Optional[list] = None


class Perso(BaseModel):
    nom:           str
    nom_naissance: Optional[str] = None   # nom cosmique d'origine (figé si absent → = nom)
    role:          Optional[str] = None
    description:   Optional[str] = None
    voix:          Optional[dict] = None


class FicheHolistique(BaseModel):
    """Données d'entrée du mode descendant. Tout est optionnel sauf, en pratique, la date :
    chaque champ manquant désactive juste la lecture qui en dépend (repli honnête)."""
    prenoms:        str = ""
    nom:            str = ""
    date_naissance: str = ""               # "YYYY-MM-DD"
    heure_naissance: Optional[str] = None   # "HH:MM"
    latitude:       Optional[float] = None
    longitude:      Optional[float] = None  # EST-positive
    utc_offset:     Optional[float] = None  # décalage local→UTC à la naissance
    systeme_numerologie: str = "classique"  # "classique" (A=1…Z=26) ou "pythagoricien"
    langue_sortie:  str = "fr"              # "fr" ou "en" (S194) : langue du portrait/empreinte
                                             # DÉTERMINISTES. Sans rapport avec `LectureApprofondie.
                                             # langue` (texte libre passé au LLM, ex. "français").
    systeme_maisons: str = "whole_sign"     # "whole_sign" | "placidus" | "equal_house"
    methode_dominantes: str = "comptage_dignite"  # "comptage_dignite" | "score_complexe"


class RechercheInverse(BaseModel):
    description: str = ""
    combien:     int = 3
    llm:         Optional[dict] = None     # BYO/local pour le filet de secours : {base_url, cle, modele}


class LectureApprofondie(FicheHolistique):
    """Même fiche que le portrait, + la langue de rédaction et un LLM BYO optionnel."""
    langue: str = "français"
    llm:    Optional[dict] = None


class RenommerFiche(BaseModel):
    """Nouveau nom AFFICHÉ d'une fiche (p.ex. nom de scène pour une série). Le nom
    cosmique d'origine (nom_naissance) et les données restent intacts."""
    nom: str


class RangerFiche(BaseModel):
    """Catégorie libre où ranger la fiche (« Famille », « Collègues »…). Vide = non rangé."""
    categorie: str = ""


class EnregistrerFiche(BaseModel):
    """Snapshot d'une fiche cosmique à persister (opt-in). On envoie le résultat déjà
    calculé pour ne pas dépendre d'un recalcul (la lecture IA notamment n'est pas déterministe)."""
    nom:                 str = ""
    categorie:           str = ""               # rangement libre choisi par l'utilisateur
    contexte:            Optional[dict] = None   # état-civil saisi (prénoms, date, ville…)
    traditions:          Optional[dict] = None
    portrait:            Optional[dict] = None
    empreinte:           Optional[list] = None
    lecture_approfondie: Optional[str] = None


# ── Front de démo (page d'accueil) ───────────────────────────────
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    """Démo visuelle : proposer une distribution puis caster un script."""
    return Path(__file__).parent.joinpath("front.html").read_text(encoding="utf-8")


@app.get("/atelier", response_class=HTMLResponse, include_in_schema=False)
def atelier_holistique():
    """Démo visuelle du moteur holistique : portrait (descendant) & recherche inverse (montant)."""
    return Path(__file__).parent.joinpath("front_holistique.html").read_text(encoding="utf-8")


# Socle partagé « manipulation directe » (S101) : menu contextuel + modale + cliquer-déposer.
# Source unique = shared/manipulation_directe.js, copié ici par outils/sync_socle.sh.
@app.get("/manipulation_directe.js", include_in_schema=False)
def socle():
    return FileResponse(Path(__file__).parent / "manipulation_directe.js",
                        media_type="application/javascript")


# Design system partagé (S123) : tokens visuels du monorepo.
# Source unique = shared/static/workplace.css, copié ici par outils/sync_socle.sh.
@app.get("/workplace.css", include_in_schema=False)
def design_system():
    return FileResponse(Path(__file__).parent / "workplace.css", media_type="text/css")


# ── Santé ────────────────────────────────────────────────────────
@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok", "service": "personnages", "version": app.version,
            "auth": "cle_api" if API_KEYS else "ouvert",
            "modules": ["distribution", "casting_voix", "stockage", "holistique"],
            "traditions": ["numerologie", "astro_occidentale", "astro_chinoise",
                           "egyptien", "celte", "amerindien", "maya_tzolkin", "vedique",
                           "lune", "nakshatra"],
            "stats": synthese.STATS,
            "llm_defaut": llm.GATEWAY_MODEL}


# ── STATELESS : le moteur pur ────────────────────────────────────
@app.post("/distribution/proposer", tags=["stateless"])
async def proposer(body: Proposer, _cle: str = Depends(cle_api)):
    """Propose une distribution structurée à partir d'une prémisse (LLM). Ne stocke rien.
    Si `voix_dispo` est fourni, renvoie aussi un casting suggéré (module voix)."""
    try:
        persos = await llm.proposer_distribution(
            body.premisse, body.langue, body.combien, body.deja, body.llm)
    except Exception as e:  # noqa: BLE001 — repli honnête
        raise HTTPException(502, f"LLM injoignable ou invalide : {str(e)[:160]}")
    out = {"personnages": persos}
    if body.voix_dispo:
        avec_voix, _ = moteur.assigner_voix(persos, body.langue[:2] or "fr", body.voix_dispo)
        out["personnages"] = avec_voix
        out["casting_suggere"] = {p["nom"]: p["voix"].get(body.langue[:2] or "fr")
                                  for p in avec_voix}
    return out


@app.post("/casting", tags=["stateless", "voix"])
def casting(body: Casting, _cle: str = Depends(cle_api)):
    """Affecte des voix (identifiants opaques) aux intervenants d'un script, de façon
    STABLE. Module voix — le différenciateur. Rien stocké : la distribution enrichie
    est renvoyée pour que l'appelant la re-persiste s'il le souhaite."""
    intervenants = moteur.intervenants_depuis_repliques(body.repliques)
    return moteur.caster(body.personnages, body.langue, intervenants, body.pool_voix)


# ── HOLISTIQUE : génération de personnages multi-traditions (S49) ─
@app.post("/holistique/traditions", tags=["holistique"])
def holistique_traditions(body: FicheHolistique, _cle: str = Depends(cle_api)):
    """Calcule les lectures de TOUTES les traditions dérivables de la fiche (mode descendant,
    étape 1). Rien stocké. L'astro = calcul exact, l'interprétation = divertissement."""
    return traditions.calculer(body.model_dump())


@app.post("/holistique/theme", tags=["holistique"])
def holistique_theme(body: FicheHolistique, _cle: str = Depends(cle_api)):
    """Carte astrologique complète (fondations, 10 corps, points évolutifs, maisons,
    aspects, dominantes). Seule la date est absolument requise — sans heure/lieu, seules
    les fondations Soleil/Lune sont calculées (Lune approximative sans heure) ; le reste
    en repli honnête."""
    tc = theme_complet.theme_complet(body.model_dump())
    if not tc.get("fondations", {}).get("soleil"):
        raise HTTPException(422, "Fiche insuffisante : fournis au moins une date de naissance valide.")
    return tc


@app.post("/holistique/portrait", tags=["holistique"])
def holistique_portrait(body: FicheHolistique, _cle: str = Depends(cle_api)):
    """Mode DESCENDANT complet : fiche → traditions → tags → stats → archétype + forces /
    faiblesse + pierre d'équilibrage + récit. Enrichi de la carte astro complète (aspects,
    maisons, dominantes planète×signe) quand elle est calculable. Le différenciateur « holistique »."""
    fiche = body.model_dump()
    trad = traditions.calculer(fiche)
    if not trad.get("signe_solaire"):    # les stats dérivent de la date → elle est requise ici
        raise HTTPException(422, "Fiche insuffisante : fournis au moins une date de naissance valide.")
    tc = theme_complet.theme_complet_depuis_traditions(trad, fiche)
    p = synthese.portrait(trad, theme_complet=tc, nom=body.prenoms or body.nom, langue=body.langue_sortie)
    en = (body.langue_sortie or "fr").lower().startswith("en")
    return {"traditions": trad, "theme_complet": tc, "portrait": p,
            "empreinte": significations.expliquer(trad, body.langue_sortie, theme_complet=tc),
            "glossaire": significations.glossaire(body.langue_sortie),
            "didactique": significations.didactique(body.langue_sortie),
            "signes_sens": (significations.SIGNES_SENS_EN if en else significations.SIGNES_SENS)}


@app.post("/holistique/lecture-approfondie", tags=["holistique"])
async def holistique_lecture_approfondie(body: LectureApprofondie, _cle: str = Depends(cle_api)):
    """Réécriture LITTÉRAIRE de la lecture symbolique par le LLM (modèle gratuit Gateway par
    défaut, ou BYO). Bonus opt-in : le socle déterministe du portrait reste gratuit/instantané.
    Repli HONNÊTE : si l'IA est indisponible, on renvoie le récit déterministe (`source=repli`)."""
    fiche = {k: getattr(body, k) for k in FicheHolistique.model_fields}
    trad = traditions.calculer(fiche)
    if not trad.get("signe_solaire"):
        raise HTTPException(422, "Fiche insuffisante : fournis au moins une date de naissance valide.")
    tc = theme_complet.theme_complet_depuis_traditions(trad, fiche)
    p = synthese.portrait(trad, theme_complet=tc, nom=body.prenoms or body.nom, langue=body.langue_sortie)
    emp = significations.expliquer(trad, body.langue_sortie, theme_complet=tc)
    try:
        texte = await llm.approfondir_lecture(p, emp, body.langue, body.llm)
        if texte:
            return {"lecture": texte, "source": "llm"}
    except Exception as e:  # noqa: BLE001 — repli honnête : on retombe sur le déterministe
        import logging
        logging.getLogger("personnages").warning(
            "lecture-approfondie : repli déterministe activé — %s: %s",
            type(e).__name__, str(e)[:200])
    return {"lecture": p["recit"], "source": "repli"}


@app.get("/geo", tags=["holistique"])
async def geo(ville: str, _cle: str = Depends(cle_api)):
    """Géocode une ville → latitude / longitude (OpenStreetMap Nominatim, gratuit, sans clé).

    Pratique pour saisir « Toulouse » plutôt que des coordonnées. Repli honnête si le service
    est injoignable. La longitude renvoyée est EST-positive (convention de la fiche)."""
    q = (ville or "").strip()
    if not q:
        raise HTTPException(422, "Indique une ville.")
    try:
        async with httpx.AsyncClient(timeout=8) as cli:
            r = await cli.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": q, "format": "json", "limit": 1, "accept-language": "fr"},
                headers={"User-Agent": "workplace-personnages/0.3 (atelier holistique)"})
        data = r.json()
    except Exception as e:  # noqa: BLE001 — repli honnête
        raise HTTPException(502, f"Géocodage injoignable : {str(e)[:120]}")
    if not data:
        raise HTTPException(404, f"Ville introuvable : {q}")
    top = data[0]
    return {"ville": top.get("display_name", q),
            "latitude": float(top["lat"]), "longitude": float(top["lon"])}


@app.post("/holistique/recherche-inverse", tags=["holistique"])
async def holistique_recherche_inverse(body: RechercheInverse, _cle: str = Depends(cle_api)):
    """Mode MONTANT : description libre d'un caractère → signes / nombres / date qui collent.

    Analyse par CHAMP LEXICAL local d'abord (rapide, hors-ligne). FILET DE SECOURS : si rien
    n'est reconnu, on demande à un LLM (modèle gratuit Gateway par défaut, ou BYO/local) de
    traduire la description en axes — puis on continue le même calcul. `source_analyse` dit
    laquelle a servi. La non-unicité est assumée (DES pistes, pas LA vérité)."""
    combien = max(1, min(body.combien, 12))
    cible = synthese.cibler_stats(body.description)
    source = "lexique"
    if not any(cible.values()) and (body.description or "").strip():
        try:
            llm_cible = await llm.cibler_via_llm(body.description, synthese.STATS, body.llm)
            if llm_cible and any(llm_cible.values()):
                cible, source = llm_cible, "llm"
        except Exception:  # noqa: BLE001 — repli honnête : on garde la cible vide
            source = "lexique"
    res = synthese.recherche_inverse(body.description, combien, cible=cible)
    res["source_analyse"] = source
    return res


# ── STATEFUL : fiches cosmiques enregistrées (opt-in, cloisonnées par clé API) ─
@app.post("/fiches", tags=["stateful", "holistique"])
def enregistrer_fiche(body: EnregistrerFiche, cle: str = Depends(cle_api)):
    """Enregistre une fiche cosmique générée. La génération reste STATELESS : on ne stocke
    QUE sur action délibérée de l'utilisateur. Isolé par clé API (un tenant ne voit pas
    les fiches d'un autre)."""
    donnees = {"contexte": body.contexte or {}, "traditions": body.traditions or {},
               "portrait": body.portrait or {}, "empreinte": body.empreinte or [],
               "lecture_approfondie": body.lecture_approfondie or ""}
    nom = body.nom.strip() or (body.contexte or {}).get("prenoms") or "Personnage"
    return stockage.creer_fiche(cle, nom, donnees, categorie=body.categorie)


@app.get("/fiches", tags=["stateful", "holistique"])
def lister_fiches(cle: str = Depends(cle_api)):
    return stockage.lister_fiches(cle)


@app.get("/fiches/{fid}", tags=["stateful", "holistique"])
def lire_fiche(fid: str, cle: str = Depends(cle_api)):
    f = stockage.lire_fiche(cle, fid)
    if not f:
        raise HTTPException(404, "Fiche introuvable")
    return f


@app.patch("/fiches/{fid}", tags=["stateful", "holistique"])
def renommer_fiche(fid: str, body: RenommerFiche, cle: str = Depends(cle_api)):
    """Renomme la fiche pour une série (nom de scène). Garde le nom cosmique d'origine
    (nom_naissance) et toutes les données : seule l'étiquette affichée change."""
    f = stockage.renommer_fiche(cle, fid, body.nom)
    if not f:
        if stockage.lire_fiche(cle, fid) is None:
            raise HTTPException(404, "Fiche introuvable")
        raise HTTPException(422, "Le nom ne peut pas être vide.")
    return f


@app.patch("/fiches/{fid}/categorie", tags=["stateful", "holistique"])
def ranger_fiche(fid: str, body: RangerFiche, cle: str = Depends(cle_api)):
    """Range la fiche dans une catégorie libre (« Famille », « Collègues »…). Une catégorie
    vide retire le rangement. Ne touche ni au nom ni aux données cosmiques."""
    f = stockage.ranger_fiche(cle, fid, body.categorie)
    if not f:
        raise HTTPException(404, "Fiche introuvable")
    return f


@app.delete("/fiches/{fid}", status_code=204, tags=["stateful", "holistique"])
def supprimer_fiche(fid: str, cle: str = Depends(cle_api)):
    if not stockage.supprimer_fiche(cle, fid):
        raise HTTPException(404, "Fiche introuvable")


# ── STATEFUL : distributions persistées (cloisonnées par clé API) ─
@app.post("/distributions", tags=["stateful"])
def creer_distribution(body: CreerDistribution, cle: str = Depends(cle_api)):
    return stockage.creer(cle, body.titre, body.langue, body.premisse)


@app.get("/distributions", tags=["stateful"])
def lister_distributions(cle: str = Depends(cle_api)):
    return stockage.lister(cle)


@app.get("/distributions/{did}", tags=["stateful"])
def lire_distribution(did: str, cle: str = Depends(cle_api)):
    d = stockage.lire(cle, did)
    if not d:
        raise HTTPException(404, "Distribution introuvable")
    return d


@app.patch("/distributions/{did}", tags=["stateful"])
def maj_distribution(did: str, body: MajDistribution, cle: str = Depends(cle_api)):
    d = stockage.maj(cle, did, body.model_dump(exclude_none=True))
    if not d:
        raise HTTPException(404, "Distribution introuvable")
    return d


@app.delete("/distributions/{did}", status_code=204, tags=["stateful"])
def supprimer_distribution(did: str, cle: str = Depends(cle_api)):
    if not stockage.supprimer(cle, did):
        raise HTTPException(404, "Distribution introuvable")


@app.post("/distributions/{did}/proposer", tags=["stateful"])
async def proposer_dans(did: str, body: Proposer, cle: str = Depends(cle_api)):
    """Propose des personnages cohérents avec la distribution stockée et les AJOUTE."""
    d = stockage.lire(cle, did)
    if not d:
        raise HTTPException(404, "Distribution introuvable")
    deja = moteur.distribution_texte(d["personnages"])
    persos = await llm.proposer_distribution(
        body.premisse or d.get("premisse", ""), body.langue or d.get("langue", "fr"),
        body.combien, deja, body.llm)
    return {"propositions": persos}   # l'ajout effectif se fait via POST .../personnages


@app.post("/distributions/{did}/personnages", tags=["stateful"])
def ajouter_perso(did: str, body: Perso, cle: str = Depends(cle_api)):
    d = stockage.lire(cle, did)
    if not d:
        raise HTTPException(404, "Distribution introuvable")
    persos = d["personnages"]
    pid = moteur.prochain_id("p", {p.get("id") for p in persos})
    nom = body.nom.strip()
    # nom_naissance = nom cosmique d'origine, figé une fois pour toutes. S'il n'est pas
    # fourni (perso saisi à la main), il vaut le nom courant ; on garde toujours les deux.
    perso = {"id": pid, "nom": nom, "nom_naissance": (body.nom_naissance or nom).strip(),
             "role": (body.role or "").strip(),
             "description": (body.description or "").strip(),
             "voix": body.voix if isinstance(body.voix, dict) else {}}
    persos.append(perso)
    stockage.maj(cle, did, {"personnages": persos})
    return perso


@app.patch("/distributions/{did}/personnages/{pid}", tags=["stateful"])
def maj_perso(did: str, pid: str, body: dict, cle: str = Depends(cle_api)):
    d = stockage.lire(cle, did)
    if not d:
        raise HTTPException(404, "Distribution introuvable")
    perso = next((p for p in d["personnages"] if p.get("id") == pid), None)
    if not perso:
        raise HTTPException(404, "Personnage introuvable")
    # Avant de renommer pour la série, fige le nom d'origine s'il manquait encore
    # (fiches créées avant cette mémoire) → on garde toujours les deux.
    perso.setdefault("nom_naissance", perso.get("nom", ""))
    for k in ("nom", "nom_naissance", "role", "description"):
        if k in body and body[k] is not None:
            perso[k] = str(body[k]).strip()
    if isinstance(body.get("voix"), dict):
        perso.setdefault("voix", {}).update({k: v for k, v in body["voix"].items() if v})
    stockage.maj(cle, did, {"personnages": d["personnages"]})
    return perso


@app.delete("/distributions/{did}/personnages/{pid}", status_code=204, tags=["stateful"])
def supprimer_perso(did: str, pid: str, cle: str = Depends(cle_api)):
    d = stockage.lire(cle, did)
    if not d:
        raise HTTPException(404, "Distribution introuvable")
    d["personnages"] = [p for p in d["personnages"] if p.get("id") != pid]
    stockage.maj(cle, did, {"personnages": d["personnages"]})


@app.post("/distributions/{did}/casting", tags=["stateful", "voix"])
def casting_distribution(did: str, body: Casting, cle: str = Depends(cle_api)):
    """Caste un script avec la distribution STOCKÉE, et re-persiste les voix épinglées."""
    d = stockage.lire(cle, did)
    if not d:
        raise HTTPException(404, "Distribution introuvable")
    intervenants = moteur.intervenants_depuis_repliques(body.repliques)
    res = moteur.caster(d["personnages"], body.langue, intervenants, body.pool_voix)
    stockage.maj(cle, did, {"personnages": res["personnages"]})   # voix figées persistées
    return res
