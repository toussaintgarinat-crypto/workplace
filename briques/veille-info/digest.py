"""Pipeline quotidien de la brique veille-info. Orchestration pure : fetch RSS pour chaque
personne ayant des sources actives → dédup → résumé LLM consolidé si nouveautés → digest
idempotent par (user_id, date). Ne lève jamais : toute panne (source injoignable, Gateway
indisponible) est journalisée et l'utilisateur suivant continue d'être traité."""
from __future__ import annotations

import logging
import os

import httpx
import rss
import stockage
from lib.llm_client import llm_complete

logger = logging.getLogger(__name__)

VOIX_URL = os.getenv("VOIX_URL", "http://host.docker.internal:5985")

_SYSTEM = ("Tu es un assistant de veille informationnelle. Résume en français, en quelques "
          "phrases synthétiques, les nouveaux articles listés ci-dessous. Regroupe par thème "
          "si pertinent, cite les points notables, reste factuel et concis.")


def _construire_prompt(articles: list[dict]) -> str:
    lignes = [f"- {a['titre']} ({a['url']})" for a in articles]
    return "Nouveaux articles du jour :\n" + "\n".join(lignes)


def _generer_audio(digest_id: int, texte: str) -> None:
    """Génère l'audio du digest via la brique voix (motif briques/studio/main.py:1010-1028,
    aucune clé — cohérent avec le reste du parc). Best-effort STRICT : un échec est
    journalisé, jamais propagé — le digest texte (déjà créé par l'appelant) reste utilisable
    sans audio. Pas de retry automatique dans cette version."""
    try:
        r = httpx.post(f"{VOIX_URL}/rendre", timeout=180,
                       json={"episode_id": f"veille-info-{digest_id}",
                             "segments": [{"voix": None, "texte": texte}]})
        r.raise_for_status()
        res = r.json()
        if not res.get("url"):
            logger.warning("Veille-info audio digest_id=%s : pas d'URL (place_holder=%s)",
                           digest_id, res.get("place_holder"))
            return
        stockage.inserer_audio_digest(digest_id, res["url"], res.get("duree"))
    except Exception as e:  # noqa: BLE001 — audio best-effort, le digest texte reste utilisable
        logger.warning("Veille-info audio digest_id=%s : %s", digest_id, e)


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

    articles = stockage.articles_non_digestes(user_id)
    if not articles:
        return False

    try:
        resume = llm_complete(_construire_prompt(articles), system=_SYSTEM)
    except Exception as e:  # noqa: BLE001 — Gateway indisponible : pas de digest partiel
        logger.warning("Veille-info résumé LLM (user=%s) : %s", user_id, e)
        return False

    d = stockage.inserer_digest(user_id, resume, len(articles))
    stockage.marquer_articles_digestes([a["id"] for a in articles])
    _generer_audio(d["id"], resume)
    return True


def _traiter_utilisateur_sans_planter(user_id: str) -> bool:
    """Enrobe `_traiter_utilisateur` : une panne inattendue (ex. un appel `stockage.*` qui
    lève, en dehors des deux chemins déjà gardés dans `_traiter_utilisateur`) est journalisée
    et comptée comme « pas de digest pour cette personne », jamais propagée. Contrainte du
    plan : « Aucun échec ne doit faire planter le pipeline » — plus large que les deux pannes
    déjà gérées (fetch RSS, appel LLM)."""
    try:
        return _traiter_utilisateur(user_id)
    except Exception as e:  # noqa: BLE001 — une personne en échec inattendu ne doit jamais arrêter le lot
        logger.warning("Veille-info échec inattendu (user=%s) : %s", user_id, e)
        return False


def executer_digest_quotidien(user_ids: list[str] | None = None) -> dict:
    """Point d'entrée appelé par l'horloge du Cœur (ou à la main). Traite TOUTES les
    personnes ayant au moins une source active, ou seulement `user_ids` si fourni.

    `user_ids` existe pour les tests (cibler précisément un utilisateur sans toucher aux
    sources laissées par d'autres fichiers de test dans la même DB partagée) — la route HTTP
    de `main.py` ne le fournit JAMAIS, elle traite toujours tout le monde."""
    cibles = user_ids if user_ids is not None else stockage.lister_user_ids_actifs()
    digests_crees = sum(1 for uid in cibles if _traiter_utilisateur_sans_planter(uid))
    return {"utilisateurs_traites": len(cibles), "digests_crees": digests_crees}
