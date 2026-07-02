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

Sécurité : les endpoints d'inscription/suppression (``POST/DELETE /noeuds``) exigent une
clé API valide. Posez une clé dans ``API_KEYS`` (env de la brique) ; la commande
d'auto-inscription du bootstrap l'envoie via ``X-API-Key`` (variable ``MUSCLE_KEY``
côté client — voir docker-compose.yml). En mode développement (``API_KEYS`` vide),
la brique reste ouverte.
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

import gateway_admin as gateway_admin_mod
import noeud as noeud_mod
import persistance as persistance_mod

_log = logging.getLogger("calcul")

async def _republier_parc(parc: dict) -> dict:
    """Re-pousse dans LiteLLM tous les nœuds du parc qui ont un modele_gateway.

    Idempotent : si le modèle existe déjà dans LiteLLM, l'API renvoie 200 ou 409 → ok.
    Best-effort : une erreur gateway ne plante pas l'opération (on continue les autres nœuds).
    """
    repousses = 0
    echecs = []
    for nid, n in parc.items():
        if not n.modele_gateway:
            continue
        verdict = await gateway_admin_mod.enregistrer_modele(n.modele_gateway, n.endpoint)
        if verdict["ok"]:
            repousses += 1
        else:
            echecs.append({"id": nid, "erreur": verdict.get("erreur")})
    return {"ok": True, "repousses": repousses, "echecs": echecs}


@asynccontextmanager
async def _lifespan(application: FastAPI):
    """Cycle de vie : re-push du parc dans LiteLLM au démarrage (best-effort, non bloquant)."""
    try:
        res = await _republier_parc(PARC)
        if res["repousses"] > 0:
            _log.info("calcul : %d modèle(s) re-poussé(s) dans LiteLLM au démarrage.", res["repousses"])
    except Exception as exc:  # noqa: BLE001 — tolérant au boot
        _log.warning("calcul : re-push LiteLLM au démarrage ignoré (%s).", exc)
    yield  # point de séparation startup / shutdown


app = FastAPI(
    title="Calcul — réveil & santé des nœuds de calcul",
    version="0.2.0",
    lifespan=_lifespan,
)
# Origines navigateur autorisées : liste explicite via CORS_ORIGINS (CSV). Défaut "*"
# = comportement historique. En contexte MULTI-TENANT (même local : autre tenant/
# assistant sur la machine), définir CORS_ORIGINS=http://localhost:5100,... pour
# qu'une page web tierce ne puisse pas appeler cette brique depuis le navigateur.
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}

# Parc chargé au démarrage : fusion CALCUL_NOEUDS (env) + CALCUL_PARC_FILE (fichier persisté).
# Le fichier a la priorité pour un même id → les nœuds inscrits dynamiquement via API
# survivent aux redémarrages sans que l'opérateur ait à modifier l'env.
PARC: dict = persistance_mod.charger_parc()


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


_BOOTSTRAP_PATH = Path(__file__).parent / "bootstrap.sh"


@app.get("/bootstrap.sh", tags=["système"], response_class=PlainTextResponse)
def servir_bootstrap():
    """Sert le script d'auto-inscription du muscle. Sans auth : la clé est demandée à l'exécution."""
    if not _BOOTSTRAP_PATH.exists():
        raise HTTPException(404, "bootstrap.sh introuvable sur le serveur.")
    return PlainTextResponse(_BOOTSTRAP_PATH.read_text(), media_type="text/x-sh")


@app.get("/sante", tags=["système"])
def sante():
    """État de la brique : nombre de nœuds déclarés + leurs états connus (sans re-sonder)."""
    return {
        "ok": True, "service": "calcul", "version": "0.2.0",
        "noeuds": len(PARC),
        "etats": {nid: n.etat for nid, n in PARC.items()},
    }


@app.get("/noeuds", tags=["nœuds"])
def lister_noeuds(_cle: str = Depends(cle_api)):
    """Liste les nœuds déclarés avec leur dernier état connu (n'effectue PAS de sonde)."""
    return {"noeuds": [n.vue_publique() for n in PARC.values()]}


@app.post("/noeuds", tags=["nœuds"])
async def inscrire_noeud(
    descripteur: Dict[str, Any] = Body(...),
    _cle: str = Depends(cle_api),
):
    """Inscrit (ou réinscrit) un nœud de calcul : valide, sonde LIVE, persiste, renvoie la vue publique.

    Honnêteté : le nœud est refusé s'il ne répond pas à la sonde au moment de l'inscription.
    Idempotent : réinscrire un id existant le met à jour sans créer de doublon (étape 4 S131).
    Corps attendu : même format qu'un item ``CALCUL_NOEUDS`` (``id`` + ``endpoint`` obligatoires).
    """
    try:
        n = noeud_mod.Noeud.from_dict(descripteur)
    except ValueError as exc:
        raise HTTPException(422, f"Descripteur invalide : {exc}")

    ok = await noeud_mod.sonder(n)
    if not ok:
        raise HTTPException(
            422,
            f"Nœud refusé : la sonde n'a obtenu aucune réponse de {n.endpoint!r} "
            f"(état : {n.etat!r}). Vérifiez que le service LLM tourne et est joignable "
            "depuis cette brique avant de l'inscrire.",
        )

    PARC[n.id] = n
    persistance_mod.sauver_noeud(n)

    # Enregistrement dans le Gateway — best-effort, ne bloque pas l'inscription.
    if n.modele:
        nom_gateway = n.modele_gateway or f"ollama/{n.modele}"
        verdict = await gateway_admin_mod.enregistrer_modele(nom_gateway, n.endpoint)
        if verdict["ok"]:
            n.modele_gateway = verdict.get("model_name") or nom_gateway
            persistance_mod.sauver_noeud(n)
        else:
            _log.warning(
                "calcul : enregistrement gateway ignoré pour %r (%s).",
                n.id, verdict.get("erreur"),
            )

    return n.vue_publique()


@app.post("/noeuds/republier", tags=["nœuds", "système"])
async def republier_parc(_cle: str = Depends(cle_api)):
    """Re-pousse dans LiteLLM tous les modèles du parc (idempotent). Utile après redémarrage."""
    return await _republier_parc(PARC)


@app.delete("/noeuds/{nid}", tags=["nœuds"])
def retirer_noeud_api(nid: str, _cle: str = Depends(cle_api)):
    """Retire un nœud du parc actif et du fichier persisté. 404 si inconnu."""
    if nid not in PARC:
        raise HTTPException(404, f"Nœud inconnu : {nid!r}")
    del PARC[nid]
    persistance_mod.retirer_noeud(nid)
    return {"ok": True, "id": nid, "retire": True}


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
    """Recharge le parc depuis CALCUL_NOEUDS + fichier persisté (vue fusionnée complète)."""
    global PARC
    PARC = persistance_mod.charger_parc()
    return {"ok": True, "noeuds": len(PARC)}
