"""Brique « world-engine » — croisement de 2 profils cosmiques (génome cosmique).

Persiste automatiquement chaque enfant produit (SQLite, cloisonné par `cle_api`)
— voir `stockage.py`. Dépend de `personnages` (port 5900) en HTTP pour tout
calcul astral — ne duplique jamais le moteur.
"""
import asyncio
import logging
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
import stockage_federation
import stockage_horloge
import stockage_spatial

_log = logging.getLogger("world-engine")

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


class CreerFederation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nom: Optional[str] = None


class RattacherPays(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monde_id: str
    nom: Optional[str] = None


class DetacherPays(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monde_id: str


class DeclarerAdjacence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monde_id_a: str
    monde_id_b: str


@app.post("/genome/croiser", tags=["genome"])
async def genome_croiser(body: genome_moteur.Croisement, _cle: str = Depends(cle_api)):
    """Croise 2 profils cosmiques (via `personnages`, ou un enfant déjà stocké
    référencé par id) pour produire un enfant au thème astronomiquement réel — voir
    `genome_moteur.executer_croisement` pour le détail."""
    return await genome_moteur.executer_croisement(body, _cle)


@app.post("/genome/fonder", tags=["genome"])
async def genome_fonder(body: genome_moteur.FondationSolo, _cle: str = Depends(cle_api)):
    """Crée un habitant fondateur sans croisement à 2 parents (pont Studio↔world-engine)
    — voir `genome_moteur.executer_fondation` pour le détail."""
    return await genome_moteur.executer_fondation(body, _cle)


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
    # Même cascade côté fédérations (correctif revue finale, Important) : sans elle,
    # un monde supprimé restait « pays membre » à jamais dans GET /federation/{id},
    # avec ses adjacences — et les ticks continuaient de le proposer en destination.
    stockage_federation.detacher_pays_de_toutes_federations(mid)


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


def _federation_visible(federation_id: str, cle_api_val: str) -> dict | None:
    """Créateur OU tout propriétaire d'au moins un pays membre peuvent VOIR une
    fédération (voir design) — dérivé directement de `lire_federation` (déjà lu
    intégralement), pas d'une requête `membre()` séparée.

    ⚠️ Renvoie la fédération COMPLÈTE, `createur_cle_api` et `cle_api` par pays
    inclus : ces champs sont la matière même du contrôle de permission ci-dessous.
    Ils ne doivent JAMAIS ressortir tels quels dans une réponse HTTP — voir
    `_federation_publique`, appliquée systématiquement APRÈS ce contrôle."""
    federation = stockage_federation.lire_federation(federation_id)
    if federation is None:
        return None
    if (federation["createur_cle_api"] != cle_api_val
            and not any(p["cle_api"] == cle_api_val for p in federation["pays"])):
        return None
    return federation


def _federation_publique(federation: dict) -> dict:
    """Vue HTTP d'une fédération : les `cle_api` brutes sont RETIRÉES (correctif
    revue finale, Critical).

    `createur_cle_api` et le `cle_api` de chaque pays sont les VRAIES clés
    d'authentification (`X-API-Key`) de leurs propriétaires. Une fédération étant
    multi-tenant par construction (voir design), les exposer permettait à
    n'importe quel membre de lire la clé du créateur ou d'un autre membre et
    d'usurper complètement ce tenant (créer/lire/supprimer ses mondes et ses
    enfants) — contournement total du cloisonnement.

    Le stockage (`stockage_federation.lire_federation`) garde volontairement ces
    champs : la logique interne (permissions, `_federation_visible`) en a besoin.
    Seule la vue HTTP les efface, une fois la permission déjà vérifiée."""
    return {
        "id": federation["id"], "nom": federation["nom"], "cree_le": federation["cree_le"],
        "pays": [{"monde_id": p["monde_id"], "nom": p["nom"], "rattache_le": p["rattache_le"]}
                 for p in federation["pays"]],
        "adjacences": federation["adjacences"],
    }


@app.post("/federation", tags=["federation"])
def federation_creer(body: CreerFederation, _cle: str = Depends(cle_api)):
    """La réponse ne réémet jamais `createur_cle_api` (= la clé de l'appelant) —
    voir `_federation_publique`."""
    federation = stockage_federation.creer_federation(_cle, body.nom)
    return {"id": federation["id"], "nom": federation["nom"], "cree_le": federation["cree_le"]}


@app.post("/federation/{fid}/rattacher", tags=["federation"])
def federation_rattacher(fid: str, body: RattacherPays, _cle: str = Depends(cle_api)):
    """Exige que `_cle` soit propriétaire de `body.monde_id` — seul le propriétaire
    d'un pays peut le rattacher (voir design, consentement fort)."""
    if not stockage_spatial.monde_existe(_cle, body.monde_id):
        raise HTTPException(404, f"Monde '{body.monde_id}' introuvable.")
    resultat = stockage_federation.rattacher_pays(fid, body.monde_id, _cle, body.nom)
    if resultat is None:
        raise HTTPException(404, f"Fédération '{fid}' introuvable.")
    return resultat


@app.post("/federation/{fid}/detacher", tags=["federation"])
def federation_detacher(fid: str, body: DetacherPays, _cle: str = Depends(cle_api)):
    if not stockage_federation.detacher_pays(fid, body.monde_id, _cle):
        raise HTTPException(404, f"Pays '{body.monde_id}' non membre de la fédération '{fid}' pour cette clé.")
    return {"federation_id": fid, "monde_id": body.monde_id, "detache": True}


@app.post("/federation/{fid}/adjacence", tags=["federation"])
def federation_adjacence(fid: str, body: DeclarerAdjacence, _cle: str = Depends(cle_api)):
    if body.monde_id_a == body.monde_id_b:
        raise HTTPException(422, "Un pays ne peut pas être déclaré adjacent à lui-même.")
    if not stockage_federation.membre(fid, _cle):
        raise HTTPException(404, f"Fédération '{fid}' introuvable ou vous n'y êtes pas membre.")
    resultat = stockage_federation.declarer_adjacence(fid, body.monde_id_a, body.monde_id_b)
    if resultat is None:
        raise HTTPException(404, "Un des deux pays n'est pas membre de cette fédération.")
    return resultat


@app.get("/federation/{fid}", tags=["federation"])
def federation_lire(fid: str, _cle: str = Depends(cle_api)):
    federation = _federation_visible(fid, _cle)
    if federation is None:
        raise HTTPException(404, f"Fédération '{fid}' introuvable.")
    return _federation_publique(federation)


@app.get("/federation/{fid}/etat", tags=["federation"])
def federation_etat(fid: str, _cle: str = Depends(cle_api)):
    if _federation_visible(fid, _cle) is None:
        raise HTTPException(404, f"Fédération '{fid}' introuvable.")
    return stockage_federation.population_vivante_federation(fid)


@app.get("/federation", tags=["federation"])
def federation_lister(_cle: str = Depends(cle_api)):
    """`createur_cle_api` retiré de chaque entrée — voir `_federation_publique`."""
    return [{"id": f["id"], "nom": f["nom"], "cree_le": f["cree_le"]}
            for f in stockage_federation.lister_federations(_cle)]


@app.delete("/federation/{fid}", status_code=204, tags=["federation"])
def federation_supprimer(fid: str, _cle: str = Depends(cle_api)):
    if not stockage_federation.supprimer_federation(_cle, fid):
        raise HTTPException(404, f"Fédération '{fid}' introuvable.")


SCHEDULER_INTERVALLE_S = int(os.getenv("HORLOGE_SCHEDULER_INTERVALLE_S", "5"))
_SCHEDULER_ACTIF = os.getenv("HORLOGE_SCHEDULER_DESACTIVE", "").strip() != "1"


async def _executer_et_consigner(monde_id: str, cle_api_val: str) -> None:
    """Exécute un tick et consigne son issue. N'importe quelle exception est
    attrapée ici, jamais laissée remonter à `asyncio.gather` — c'est ce qui
    isole un monde en échec des autres mondes du même passage."""
    try:
        resultat = await horloge_moteur.executer_tick(monde_id, cle_api_val)
        for avertissement in resultat.get("avertissements", []):
            _log.warning("monde=%s %s", monde_id, avertissement)
    except Exception:
        _log.exception("tick en échec monde=%s", monde_id)


async def _executer_passage(dues: list[dict]) -> None:
    """Exécute tous les mondes dus d'un même passage EN PARALLÈLE — la durée
    du passage devient max(durées) au lieu de Σ(durées). Voir
    docs/superpowers/specs/2026-08-25-world-engine-sprint-e-scheduler-parallele-design.md."""
    await asyncio.gather(*(_executer_et_consigner(d["monde_id"], d["cle_api"]) for d in dues))


async def _boucle_scheduler():
    """Tâche de fond in-process (pas de queue externe — volume modéré visé ce
    sprint, voir design). Vérifie périodiquement les horloges actives dont
    l'intervalle est écoulé et déclenche leur tick."""
    while True:
        await asyncio.sleep(SCHEDULER_INTERVALLE_S)
        maintenant = datetime.now(timezone.utc).isoformat()
        try:
            dues = stockage_horloge.horloges_actives_a_declencher(maintenant)
        except Exception:
            continue
        await _executer_passage(dues)


@app.on_event("startup")
async def _demarrer_scheduler():
    if _SCHEDULER_ACTIF:
        asyncio.create_task(_boucle_scheduler())
