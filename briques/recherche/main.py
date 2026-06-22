"""Brique « recherche » — recherche web + lecture de page en API.

Produit autonome, sans dépendance à Oria/Workplace, miroir des briques vision/transcription.
Deux gestes composables, déclarés comme CAPACITÉS dans le manifest → outils du Cœur :

  • /rechercher : une requête → liens classés CLIQUABLES (titre, url, extrait).
                  Capacité `recherche_web`. Lecture seule.
  • /lire-page  : une URL → texte principal + liens de la page, pour que l'assistant
                  RÉSUME en gardant les sources. Capacité `page_lire`. Lecture seule.

Souverain par défaut : le moteur de recherche est SearXNG auto-hébergé (conteneur voisin,
0 clé), avec repli DuckDuckGo sans-infra et extension Tavily à clé (cf. fournisseurs.py).
La lecture de page est LOCALE (Trafilatura), bornée et polie (robots.txt) (cf. extraction.py).

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
import fournisseurs

app = FastAPI(title="Recherche — recherche web + lecture de page", version="0.1.0")

# Origines navigateur autorisées : liste explicite via CORS_ORIGINS (CSV). Défaut "*"
# = comportement historique. En MULTI-TENANT local, restreindre (cf. brique vision).
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


class Rechercher(BaseModel):
    requete:     str
    n:           Optional[int] = None          # nombre de résultats voulus
    langue:      Optional[str] = None          # ex. "fr", "en"
    fournisseur: Optional[str] = None          # force un moteur (sinon : ordre de préférence)


class LirePage(BaseModel):
    url: str


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return ("<h1>🔎 Brique recherche</h1><p>Recherche web (SearXNG souverain + repli) et "
            "lecture de page (Trafilatura). Voir <a href='/docs'>/docs</a>.</p>")


@app.get("/sante", tags=["système"])
def sante():
    """État : moteurs connus, ceux configurés, et celui qui servirait en tête."""
    dispo = fournisseurs.disponibles()
    return {
        "ok": True,
        "fournisseurs": list(fournisseurs.REGISTRE.keys()),
        "ordre": fournisseurs.ordre(),
        "configures": dispo,
        "actif": dispo[0] if dispo else None,
    }


@app.get("/fournisseurs", tags=["système"])
def liste_fournisseurs():
    """Catalogue des moteurs : nom + s'il est configuré (pour proposer un choix côté UI)."""
    return {"fournisseurs": [{"nom": n, "configure": f.disponible()}
                             for n, f in fournisseurs.REGISTRE.items()],
            "ordre": fournisseurs.ordre()}


@app.post("/rechercher", tags=["recherche", "synergie"])
async def rechercher(body: Rechercher, _cle: str = Depends(cle_api)):
    """Une requête → liens classés cliquables. Cascade de moteurs, repli honnête (vide)."""
    requete = (body.requete or "").strip()
    if not requete:
        raise HTTPException(422, "Requête vide.")
    n = body.n or fournisseurs._n_defaut()
    n = max(1, min(50, n))
    langue = (body.langue or "fr").strip()

    if body.fournisseur:
        f = fournisseurs.REGISTRE.get(body.fournisseur.lower())
        candidats = [body.fournisseur.lower()] if (f and f.disponible()) else []
    else:
        candidats = fournisseurs.disponibles()

    if not candidats:
        return {"requete": requete, "resultats": [], "backend": None, "nb": 0,
                "note": "Aucun moteur de recherche configuré : démarrez le conteneur "
                        "SearXNG (souverain), autorisez DuckDuckGo (RECHERCHE_DDG=1) ou "
                        "renseignez TAVILY_API_KEY."}

    erreurs = {}
    for nom in candidats:
        try:
            resultats = await fournisseurs.REGISTRE[nom].rechercher(requete, n, langue)
            if resultats:
                return {"requete": requete, "resultats": resultats,
                        "backend": nom, "nb": len(resultats)}
            erreurs[nom] = "aucun résultat"
        except Exception as e:  # noqa: BLE001
            erreurs[nom] = str(e)[:160]

    return {"requete": requete, "resultats": [], "backend": None, "nb": 0,
            "note": "Moteurs essayés sans résultat : " + ", ".join(candidats),
            "erreurs": erreurs}


@app.post("/lire-page", tags=["recherche", "synergie"])
async def lire_page(body: LirePage, _cle: str = Depends(cle_api)):
    """Une URL → texte principal + liens de la page (pour résumer en gardant les sources)."""
    try:
        return await extraction.lire_page(body.url)
    except extraction.ErreurLecture as e:
        raise HTTPException(422, str(e))
