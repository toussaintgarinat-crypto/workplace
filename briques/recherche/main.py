"""Brique « recherche » (moteur HuntR porté) — recherche web multi-providers + lecture de page.

Contrat exposé au Cœur : capacités `recherche_web` et `page_lire` (port 6040), avec un moteur
riche emprunté au plugin HuntR de Gungnir :

  • /rechercher : une requête → liens classés CLIQUABLES. Lance EN PARALLÈLE tous les
                  moteurs configurés (jusqu'à 9 : SearXNG, DuckDuckGo, Tavily, Brave, Exa,
                  Serper, SerpAPI, Kagi, Bing), déduplique par URL canonique et CLASSE par
                  consensus (nb de moteurs × poids × rang). Multi-thème (web|news|academic|code).
                  Capacité `recherche_web`. Lecture seule.
  • /lire-page  : une URL → texte principal (Trafilatura souverain) + liens, pour résumer
                  EN gardant les sources. Capacité `page_lire`. Lecture seule.

Souverain par défaut : SearXNG auto-hébergé (conteneur voisin, 0 clé) + DuckDuckGo
sans-infra. Les moteurs à clé sont INERTES tant que leur clé n'est pas renseignée.

Honnêteté : aucun lien inventé, aucun faux texte. Si aucun moteur ne répond, on rend une
liste vide qui le DIT ; si une page est illisible, on rend l'erreur, pas un placeholder.
"""
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import extraction
import providers
import synthese as syn
from cache import recherche_cache
from search_providers import VALID_TOPICS, multi_search
from source_filters import apply_source_filters, has_active_filters

app = FastAPI(title="Recherche — HuntR : recherche web multi-providers + lecture de page",
              version="1.0.0")

# Origines navigateur autorisées : liste explicite via CORS_ORIGINS (CSV). Défaut "*".
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


def _filtres_config() -> dict:
    """Filtres de source (blocklist/allowlist) lus depuis l'env. Opt-in, inertes par défaut."""
    cfg: dict = {}
    if _envr("STARTER_BLOCKLIST", "0") == "1":
        cfg["use_starter_blocklist"] = True
    bl = [d.strip() for d in _envr("BLOCKLIST", "").split(",") if d.strip()]
    if bl:
        cfg["blocklist"] = bl
    al = [d.strip() for d in _envr("ALLOWLIST", "").split(",") if d.strip()]
    if al:
        cfg["allowlist"] = al
        cfg["allowlist_mode"] = _envr("ALLOWLIST_MODE", "boost").lower()
    return cfg


def _envr(nom: str, defaut: str = "") -> str:
    """Lit RECHERCHE_<nom>, repli BROWSER_<nom> (nommage HuntR), puis défaut."""
    return os.getenv(f"RECHERCHE_{nom}", os.getenv(f"BROWSER_{nom}", defaut))


def _n_defaut() -> int:
    try:
        return max(1, min(50, int(_envr("N_DEFAUT", "8"))))
    except ValueError:
        return 8


class Rechercher(BaseModel):
    requete:     str
    n:           Optional[int] = None          # nombre de résultats voulus
    langue:      Optional[str] = None          # compat (HuntR cible le fr par défaut)
    topic:       Optional[str] = None          # web | news | academic | code
    fournisseur: Optional[str] = None          # force UN moteur (sinon : tous les actifs)


class Synthetiser(BaseModel):
    requete:      str
    n:            Optional[int] = None
    topic:        Optional[str] = None
    langue:       Optional[str] = None
    instructions: Optional[str] = None


class LirePage(BaseModel):
    url: str
    js:  Optional[bool] = None  # True = forcer Playwright, None/False = auto


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return ("<h1>🔎 Brique recherche (moteur HuntR)</h1><p>Recherche web multi-providers "
            "(SearXNG souverain + DuckDuckGo + 7 moteurs à clé, fusion par consensus) et "
            "lecture de page (Trafilatura). Voir <a href='/docs'>/docs</a>.</p>")


@app.get("/sante", tags=["système"])
def sante():
    """État : moteurs connus, ceux configurés, et celui qui servirait en tête."""
    actifs = providers.noms_actifs()
    return {
        "ok": True,
        "fournisseurs": list(providers.CATALOGUE.keys()),
        "ordre": providers.ordre(),
        "configures": actifs,
        "actif": actifs[0] if actifs else None,
    }


@app.get("/fournisseurs", tags=["système"])
def liste_fournisseurs():
    """Catalogue des moteurs : nom + s'il est configuré (pour proposer un choix côté UI)."""
    actifs = set(providers.noms_actifs())
    return {"fournisseurs": [{"nom": n, "configure": n in actifs}
                             for n in providers.CATALOGUE],
            "ordre": providers.ordre()}


@app.post("/rechercher", tags=["recherche", "synergie"])
async def rechercher(body: Rechercher, _cle: str = Depends(cle_api)):
    """Une requête → liens classés cliquables. Fusion multi-moteurs, repli honnête (vide)."""
    requete = (body.requete or "").strip()
    if not requete:
        raise HTTPException(422, "Requête vide.")
    n = max(1, min(50, body.n or _n_defaut()))
    topic = (body.topic or "web").lower()
    if topic not in VALID_TOPICS:
        topic = "web"

    actifs = providers.actifs()
    if body.fournisseur:
        cible = body.fournisseur.lower()
        actifs = [(nom, inst) for nom, inst in actifs if nom == cible]

    if not actifs:
        return {"requete": requete, "topic": topic, "resultats": [], "backend": None, "nb": 0,
                "note": "Aucun moteur de recherche configuré : démarrez le conteneur SearXNG "
                        "(souverain), autorisez DuckDuckGo (BROWSER_DDG=1) ou renseignez une clé "
                        "(TAVILY_API_KEY, BRAVE_API_KEY, SERPER_API_KEY…)."}

    langue = (body.langue or "fr").lower().strip()
    noms = [nom for nom, _ in actifs]
    cache_key = recherche_cache.make_key(requete, topic, n, noms) + f"|{langue}"
    cached = recherche_cache.get(cache_key)
    if cached is not None:
        return cached

    resultats = await multi_search(actifs, requete, max_results=n, topic=topic, langue=langue)

    rapport_filtre = None
    cfg = _filtres_config()
    if resultats and has_active_filters(cfg):
        resultats, rapport_filtre = apply_source_filters(resultats, cfg)

    sortie = [{
        "titre": r.title,
        "url": r.url,
        "extrait": r.snippet or r.content,
        "source": r.source,
        "providers": r.providers or [r.source],
        "score": r.score,
        "nb_providers": r.nb_providers,
    } for r in resultats]

    reponse = {"requete": requete, "topic": topic, "resultats": sortie,
               "backend": ",".join(noms), "moteurs": noms, "nb": len(sortie)}
    if rapport_filtre:
        reponse["filtre"] = rapport_filtre
    if not sortie:
        reponse["note"] = "Moteurs essayés sans résultat : " + ", ".join(noms)

    recherche_cache.set(cache_key, reponse)
    return reponse


@app.post("/synthétiser", tags=["recherche", "synergie"])
async def synthetiser_endpoint(body: Synthetiser, _cle: str = Depends(cle_api)):
    """Recherche + synthèse LLM — renvoie un texte en langage naturel + les sources."""
    requete = (body.requete or "").strip()
    if not requete:
        raise HTTPException(422, "Requête vide.")
    n = max(1, min(50, body.n or _n_defaut()))
    topic = (body.topic or "web").lower()
    if topic not in VALID_TOPICS:
        topic = "web"
    langue = (body.langue or "fr").lower().strip()

    actifs = providers.actifs()
    if not actifs:
        return {"requete": requete, "synthese": None, "sources": [], "backend": None,
                "nb_sources": 0,
                "note": "Aucun moteur de recherche configuré."}

    noms = [nom for nom, _ in actifs]
    resultats = await multi_search(actifs, requete, max_results=n, topic=topic, langue=langue)

    synthese_text, sources = await syn.synthetiser(
        requete, resultats,
        instructions=body.instructions or "",
        langue=langue,
        max_items=min(n, 8),
    )

    reponse: dict = {
        "requete": requete,
        "synthese": synthese_text,
        "sources": sources,
        "backend": ",".join(noms),
        "nb_sources": len(sources),
    }
    if synthese_text is None:
        reponse["note"] = "Gateway LLM indisponible — synthèse non réalisée."
    return reponse


@app.post("/lire-page", tags=["recherche", "synergie"])
async def lire_page(body: LirePage, _cle: str = Depends(cle_api)):
    """Une URL → texte principal + liens de la page (pour résumer en gardant les sources)."""
    try:
        return await extraction.lire_page(body.url, js=bool(body.js))
    except extraction.ErreurLecture as e:
        raise HTTPException(422, str(e))
