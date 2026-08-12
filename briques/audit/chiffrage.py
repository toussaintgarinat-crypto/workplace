"""Chiffrage ROI (S229) — 5e couche de l'audit, calculée à la demande via POST /chiffrer.

Le statut ('fourni_client' vs 'hypothese_llm') est décidé ICI, en Python, PAS par le LLM,
pour ne jamais dépendre de sa discipline. Idem pour l'avertissement : un littéral fixe,
jamais généré, ajouté après coup à chaque entrée.
"""
import json
import logging

from gateway import appeler_llm
from prompts import prompt_roi

logger = logging.getLogger(__name__)

AVERTISSEMENT = "Estimation à valider avec le client — non contractuelle."


async def chiffrer(territoire: dict, problemes: dict, priorites: dict,
                   cout_horaire: dict | None) -> dict | None:
    """Retourne le JSON de chiffrage, ou None si le LLM échoue après 1 retry."""
    cout_horaire = cout_horaire or {}
    prompt = prompt_roi(
        json.dumps(territoire or {}, ensure_ascii=False),
        json.dumps(problemes or {}, ensure_ascii=False),
        json.dumps(priorites or {}, ensure_ascii=False),
        json.dumps(cout_horaire, ensure_ascii=False),
    )

    resultat = None
    for tentative in range(2):
        try:
            resultat = await appeler_llm(prompt)
            break
        except Exception as e:
            logger.warning(f"Chiffrage ROI tentative {tentative + 1} échouée : {e}")

    if not resultat or not isinstance(resultat.get("problemes"), list):
        return None

    for entree in resultat["problemes"]:
        if not isinstance(entree, dict):
            continue
        pole = entree.get("pole")
        entree["statut"] = "fourni_client" if pole in cout_horaire else "hypothese_llm"
        entree["avertissement"] = AVERTISSEMENT
        if entree["statut"] == "fourni_client":
            entree["cout_horaire_estime"] = None
    return resultat
