"""Orchestration des campagnes de prospection (S193). À la cadence horloge (déclarée dans
manifest.json), pour chaque personne ayant au moins une campagne active : appelle `geo`
(prospects enrichis d'une zone existante) → pousse au CRM `forge` → pousse un résumé dans
`memoire` (espace "veille", wing "veille-prospection", isolé par personne).

Dégradation : `geo` injoignable ⇒ rien à faire pour cette campagne, erreur journalisée.
`forge`/`memoire` injoignables APRÈS un succès `geo` ⇒ ne font JAMAIS perdre les prospects
(déjà persistés côté `geo`) ni planter le traitement des autres campagnes — `memoire` est
strictement best-effort (jamais dans le chemin critique)."""
from __future__ import annotations

import logging
import os

import httpx

import stockage

logger = logging.getLogger(__name__)


def _url(env: str, defaut: str) -> str:
    return os.getenv(env, defaut).rstrip("/")


def _entetes(cle_env: str, user_id: str | None = None) -> dict:
    entetes: dict = {}
    cle = os.getenv(cle_env, "")
    if cle:
        entetes["X-API-Key"] = cle
    if user_id:
        entetes["X-User-Id"] = user_id
    return entetes


def _appeler_geo(zone_id: str) -> dict:
    base = _url("GEO_URL", "http://host.docker.internal:6110")
    r = httpx.post(f"{base}/prospection/enrichir-lot", json={"zone_id": zone_id},
                   headers=_entetes("GEO_KEY"), timeout=180)
    r.raise_for_status()
    return r.json()


def _appeler_forge(prospects: list[dict]) -> dict:
    base = _url("FORGE_URL", "http://host.docker.internal:5700")
    r = httpx.post(f"{base}/crm/import-lot", json={"prospects": prospects},
                   headers=_entetes("FORGE_KEY"), timeout=60)
    r.raise_for_status()
    return r.json()


def _pousser_memoire(user_id: str, contenu: str) -> None:
    """Best-effort strict : un échec ici ne remonte JAMAIS à l'appelant.

    `user_id` est le tenant interne (`f"perso:{x_user_id}"`, motif `tenant_actuel`),
    utilisé tel quel dans NOTRE stockage. Mais `memoire` isole par personne via l'espace
    `f"{espace}-{utilisateur}"` où `utilisateur` est le X-User-Id BRUT que lui envoie le
    Cœur (sans préfixe, cf. `core/contexte_tenant.py::entetes_par_personne`) — on retire
    donc le préfixe `perso:` avant de le transmettre à `memoire`, sinon le souvenir atterrit
    dans un espace (`veille-perso:xxx`) que le chemin de rappel du Cœur ne lit jamais."""
    identite = user_id.removeprefix("perso:")
    base = _url("MEMOIRE_URL", "http://host.docker.internal:5600")
    try:
        r = httpx.post(f"{base}/retenir",
                       json={"contenu": contenu, "titre": "Prospection", "espace": "veille",
                             "wing": "veille-prospection"},
                       headers=_entetes("MEMOIRE_KEY", identite), timeout=30)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001 — jamais bloquant
        logger.warning("Veille-prospection push mémoire (user=%s) : %s", user_id, e)


def _executer_campagne(campagne: dict) -> dict:
    """Exécute UNE campagne. Ne lève jamais : les erreurs sont journalisées dans le
    décompte renvoyé, jamais propagées à l'appelant (une campagne en échec ne doit pas
    empêcher le traitement des autres)."""
    try:
        rapport_geo = _appeler_geo(campagne["zone_id"])
    except httpx.HTTPError as e:
        return {"trouves": 0, "deja_connus": 0, "nouveaux_crm": 0, "erreur": str(e)}

    prospects = rapport_geo.get("prospects", [])
    deja_connus = rapport_geo.get("compte", {}).get("deja_enrichi", 0)
    nouveaux_crm, erreur = 0, None
    if prospects:
        try:
            rapport_forge = _appeler_forge(prospects)
            nouveaux_crm = rapport_forge.get("crees", 0)
        except httpx.HTTPError as e:
            erreur = str(e)
        _pousser_memoire(
            campagne["user_id"],
            f"Campagne de prospection : {len(prospects)} prospect(s) trouvé(s), "
            f"{nouveaux_crm} nouveau(x) au CRM ({deja_connus} déjà connu(s)).")

    return {"trouves": len(prospects), "deja_connus": deja_connus,
            "nouveaux_crm": nouveaux_crm, "erreur": erreur}


def _executer_campagne_sans_planter(campagne: dict) -> bool:
    """Enrobe `_executer_campagne` et les appels `stockage.*` qui suivent : une panne
    inattendue (ex. corruption JSON de `geo`, ou une erreur SQLite imprévisible) est
    journalisée et comptée comme « campagne traitée (sans succès) », jamais propagée.
    Contrainte du plan : « Aucun échec ne doit faire planter le pipeline d'orchestration » —
    plus large que les pannes HTTP déjà gérées dans `_executer_campagne`."""
    try:
        resultat = _executer_campagne(campagne)
        stockage.inserer_execution(campagne["id"], **resultat)
        stockage.maj_derniere_execution(campagne["id"])
        return True
    except Exception as e:  # noqa: BLE001 — une campagne en échec inattendu ne doit jamais arrêter le lot
        logger.warning("Veille-prospection échec inattendu (campagne_id=%s, user_id=%s) : %s",
                       campagne["id"], campagne.get("user_id"), e)
        return False


def executer_campagnes(user_ids: list[str] | None = None) -> dict:
    """Point d'entrée horloge : traite toutes les campagnes actives de toutes les
    personnes, ou seulement `user_ids` si fourni (motif `digest.py` de `veille-info` — la
    route HTTP réelle ne le fournit JAMAIS)."""
    cibles = user_ids if user_ids is not None else stockage.lister_user_ids_actifs()
    campagnes_executees = 0
    for user_id in cibles:
        for campagne in stockage.lister_campagnes(user_id, actives_seulement=True):
            if _executer_campagne_sans_planter(campagne):
                campagnes_executees += 1
    return {"campagnes_executees": campagnes_executees}
