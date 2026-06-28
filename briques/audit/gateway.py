"""Client Gateway de la brique audit — fin adaptateur sur shared.llm_client (S118).

Ne garde que le prompt système métier ; tout le reste (backoff, extraction JSON,
réglages Gateway) vit dans shared/llm_client.py, partagé avec le générateur.
"""
from shared.llm_client import appeler_json

SYSTEM_PROMPT = (
    "Tu es un consultant senior en transformation d'entreprise. Tu analyses des documents "
    "fournis et tu produis une réponse UNIQUEMENT en JSON valide, sans markdown, "
    "sans explication autour du JSON. Si une information est absente des documents, "
    "tu mets null ou une liste vide — tu n'inventes JAMAIS."
)


async def appeler_llm(user: str) -> dict:
    """Appelle le Gateway avec le prompt système de l'audit et renvoie le JSON parsé."""
    return await appeler_json(user, system_prompt=SYSTEM_PROMPT, temperature=0.1)
