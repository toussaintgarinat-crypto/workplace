import json
import logging

from gateway import appeler_llm
from prompts import prompt_territoire, prompt_flux, prompt_problemes, prompt_priorites

logger = logging.getLogger(__name__)

LIMITE_CONTEXTE = 12000


def _tronquer(textes: list[str]) -> str:
    joint = "\n\n---\n\n".join(textes)
    return joint[:LIMITE_CONTEXTE]


def _serialiser(obj: dict | None) -> str:
    if obj is None:
        return "{}"
    return json.dumps(obj, ensure_ascii=False)


async def auditer(textes: list[str], nom_entreprise: str) -> dict:
    """Lance les 4 couches d'analyse séquentiellement."""
    contexte = _tronquer(textes)

    territoire = await _analyser_couche(
        "territoire",
        prompt_territoire(contexte),
    )

    flux = await _analyser_couche(
        "flux",
        prompt_flux(contexte, _serialiser(territoire)),
    )

    problemes = await _analyser_couche(
        "problemes",
        prompt_problemes(contexte, _serialiser(territoire), _serialiser(flux)),
    )

    priorites = await _analyser_couche(
        "priorites",
        prompt_priorites(
            contexte,
            _serialiser(territoire),
            _serialiser(flux),
            _serialiser(problemes),
        ),
    )

    return {
        "territoire": territoire,
        "flux": flux,
        "problemes": problemes,
        "priorites": priorites,
    }


async def _analyser_couche(nom: str, prompt: str) -> dict | None:
    """Appelle le LLM pour une couche, avec 1 retry en cas d'échec JSON."""
    for tentative in range(2):
        try:
            return await appeler_llm(prompt)
        except Exception as e:
            logger.warning(f"Couche {nom} tentative {tentative + 1} échouée : {e}")
            if tentative == 1:
                logger.error(f"Couche {nom} abandonnée après 2 tentatives")
                return None
    return None
