"""Brique « calcul » — partage de puissance de calcul (« le Muscle »).

Gère le CYCLE DE VIE d'un ou plusieurs nœuds de calcul distants (typiquement un Mac
Apple Silicon à grosse RAM unifiée) servant un LLM derrière un endpoint
OpenAI-compatible : savoir s'ils sont prêts, et les RÉVEILLER à la demande
(Wake-on-LAN et/ou wake-ping mesh). Cette brique ne calcule rien et ne route aucune
complétion — la Gateway (LiteLLM) reste l'unique chemin LLM. Le Cœur s'en sert pour
décider s'il met le modèle local en tête de sa cascade (cf. roadmap S58b).

Souveraineté & honnêteté : aucun nœud n'est inventé ; un nœud non sondé est « inconnu »,
un réveil qui échoue le dit. La config des nœuds vient de l'env ``CALCUL_NOEUDS`` (JSON),
aucun secret en dur (motif des fournisseurs d'images / COMFY_URL).
"""
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import noeud as noeud_mod

app = FastAPI(title="Calcul — réveil & santé des nœuds de calcul", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}

# Parc chargé une fois au démarrage depuis CALCUL_NOEUDS. Rechargeable via /noeuds/recharger.
PARC: dict = noeud_mod.charger_noeuds()


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


def _noeud(nid: str) -> noeud_mod.Noeud:
    n = PARC.get(nid)
    if not n:
        raise HTTPException(404, f"Nœud inconnu : {nid!r}")
    return n


@app.get("/sante", tags=["système"])
def sante():
    """État de la brique : nombre de nœuds déclarés + leurs états connus (sans re-sonder)."""
    return {
        "ok": True, "service": "calcul", "version": "0.1.0",
        "noeuds": len(PARC),
        "etats": {nid: n.etat for nid, n in PARC.items()},
    }


@app.get("/noeuds", tags=["nœuds"])
def lister_noeuds(_cle: str = Depends(cle_api)):
    """Liste les nœuds déclarés avec leur dernier état connu (n'effectue PAS de sonde)."""
    return {"noeuds": [n.vue_publique() for n in PARC.values()]}


@app.get("/noeuds/{nid}/pret", tags=["nœuds"])
async def pret(nid: str, _cle: str = Depends(cle_api)):
    """Sonde LIVE le nœud : répond-il maintenant ? Met à jour son état au passage."""
    n = _noeud(nid)
    ok = await noeud_mod.sonder(n)
    return {"pret": ok, **n.vue_publique()}


@app.post("/noeuds/{nid}/reveiller", tags=["nœuds"])
async def reveiller(nid: str, _cle: str = Depends(cle_api)):
    """Réveille le nœud (WoL/wake-ping) puis attend qu'il réponde. Verdict honnête."""
    n = _noeud(nid)
    res = await noeud_mod.reveiller(n)
    return {**res, "id": n.id}


@app.get("/muscle", tags=["nœuds"])
async def muscle(reveiller: bool = False, _cle: str = Depends(cle_api)):
    """Élit UN muscle utilisable dans le pool (plusieurs Mac/PC possibles).

    Préfère un nœud déjà éveillé (par priorité) ; avec ``?reveiller=1``, en réveille un en
    dernier recours. Renvoie le ``modele_gateway`` à mettre en tête de cascade côté Cœur.
    Aucun muscle dispo → ``{disponible: false}`` (le Cœur retombe sur sa cascade gratuite)."""
    n = await noeud_mod.elire(PARC, reveiller_si_besoin=reveiller)
    if not n:
        return {"disponible": False,
                "noeuds": [x.vue_publique() for x in noeud_mod.ordre_election(PARC)]}
    return {"disponible": True, **n.vue_publique()}


@app.post("/noeuds/sonder", tags=["nœuds", "horloge"])
async def sonder_tous(_cle: str = Depends(cle_api)):
    """Rafraîchit l'état de TOUS les nœuds (tâche keepalive pilotée par l'horloge du Cœur)."""
    resultats = {}
    for nid, n in PARC.items():
        resultats[nid] = await noeud_mod.sonder(n)
    return {"ok": True, "sondes": resultats,
            "etats": {nid: n.etat for nid, n in PARC.items()}}


@app.post("/noeuds/recharger", tags=["système"])
def recharger(_cle: str = Depends(cle_api)):
    """Recharge le parc depuis CALCUL_NOEUDS (après changement d'env / redéploiement)."""
    global PARC
    PARC = noeud_mod.charger_noeuds()
    return {"ok": True, "noeuds": len(PARC)}
