"""Synchronisation des modèles gratuits OpenRouter dans LiteLLM, par son API (S202).

Remplace l'ancien `briques/gateway/sync_free_models.py`, qui réécrivait
`litellm_config.yaml` et supposait un redémarrage du proxy pour être pris en compte. Deux
raisons de changer, détaillées dans l'ADR
`docs/decisions/2026-07-27-sync-modeles-gratuits-gateway.md` :

- le YAML est monté en LECTURE SEULE dans le conteneur LiteLLM ;
- LiteLLM expose `/model/new` et `/model/delete` et persiste dans sa base Postgres, donc la
  liste peut changer À CHAUD — sans redémarrage, donc sans accès au socket Docker.

Le sync est **différentiel** : il ne touche que les modèles préfixés `free/`, et laisse
strictement tranquille tout ce qui est déclaré dans le YAML (payants, `go/*`, locaux).
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

LITELLM_URL = os.getenv("LITELLM_URL", "http://gateway:4000")
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
TOP_N = int(os.getenv("FREE_MODELS_TOP_N", "12"))

PREFIXE = "free/"
_TIMEOUT = 30.0


def _entetes() -> dict:
    return {"Authorization": f"Bearer {LITELLM_MASTER_KEY}", "Content-Type": "application/json"}


def catalogue_gratuits() -> list[dict]:
    """Modèles gratuits d'OpenRouter utilisables par l'assistant, les `TOP_N` plus gros.

    Les deux filtres viennent de l'ancien script et restent indispensables : l'assistant du
    Cœur EXIGE le function-calling (`tools`) et du texte — un modèle gratuit d'image ou sans
    outils casserait la cascade au lieu de la dépanner.
    """
    r = httpx.get("https://openrouter.ai/api/v1/models",
                  headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"}, timeout=_TIMEOUT)
    r.raise_for_status()
    modeles = r.json()["data"]

    def gratuit(m: dict) -> bool:
        p = m.get("pricing", {})
        return str(p.get("prompt", "1")) == "0" and str(p.get("completion", "1")) == "0"

    def utile(m: dict) -> bool:
        sp = m.get("supported_parameters") or []
        modality = (m.get("architecture", {}) or {}).get("modality", "") or ""
        return "tools" in sp and "text" in modality

    retenus = [m for m in modeles if gratuit(m) and utile(m)]
    retenus.sort(key=lambda m: m.get("context_length", 0), reverse=True)
    return retenus[:TOP_N]


def nom_workplace(id_openrouter: str) -> str:
    """`qwen/qwen3-coder:free` → `free/qwen/qwen3-coder` (nom vu par le Cœur)."""
    parts = id_openrouter.split("/")
    fournisseur = parts[0] if len(parts) > 1 else "inconnu"
    slug = parts[-1].replace(":free", "").replace(":", "-")
    return f"{PREFIXE}{fournisseur}/{slug}"


def modeles_actuels(client: httpx.Client) -> dict[str, str]:
    """Modèles `free/*` déjà servis par LiteLLM → {nom: id interne}, pour le différentiel."""
    r = client.get(f"{LITELLM_URL}/model/info", headers=_entetes(), timeout=_TIMEOUT)
    r.raise_for_status()
    actuels = {}
    for m in r.json().get("data", []):
        nom = m.get("model_name", "")
        if nom.startswith(PREFIXE):
            actuels[nom] = (m.get("model_info") or {}).get("id", "")
    return actuels


def _params(m: dict) -> dict:
    """Paramètres LiteLLM d'un modèle gratuit.

    `timeout` court et `num_retries: 0` : les gratuits d'OpenRouter rate-limitent souvent et
    peuvent PENDRE au lieu de renvoyer un 429 rapide — mieux vaut rendre la main vite pour que
    la cascade du Cœur bascule sur le gratuit suivant, puis sur le repli payant (motif hérité
    de l'ancien script, cf. Workplace S17).
    """
    return {
        "model": f"openrouter/{m['id']}",
        "api_key": OPENROUTER_API_KEY,
        "api_base": "https://openrouter.ai/api/v1",
        "timeout": 10,
        "num_retries": 0,
    }


def synchroniser() -> dict:
    """Aligne les `free/*` de LiteLLM sur le catalogue OpenRouter du moment.

    Ne lève pas sur un échec unitaire d'ajout/suppression : un modèle récalcitrant ne doit pas
    empêcher les autres d'être synchronisés — sinon une seule anomalie fige toute la liste,
    ce qui est exactement le problème qu'on cherche à supprimer.
    """
    if not OPENROUTER_API_KEY:
        return {"statut": "ignore", "raison": "OPENROUTER_API_KEY absente"}
    if not LITELLM_MASTER_KEY:
        return {"statut": "ignore", "raison": "LITELLM_MASTER_KEY absente"}

    voulus = {nom_workplace(m["id"]): m for m in catalogue_gratuits()}
    with httpx.Client() as client:
        actuels = modeles_actuels(client)

        a_ajouter = [n for n in voulus if n not in actuels]
        a_retirer = [n for n in actuels if n not in voulus]

        ajoutes, retires, erreurs = [], [], []
        for nom in a_ajouter:
            try:
                r = client.post(f"{LITELLM_URL}/model/new", headers=_entetes(), timeout=_TIMEOUT,
                                json={"model_name": nom, "litellm_params": _params(voulus[nom])})
                r.raise_for_status()
                ajoutes.append(nom)
            except Exception as e:  # noqa: BLE001
                erreurs.append(f"ajout {nom} : {str(e)[:120]}")

        for nom in a_retirer:
            try:
                r = client.post(f"{LITELLM_URL}/model/delete", headers=_entetes(),
                                timeout=_TIMEOUT, json={"id": actuels[nom]})
                r.raise_for_status()
                retires.append(nom)
            except Exception as e:  # noqa: BLE001
                erreurs.append(f"retrait {nom} : {str(e)[:120]}")

    if erreurs:
        logger.warning("gateway-sync : %d erreur(s) — %s", len(erreurs), "; ".join(erreurs))
    logger.info("gateway-sync : %d ajouté(s), %d retiré(s), %d inchangé(s)",
                len(ajoutes), len(retires), len(voulus) - len(ajoutes))

    return {"statut": "ok", "ajoutes": ajoutes, "retires": retires,
            "inchanges": len(voulus) - len(ajoutes), "erreurs": erreurs}
