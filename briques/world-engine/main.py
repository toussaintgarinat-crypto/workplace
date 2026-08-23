"""Brique « world-engine » — croisement de 2 profils cosmiques (génome cosmique).

Stateless : entrée → sortie, rien stocké. Dépend de `personnages` (port 5900) en
HTTP pour tout calcul astral — ne duplique jamais le moteur.
"""
import os
from datetime import date
from random import Random
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import fusion
import personnages_client

app = FastAPI(title="World Engine — Génome Cosmique", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}
if os.getenv("WORLD_ENGINE_KEY", "").strip():
    API_KEYS.add(os.getenv("WORLD_ENGINE_KEY").strip())


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    """Valide la clé API (header X-API-Key ou Authorization: Bearer).

    API_KEYS vide (défaut dev) = mode ouvert. Même motif que `briques/personnages`."""
    if not API_KEYS:
        return "public"
    cle = x_api_key
    if not cle and authorization and authorization.startswith("Bearer "):
        cle = authorization[7:]
    if cle not in API_KEYS:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    return cle


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok", "brique": "world-engine"}


class FicheParent(BaseModel):
    """Même forme que FicheHolistique côté personnages — sous-ensemble minimal
    pour ce prototype (pas de systeme_numerologie/langue_sortie ici, YAGNI)."""
    prenoms: str = ""
    nom: str = ""
    date_naissance: str = ""
    heure_naissance: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    utc_offset: Optional[float] = None


class Croisement(BaseModel):
    parent_a: FicheParent
    parent_b: FicheParent
    prenoms_enfant: str = ""
    nom_enfant: str = ""
    latitude_enfant: float      # jamais deviné : requis
    longitude_enfant: float     # jamais deviné : requis
    utc_offset_enfant: Optional[float] = None
    annee_enfant: Optional[int] = None   # défaut : année courante, sans signification d'hérédité
    mutation_rate: float = 0.10


@app.post("/genome/croiser", tags=["genome"])
async def genome_croiser(body: Croisement, _cle: str = Depends(cle_api)):
    """Croise 2 profils cosmiques (via `personnages`) pour produire un enfant au
    thème astronomiquement réel, avec un récit d'hérédité en post-traitement
    (comparaison des 10 corps aux 2 parents — coïncidence assumée, pas une vraie
    génétique astrale)."""
    try:
        ra = await personnages_client.portrait(body.parent_a.model_dump())
        rb = await personnages_client.portrait(body.parent_b.model_dump())
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if ra.status_code != 200:
        raise HTTPException(ra.status_code, f"Parent A : {ra.json().get('detail', ra.text)}")
    if rb.status_code != 200:
        raise HTTPException(rb.status_code, f"Parent B : {rb.json().get('detail', rb.text)}")
    theme_a, theme_b = ra.json(), rb.json()

    description, mutation_survenue = fusion.fusionner_description(
        theme_a, theme_b, body.mutation_rate, Random())

    try:
        rri = await personnages_client.recherche_inverse(description)
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if rri.status_code != 200:
        raise HTTPException(rri.status_code, f"Recherche inverse : {rri.json().get('detail', rri.text)}")
    signes = rri.json().get("signes") or []
    if not signes:
        raise HTTPException(422, "Impossible de dériver un signe pour l'enfant à partir "
                                  "de cette description fusionnée.")

    annee = body.annee_enfant or date.today().year
    date_enfant = fusion.date_pour_signe(signes[0]["signe"], annee)

    fiche_enfant = {
        "prenoms": body.prenoms_enfant, "nom": body.nom_enfant,
        "date_naissance": date_enfant, "heure_naissance": None,
        "latitude": body.latitude_enfant, "longitude": body.longitude_enfant,
        "utc_offset": body.utc_offset_enfant,
    }
    try:
        re_ = await personnages_client.portrait(fiche_enfant)
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if re_.status_code != 200:
        raise HTTPException(re_.status_code, f"Enfant : {re_.json().get('detail', re_.text)}")
    theme_enfant = re_.json()

    heredite = fusion.comparer_dix_corps(
        theme_enfant["theme_complet"]["dix_corps"],
        theme_a["theme_complet"]["dix_corps"],
        theme_b["theme_complet"]["dix_corps"])

    return {"parentA": theme_a, "parentB": theme_b, "description_genome": description,
            "enfant": theme_enfant, "heredite": heredite, "mutation_survenue": mutation_survenue}
