"""Client Gateway de la brique générateur — fin adaptateur sur shared.llm_client (S118).

Ne garde que le prompt système métier et la consigne de langue ; tout le reste
(backoff, extraction JSON, réglages Gateway) vit dans shared/llm_client.py, partagé
avec l'audit.
"""
from langues import consigne_langue
from shared.llm_client import appeler_json

SYSTEM_PROMPT = (
    "Tu es un expert en design d'applications d'entreprise. Tu analyses un audit structuré "
    "et tu produis une réponse UNIQUEMENT en JSON valide, sans markdown, "
    "sans explication autour du JSON. Tu remplis tous les champs demandés — "
    "si une info est absente, tu proposes une valeur raisonnable basée sur le contexte."
)


async def appeler_llm(user: str, langue: str = "fr") -> dict:
    """Appelle le Gateway avec le prompt système du générateur (+ consigne de langue)."""
    return await appeler_json(user, system_prompt=SYSTEM_PROMPT + consigne_langue(langue),
                              temperature=0.2)
