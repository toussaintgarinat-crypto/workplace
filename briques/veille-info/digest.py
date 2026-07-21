"""Pipeline quotidien de la brique veille-info. Orchestration pure : fetch RSS pour chaque
personne ayant des sources actives → dédup → résumé LLM consolidé si nouveautés → digest
idempotent par (user_id, date). Ne lève jamais : toute panne (source injoignable, Gateway
indisponible) est journalisée et l'utilisateur suivant continue d'être traité."""
from __future__ import annotations

import logging

import rss
import stockage
from lib.llm_client import llm_complete

logger = logging.getLogger(__name__)

_SYSTEM = ("Tu es un assistant de veille informationnelle. Résume en français, en quelques "
          "phrases synthétiques, les nouveaux articles listés ci-dessous. Regroupe par thème "
          "si pertinent, cite les points notables, reste factuel et concis.")


def _construire_prompt(articles: list[dict]) -> str:
    lignes = [f"- {a['titre']} ({a['url']})" for a in articles]
    return "Nouveaux articles du jour :\n" + "\n".join(lignes)


def _traiter_utilisateur(user_id: str) -> bool:
    """Traite un utilisateur : fetch ses sources actives, résume s'il y a du nouveau.
    Renvoie True si un digest a été créé."""
    if stockage.digest_existe(user_id):
        return False

    for source in stockage.lister_sources(user_id, actives_seulement=True):
        try:
            texte = rss.fetcher(source["url"])
            items = rss.parser_items(texte)
        except Exception as e:  # noqa: BLE001 — une source en échec ne bloque pas les autres
            logger.warning("Veille-info fetch source %r (user=%s) : %s",
                          source["nom"], user_id, e)
            continue
        for item in items:
            stockage.inserer_article(user_id, source["id"], item["titre"], item["url"],
                                     item["published_at"])

    articles = stockage.articles_du_jour(user_id)
    if not articles:
        return False

    try:
        resume = llm_complete(_construire_prompt(articles), system=_SYSTEM)
    except Exception as e:  # noqa: BLE001 — Gateway indisponible : pas de digest partiel
        logger.warning("Veille-info résumé LLM (user=%s) : %s", user_id, e)
        return False

    stockage.inserer_digest(user_id, resume, len(articles))
    return True


def executer_digest_quotidien(user_ids: list[str] | None = None) -> dict:
    """Point d'entrée appelé par l'horloge du Cœur (ou à la main). Traite TOUTES les
    personnes ayant au moins une source active, ou seulement `user_ids` si fourni.

    `user_ids` existe pour les tests (cibler précisément un utilisateur sans toucher aux
    sources laissées par d'autres fichiers de test dans la même DB partagée) — la route HTTP
    de `main.py` ne le fournit JAMAIS, elle traite toujours tout le monde."""
    cibles = user_ids if user_ids is not None else stockage.lister_user_ids_actifs()
    digests_crees = sum(1 for uid in cibles if _traiter_utilisateur(uid))
    return {"utilisateurs_traites": len(cibles), "digests_crees": digests_crees}
