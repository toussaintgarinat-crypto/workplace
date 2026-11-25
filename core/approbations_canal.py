"""Canal d'envoi des approbations vers la brique `connexion` (Telegram) — S245.

Best-effort : une brique injoignable ne doit JAMAIS faire échouer ni l'exécution d'un outil
ni une décision déjà enregistrée. Le code à 6 chiffres d'un destructif n'est JAMAIS envoyé ici :
il ne vit que dans l'app (GET /approbations/en_attente)."""
import logging
import os

import httpx

import approbations
import orchestrateur

logger = logging.getLogger(__name__)

_ICONES = {"approuvee": "✅ Approuvée", "refusee": "❌ Refusée", "expiree": "⌛ Expirée",
           "executee": "✅ Exécutée", "echec": "⚠️ Échec"}


def charge_notification(demande: dict, relance: bool = False) -> dict:
    prerequis = demande.get("prerequis") or {}
    return {"id": demande["id"], "resume": demande["resume"],
            "sensibilite": demande["sensibilite"],
            "prerequis_ok": all(prerequis.values()) if prerequis else True,
            "relance": relance, "expire_a": demande["expire_a"]}


def texte_final(demande: dict) -> str:
    etat = _ICONES.get(demande["statut"], demande["statut"])
    par = f" par {demande['decide_par']}" if demande.get("decide_par") else ""
    return f"{etat}{par}\n{demande['resume']}"


async def _poster(registre, chemin: str, corps: dict) -> dict:
    base = orchestrateur._brique_base(registre, "connexion")
    entetes = {}
    cle = os.getenv("CONNEXION_KEY", "")
    if cle:
        entetes["X-API-Key"] = cle
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{base}{chemin}", json=corps, headers=entetes)
        r.raise_for_status()
        return r.json()


async def notifier(registre, demande: dict, relance: bool = False) -> None:
    try:
        rep = await _poster(registre, "/approbation/notifier",
                            charge_notification(demande, relance))
        messages = rep.get("messages") or []
        if messages and demande.get("id"):
            approbations.enregistrer_messages(demande["id"], messages)
    except Exception as ex:  # noqa: BLE001 — jamais bloquant
        logger.warning("Approbation %s : notification Telegram impossible : %s",
                       demande.get("id", "?")[:8], ex)


async def mettre_a_jour(registre, demande: dict) -> None:
    """Édite les messages Telegram vers l'état final (✅ / ❌ / ⌛)."""
    if not demande.get("messages") or demande.get("statut") == "en_attente":
        return
    try:
        await _poster(registre, "/approbation/mettre_a_jour",
                      {"messages": demande["messages"], "texte": texte_final(demande)})
    except Exception as ex:  # noqa: BLE001
        logger.warning("Approbation %s : mise à jour Telegram impossible : %s",
                       demande.get("id", "?")[:8], ex)
