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

# Nombre de fetchs consécutifs en échec au-delà duquel une source est considérée MORTE
# (flux supprimé, domaine expiré, feed passé en 405). Le digest tournant une fois par jour,
# 5 ≈ cinq jours : assez pour ne pas s'alarmer d'une coupure réseau passagère.
_SEUIL_SOURCE_EN_PANNE = int(os.getenv("VEILLE_SEUIL_SOURCE_EN_PANNE", "5"))

_SYSTEM = ("Tu es un assistant de veille informationnelle. Résume en français, en quelques "
          "phrases synthétiques, les nouveaux articles listés ci-dessous. Regroupe par thème "
          "si pertinent, cite les points notables, reste factuel et concis.")


def _construire_prompt(articles: list[dict]) -> str:
    lignes = [f"- {a['titre']} ({a['url']})" for a in articles]
    return "Nouveaux articles du jour :\n" + "\n".join(lignes)


def _pousser_memoire(user_id: str, resume: str, date: str) -> None:
    """Best-effort strict (S193) : un échec ici ne doit JAMAIS faire perdre le digest texte
    déjà créé, ni empêcher le traitement des autres personnes — même filet que l'audio
    (leçon S189 : tout ce qui suit un succès reste dans le même try/except).

    `user_id` est le tenant interne (`f"perso:{x_user_id}"`, motif `tenant_actuel`), utilisé
    tel quel dans NOTRE stockage. Mais `memoire` isole par personne via l'espace
    `f"{espace}-{utilisateur}"` où `utilisateur` est le X-User-Id BRUT que lui envoie le
    Cœur (sans préfixe, cf. `core/contexte_tenant.py::entetes_par_personne`) — on retire
    donc le préfixe `perso:` avant de le transmettre à `memoire`, sinon le résumé atterrit
    dans un espace (`veille-perso:xxx`) que le chemin de rappel du Cœur ne lit jamais."""
    identite = user_id.removeprefix("perso:")
    base = os.getenv("MEMOIRE_URL", "http://host.docker.internal:5600").rstrip("/")
    entetes = {"X-User-Id": identite}
    cle = os.getenv("MEMOIRE_KEY", "")
    if cle:
        entetes["X-API-Key"] = cle
    try:
        r = httpx.post(f"{base}/retenir",
                       json={"contenu": resume, "titre": f"Veille du {date}",
                             "espace": "veille", "wing": "veille-info"},
                       headers=entetes, timeout=30)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001 — jamais bloquant
        logger.warning("Veille-info push mémoire (user=%s) : %s", user_id, e)


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


def _traiter_utilisateur(user_id: str, thematique_forcee: str | None = None) -> int:
    """Traite un utilisateur : fetch ses sources actives, résume PAR THÉMATIQUE s'il y a du
    nouveau (S199 — une thématique = un groupe de sources partageant `sources.thematique`,
    "" = thématique par défaut). Renvoie le nombre de digests créés (0, 1, ou plusieurs).

    `thematique_forcee` (S200 — génération ponctuelle depuis l'atelier) : si fourni, ne
    traite QUE cette thématique — et fetche ses sources même si elles sont en pause
    (`stockage.lister_sources_thematique`, pas `lister_sources(actives_seulement=True)`),
    pour ne pas produire un digest vide sur une thématique en pause depuis longtemps."""
    if thematique_forcee is not None:
        thematiques = [thematique_forcee]
        sources = stockage.lister_sources_thematique(user_id, thematique_forcee)
    else:
        thematiques = stockage.thematiques_actives(user_id)
        sources = stockage.lister_sources(user_id, actives_seulement=True)

    if thematiques and all(stockage.digest_existe(user_id, thematique=t) for t in thematiques):
        return 0  # tout est déjà fait aujourd'hui : pas la peine de fetcher (motif historique)

    for source in sources:
        try:
            texte = rss.fetcher(source["url"])
            items = rss.parser_items(texte)
        except Exception as e:  # noqa: BLE001 — une source en échec ne bloque pas les autres
            echecs = stockage.enregistrer_echec_source(source["id"], str(e))
            # Au-delà du seuil, le flux est mort (404/405 depuis des semaines) : on garde la
            # trace en base — l'atelier l'affiche — mais on cesse de crier à chaque digest,
            # sinon un feed disparu noie les vrais incidents dans les logs.
            if echecs == _SEUIL_SOURCE_EN_PANNE:
                logger.error("Veille-info source %r (user=%s) en panne depuis %d fetchs "
                             "consécutifs — à corriger ou supprimer dans l'atelier : %s",
                             source["nom"], user_id, echecs, e)
            elif echecs < _SEUIL_SOURCE_EN_PANNE:
                logger.warning("Veille-info fetch source %r (user=%s) : %s",
                               source["nom"], user_id, e)
            continue
        stockage.reinitialiser_echecs_source(source["id"])
        for item in items:
            stockage.inserer_article(user_id, source["id"], item["titre"], item["url"],
                                     item["published_at"])

    digests_crees = 0
    for thematique in thematiques:
        if stockage.digest_existe(user_id, thematique=thematique):
            continue

        articles = stockage.articles_non_digestes(user_id, thematique)
        if not articles:
            continue

        try:
            resume = llm_complete(_construire_prompt(articles), system=_SYSTEM)
        except Exception as e:  # noqa: BLE001 — Gateway indisponible : pas de digest partiel
            logger.warning("Veille-info résumé LLM (user=%s, thematique=%r) : %s",
                           user_id, thematique, e)
            continue

        d = stockage.inserer_digest(user_id, resume, len(articles), thematique=thematique)
        try:
            stockage.marquer_articles_digestes([a["id"] for a in articles])
            _generer_audio(d["id"], resume)
            _pousser_memoire(user_id, resume, d["date"])
        except Exception as e:  # noqa: BLE001 — le digest (déjà créé ci-dessus) doit compter
            # comme créé même si le marquage des articles ou l'audio échoue ensuite (même
            # filet que l'ancienne version mono-digest, cf. commentaire d'origine préservé
            # dans l'historique git).
            logger.warning("Veille-info marquage articles/audio (user=%s, digest_id=%s) : %s",
                           user_id, d["id"], e)
        digests_crees += 1
    return digests_crees


def _traiter_utilisateur_sans_planter(user_id: str, thematique_forcee: str | None = None) -> int:
    """Enrobe `_traiter_utilisateur` : une panne inattendue (ex. un appel `stockage.*` qui
    lève, en dehors des chemins déjà gardés dans `_traiter_utilisateur`) est journalisée
    et compte 0 digest créé pour cette personne, jamais propagée."""
    try:
        return _traiter_utilisateur(user_id, thematique_forcee)
    except Exception as e:  # noqa: BLE001 — une personne en échec inattendu ne doit jamais arrêter le lot
        logger.warning("Veille-info échec inattendu (user=%s) : %s", user_id, e)
        return 0


def executer_digest_quotidien(user_ids: list[str] | None = None,
                              thematique: str | None = None) -> dict:
    """Point d'entrée appelé par l'horloge du Cœur (ou à la main). Traite TOUTES les
    personnes ayant au moins une source active, ou seulement `user_ids` si fourni.

    `thematique` (S200 — génération ponctuelle depuis l'atelier) : si fourni SANS `user_ids`,
    les cibles sont calculées via `stockage.lister_user_ids_thematique` (inclut les personnes
    dont cette thématique est en pause), pas `lister_user_ids_actifs`. `user_ids` reste
    prioritaire quand fourni (chemin réservé aux tests, cf. commentaire historique) — la
    route HTTP de `main.py` ne le fournit JAMAIS."""
    if user_ids is not None:
        cibles = user_ids
    elif thematique is not None:
        cibles = stockage.lister_user_ids_thematique(thematique)
    else:
        cibles = stockage.lister_user_ids_actifs()
    digests_crees = sum(_traiter_utilisateur_sans_planter(uid, thematique) for uid in cibles)
    return {"utilisateurs_traites": len(cibles), "digests_crees": digests_crees}
