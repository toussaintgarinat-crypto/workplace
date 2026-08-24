"""Brique « world-engine » — croisement de 2 profils cosmiques (génome cosmique).

Persiste automatiquement chaque enfant produit (SQLite, cloisonné par `cle_api`)
— voir `stockage.py`. Dépend de `personnages` (port 5900) en HTTP pour tout
calcul astral — ne duplique jamais le moteur.
"""
import asyncio
import os
from datetime import datetime, timezone
from random import Random
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

import genome_moteur
import horloge_moteur
import spatial
import stockage
import stockage_horloge
import stockage_spatial

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


class CreerMonde(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nb_cellules: int = Field(ge=10, le=2000)
    seed: Optional[int] = None


class DemarrerHorloge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intervalle_secondes: int = Field(ge=5, le=86400)


@app.post("/genome/croiser", tags=["genome"])
async def genome_croiser(body: genome_moteur.Croisement, _cle: str = Depends(cle_api)):
    """Croise 2 profils cosmiques (via `personnages`, ou un enfant déjà stocké
    référencé par id) pour produire un enfant au thème astronomiquement réel — voir
    `genome_moteur.executer_croisement` pour le détail."""
    return await genome_moteur.executer_croisement(body, _cle)


@app.get("/genome/enfants", tags=["genome"])
def genome_enfants_lister(_cle: str = Depends(cle_api)):
    return stockage.lister(_cle)


@app.get("/genome/enfants/{eid}", tags=["genome"])
def genome_enfant_lire(eid: str, _cle: str = Depends(cle_api)):
    enfant = stockage.lire(_cle, eid)
    if enfant is None:
        raise HTTPException(404, f"Enfant '{eid}' introuvable.")
    return enfant


@app.delete("/genome/enfants/{eid}", status_code=204, tags=["genome"])
def genome_enfant_supprimer(eid: str, _cle: str = Depends(cle_api)):
    if not stockage.supprimer(_cle, eid):
        raise HTTPException(404, f"Enfant '{eid}' introuvable.")
    # Purge les placements spatiaux orphelins (Sprint B) — sans ça, une rangée
    # `placements` morte survit dans stockage_spatial.py sous cet enfant_id (jamais
    # rejouée : les lectures utilisent un INNER JOIN sur `enfants` qui l'exclut déjà,
    # mais autant ne pas la laisser traîner). Pas de cloisonnement cle_api ici : cet
    # enfant_id vient d'être confirmé appartenir à _cle par stockage.supprimer()
    # ci-dessus, et placer() n'est jamais appelé avec un enfant_id d'un autre tenant.
    stockage_spatial.supprimer_placements_enfant(eid)


def _noeud_arbre(cle_api_val: str, eid: str, vus: set[str] | None = None) -> dict | None:
    """Reconstruit récursivement la lignée d'un enfant stocké. S'arrête dès qu'un
    parent est absent (fiche brute d'origine, ou enfant stocké supprimé entre-temps
    — les deux cas sont indistinguables et traités pareil : branche `null`).

    La chaîne de parenté est un DAG par construction (ids uuid4, arêtes remontant
    toujours vers le passé — donc acyclique), PAS un arbre : un même ancêtre peut
    être atteignable par plusieurs chemins (ex. deux enfants croisés qui partagent
    un grand-parent, ou même parent_a == parent_b). `vus` mémoïse les ids déjà
    développés dans CE parcours pour éviter une ré-expansion exponentielle du
    même sous-arbre et pour ne jamais présenter un même ancêtre comme s'il
    s'agissait de personnes distinctes. Un ancêtre déjà développé ailleurs revient
    en stub `{"id":..., "prenoms":..., "nom":..., "deja_present": True}` — jamais
    en `None` : les deux ont un sens différent pour l'appelant (`None` = pas
    d'ancêtre stocké au-delà de ce point, stub = ancêtre stocké mais déjà montré
    ailleurs dans cet arbre)."""
    vus = set() if vus is None else vus
    enfant = stockage.lire(cle_api_val, eid)
    if enfant is None:
        return None
    if eid in vus:
        return {"id": enfant["id"], "prenoms": enfant["prenoms"], "nom": enfant["nom"],
                "deja_present": True}
    vus.add(eid)
    return {
        "id": enfant["id"], "prenoms": enfant["prenoms"], "nom": enfant["nom"],
        "parent_a": _noeud_arbre(cle_api_val, enfant["parent_a_id"], vus) if enfant["parent_a_id"] else None,
        "parent_b": _noeud_arbre(cle_api_val, enfant["parent_b_id"], vus) if enfant["parent_b_id"] else None,
    }


@app.get("/genome/arbre/{eid}", tags=["genome"])
def genome_arbre_lire(eid: str, _cle: str = Depends(cle_api)):
    noeud = _noeud_arbre(_cle, eid)
    if noeud is None:
        raise HTTPException(404, f"Enfant '{eid}' introuvable.")
    return noeud


@app.post("/spatial/mondes", tags=["spatial"])
def spatial_monde_creer(body: CreerMonde, _cle: str = Depends(cle_api)):
    """Génère et persiste un nouveau monde : maillage Voronoï, biomes/ressources
    dérivés d'un bruit cohérent. `seed` généré si absent (renvoyé dans la réponse,
    même (nb_cellules, seed) ⇒ même monde). Un monde a TOUJOURS une horloge
    (Sprint C), en tick manuel par défaut."""
    seed = body.seed if body.seed is not None else Random().randrange(2**31)
    cellules = spatial.generer_monde(body.nb_cellules, seed)
    monde = stockage_spatial.creer_monde(_cle, cellules, seed)
    stockage_horloge.initialiser_horloge(monde["id"])
    return monde


@app.post("/spatial/mondes/{mid}/forker", tags=["spatial"])
def spatial_monde_forker(mid: str, _cle: str = Depends(cle_api)):
    """Clone un monde existant (cellules + enfants placés) sous un nouvel id
    indépendant. Le monde source n'est jamais modifié. L'horloge du fork reprend
    le tick du monde source mais reste inactive (Sprint C)."""
    nouveau = stockage_spatial.forker_monde(_cle, mid)
    if nouveau is None:
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    stockage_horloge.copier_pour_fork(mid, nouveau["id"])
    return nouveau


@app.get("/spatial/mondes", tags=["spatial"])
def spatial_mondes_lister(_cle: str = Depends(cle_api)):
    return stockage_spatial.lister_mondes(_cle)


@app.get("/spatial/mondes/{mid}", tags=["spatial"])
def spatial_monde_lire(mid: str, _cle: str = Depends(cle_api)):
    monde = stockage_spatial.lire_monde(_cle, mid)
    if monde is None:
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    return monde


@app.get("/spatial/mondes/{mid}/cellules/{cid}", tags=["spatial"])
def spatial_cellule_lire(mid: str, cid: int, _cle: str = Depends(cle_api)):
    cellule = stockage_spatial.lire_cellule(_cle, mid, cid)
    if cellule is None:
        raise HTTPException(404, f"Cellule '{cid}' du monde '{mid}' introuvable.")
    return cellule


@app.delete("/spatial/mondes/{mid}", status_code=204, tags=["spatial"])
def spatial_monde_supprimer(mid: str, _cle: str = Depends(cle_api)):
    if not stockage_spatial.supprimer_monde(_cle, mid):
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    stockage_horloge.supprimer_pour_monde(mid)


@app.post("/horloge/{mid}/tick", tags=["horloge"])
async def horloge_tick(mid: str, _cle: str = Depends(cle_api)):
    """Avance manuellement ce monde d'exactement 1 tick (1 an narratif) — voir
    `horloge_moteur.executer_tick` pour le détail de la mécanique."""
    if not stockage_spatial.monde_existe(_cle, mid):
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    return await horloge_moteur.executer_tick(mid, _cle)


@app.post("/horloge/{mid}/demarrer", tags=["horloge"])
def horloge_demarrer(mid: str, body: DemarrerHorloge, _cle: str = Depends(cle_api)):
    """Active l'avancement automatique de ce monde (scheduler in-process, opt-in).
    Un monde nouvellement créé ou forké reste en tick manuel tant que cet endpoint
    n'est pas appelé."""
    if not stockage_spatial.monde_existe(_cle, mid):
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    stockage_horloge.demarrer(mid, body.intervalle_secondes)
    return stockage_horloge.lire_horloge(mid)


@app.post("/horloge/{mid}/arreter", tags=["horloge"])
def horloge_arreter(mid: str, _cle: str = Depends(cle_api)):
    """Désactive l'avancement automatique (les ticks déjà passés restent acquis)."""
    if not stockage_spatial.monde_existe(_cle, mid):
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    stockage_horloge.arreter(mid)
    return stockage_horloge.lire_horloge(mid)


@app.get("/horloge/{mid}", tags=["horloge"])
def horloge_lire(mid: str, _cle: str = Depends(cle_api)):
    if not stockage_spatial.monde_existe(_cle, mid):
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    return stockage_horloge.lire_horloge(mid)


SCHEDULER_INTERVALLE_S = int(os.getenv("HORLOGE_SCHEDULER_INTERVALLE_S", "5"))
_SCHEDULER_ACTIF = os.getenv("HORLOGE_SCHEDULER_DESACTIVE", "").strip() != "1"


async def _boucle_scheduler():
    """Tâche de fond in-process (pas de queue externe — volume modéré visé ce
    sprint, voir design). Vérifie périodiquement les horloges actives dont
    l'intervalle est écoulé et déclenche leur tick. Une erreur sur un monde
    n'interrompt jamais la boucle ni les autres mondes."""
    while True:
        await asyncio.sleep(SCHEDULER_INTERVALLE_S)
        maintenant = datetime.now(timezone.utc).isoformat()
        try:
            dues = stockage_horloge.horloges_actives_a_declencher(maintenant)
        except Exception:
            continue
        for due in dues:
            try:
                await horloge_moteur.executer_tick(due["monde_id"], due["cle_api"])
            except Exception:
                continue


@app.on_event("startup")
async def _demarrer_scheduler():
    if _SCHEDULER_ACTIF:
        asyncio.create_task(_boucle_scheduler())
