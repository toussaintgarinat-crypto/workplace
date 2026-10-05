"""Synchronisation des modèles gratuits dans LiteLLM, par son API (S202 ; sources multiples S239).

Remplace l'ancien `briques/gateway/sync_free_models.py`, qui réécrivait
`litellm_config.yaml` et supposait un redémarrage du proxy pour être pris en compte. Deux
raisons de changer, détaillées dans l'ADR
`docs/decisions/2026-07-27-sync-modeles-gratuits-gateway.md` :

- le YAML est monté en LECTURE SEULE dans le conteneur LiteLLM ;
- LiteLLM expose `/model/new` et `/model/delete` et persiste dans sa base Postgres, donc la
  liste peut changer À CHAUD — sans redémarrage, donc sans accès au socket Docker.

Le sync est **différentiel** et organisé par **source** (S239) : chaque source ne touche QUE
les modèles de son préfixe, et tout ce qui est déclaré dans le YAML (payants, `go/*`, locaux,
alias `gratuit/auto` / `forge/defaut`) reste strictement tranquille.

- `free/*` ← OpenRouter (clé requise). Le 2026-10-05, la clé du HP renvoyait 401 « User not
  found » : toute la cascade gratuite était morte d'un coup — d'où une deuxième source.
- `kilo/*` ← Kilo Code (https://api.kilo.ai/api/gateway), AUCUNE clé (S239). Ses gratuits
  peuvent journaliser les requêtes : ils sont le FILET de la cascade du Cœur, jamais sa tête.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

LITELLM_URL = os.getenv("LITELLM_URL", "http://gateway:4000")
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
TOP_N = int(os.getenv("FREE_MODELS_TOP_N", "12"))
KILO_TOP_N = int(os.getenv("KILO_TOP_N", "6"))
# Ids Kilo à écarter, séparés par des virgules (« nvidia,poolside/laguna-s ») : retirer un
# fournisseur amont dont les conditions déplaisent, sans toucher au code ni reconstruire
# l'image. Comparaison PAR SEGMENT de chemin, sur l'id sans sa variante (`:free`) : `nvidia`
# (ou `nvidia/`) écarte `nvidia/…` mais pas `nvidia-autre/…` ; `poolside/laguna-s` écarte
# ce modèle et son sous-arbre, pas `poolside/laguna-s-2.1`.
KILO_EXCLURE = os.getenv("KILO_EXCLURE", "")

PREFIXE = "free/"
_TIMEOUT = 30.0


@dataclass(frozen=True)
class Source:
    """Une source de modèles gratuits et la façon de les servir via LiteLLM."""
    nom: str
    prefixe: str            # préfixe Workplace géré par CETTE source, et elle seule
    url_catalogue: str      # catalogue au format OpenRouter (`data`, `pricing`, …)
    api_base: str
    modele_litellm: str     # préfixe du fournisseur LiteLLM (`openrouter/`, `openai/`)
    cle: str                # clé envoyée à l'amont ; "" = source inutilisable
    top_n: int
    exclure: tuple[str, ...] = ()


def sources() -> list[Source]:
    """Construites à l'appel (pas à l'import) : les tests et `/sync` voient la config du moment.

    Kilo prend `api_key: "anonymous"` et non une chaîne vide : un client OpenAI sans clé
    envoie `Authorization: Bearer None`, que Kilo refuse (401) alors qu'il sert `anonymous`.
    """
    return [
        Source("openrouter", PREFIXE, "https://openrouter.ai/api/v1/models",
               "https://openrouter.ai/api/v1", "openrouter/", OPENROUTER_API_KEY, TOP_N),
        Source("kilo", "kilo/", "https://api.kilo.ai/api/gateway/models",
               "https://api.kilo.ai/api/gateway", "openai/", "anonymous", KILO_TOP_N,
               tuple(p.strip().strip("/") for p in KILO_EXCLURE.split(",") if p.strip().strip("/"))),
    ]


def _entetes() -> dict:
    return {"Authorization": f"Bearer {LITELLM_MASTER_KEY}", "Content-Type": "application/json"}


def _catalogue_brut(source: Source) -> list[dict]:
    """Catalogue complet de la source (seul appel réseau vers l'amont, isolé pour les tests).

    Kilo se lit sans en-tête d'autorisation : son catalogue est public.
    """
    entetes = {"Authorization": f"Bearer {source.cle}"} if source.nom == "openrouter" else {}
    r = httpx.get(source.url_catalogue, headers=entetes, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()["data"]


def _exploitables(brut: list[dict]) -> list[dict]:
    """Modèles du catalogue brut qu'on POURRAIT servir : gratuits, à outils, texte, hors
    méta-routeurs — avant les choix de l'opérateur (`KILO_EXCLURE`, `top_n`).

    Les deux premiers filtres viennent de l'ancien script et restent indispensables : l'assistant
    du Cœur EXIGE le function-calling (`tools`) et du texte — un modèle gratuit d'image ou sans
    outils casserait la cascade au lieu de la dépanner.

    Les méta-routeurs (`kilo-auto/free`, `openrouter/free`) sont écartés : ils choisissent
    EUX-MÊMES le modèle qui répond, donc le journal du Cœur (`journal_modele`) ne saurait plus
    quel modèle a réellement servi. Le routeur de Kilo n'est exposé que sous l'alias YAML
    `gratuit/auto`, réservé à la Forge, qui n'a pas de cascade.
    """
    def gratuit(m: dict) -> bool:
        # Comparaison à "0" exacte : les routeurs payants de Kilo annoncent "-1" (prix variable).
        p = m.get("pricing", {})
        return str(p.get("prompt", "1")) == "0" and str(p.get("completion", "1")) == "0"

    def utile(m: dict) -> bool:
        sp = m.get("supported_parameters") or []
        modality = (m.get("architecture", {}) or {}).get("modality", "") or ""
        # Côté SORTIE (après « -> ») : « text->image » contient « text » mais produit des
        # images — le test d'avant S239 laissait passer un générateur d'images à outils.
        return "tools" in sp and "text" in modality.split("->")[-1]

    return [m for m in brut
            if gratuit(m) and utile(m) and not m.get("id", "").endswith("/free")]


def _selection(source: Source, exploitables: list[dict]) -> list[dict]:
    """Choix de l'opérateur appliqués aux modèles exploitables : exclusions puis `top_n` plus
    gros contextes. Une sélection VIDE est ici légitime (retrait volontaire d'un fournisseur)."""
    def admis(m: dict) -> bool:
        base = m.get("id", "").split(":")[0]  # sans la variante (`:free`)
        return not any(base == e or base.startswith(e + "/") for e in source.exclure)

    retenus = [m for m in exploitables if admis(m)]
    retenus.sort(key=lambda m: m.get("context_length", 0), reverse=True)
    return retenus[:source.top_n]


def catalogue_gratuits(source: Source) -> list[dict]:
    """Modèles gratuits de la source retenus pour LiteLLM (catalogue → exploitables → sélection)."""
    return _selection(source, _exploitables(_catalogue_brut(source)))


def nom_workplace(id_amont: str, prefixe: str = PREFIXE) -> str:
    """`qwen/qwen3-coder:free` → `free/qwen/qwen3-coder` (nom vu par le Cœur).

    Les segments du milieu sont conservés (`a/x/m` → `a/x/m`) : les jeter faisait collisionner
    `a/x/m` et `a/y/m`, l'un écrasant l'autre en silence (revue S239, M3).
    """
    parts = id_amont.split("/")
    chemin = "/".join(parts[:-1]) if len(parts) > 1 else "inconnu"
    slug = parts[-1].replace(":free", "").replace(":", "-")
    return f"{prefixe}{chemin}/{slug}"


def modeles_actuels(client: httpx.Client) -> list[dict]:
    """Modèles AJOUTÉS EN BASE servis par LiteLLM : [{nom, id}], pour le différentiel.

    `/model/info` liste aussi les modèles du YAML ; LiteLLM les distingue par
    `model_info.db_model` (faux pour le YAML). On les écarte d'office : en plus de la règle des
    préfixes, un modèle du YAML ne doit JAMAIS pouvoir être supprimé par ce service.
    """
    r = client.get(f"{LITELLM_URL}/model/info", headers=_entetes(), timeout=_TIMEOUT)
    r.raise_for_status()
    actuels = []
    for m in r.json().get("data", []):
        info = m.get("model_info") or {}
        if info.get("db_model") is False:
            continue
        actuels.append({"nom": m.get("model_name", ""), "id": info.get("id", "")})
    return actuels


def _params(source: Source, m: dict) -> dict:
    """Paramètres LiteLLM d'un modèle gratuit.

    `timeout` court et `num_retries: 0` : les gratuits rate-limitent souvent (Kilo : 200
    req/h/IP) et peuvent PENDRE au lieu de renvoyer un 429 rapide — mieux vaut rendre la main
    vite pour que la cascade du Cœur bascule sur le gratuit suivant, puis sur le repli payant
    (motif hérité de l'ancien script, cf. Workplace S17).

    `cooldown_time: 60` (S239) : quand LiteLLM met CE déploiement au frigo, c'est pour une
    minute et non l'heure du réglage global — la valeur de déploiement prime (router.py:6739
    de LiteLLM v1.86.2). Un gratuit saturé une minute ne doit pas sortir de la cascade 1 h.
    """
    return {
        "model": f"{source.modele_litellm}{m['id']}",
        "api_key": source.cle,
        "api_base": source.api_base,
        "timeout": 10,
        "num_retries": 0,
        "cooldown_time": 60,
    }


def _synchroniser_source(client: httpx.Client, source: Source, actuels_tous: list[dict]) -> dict:
    """Aligne les modèles du préfixe de `source` sur son catalogue du moment.

    Ne lève pas sur un échec unitaire d'ajout/suppression : un modèle récalcitrant ne doit pas
    empêcher les autres d'être synchronisés — sinon une seule anomalie fige toute la liste,
    ce qui est exactement le problème qu'on cherche à supprimer.
    """
    if not source.cle:
        return {"statut": "ignore", "raison": f"clé absente pour {source.nom}"}
    # Catalogue injoignable ≠ catalogue vide : on s'arrête AVANT tout retrait, sinon une
    # panne passagère de l'amont viderait la cascade de cette source.
    exploitables = _exploitables(_catalogue_brut(source))
    voulus = {nom_workplace(m["id"], source.prefixe): m
              for m in _selection(source, exploitables)}
    actuels = {a["nom"]: a["id"] for a in actuels_tous if a["nom"].startswith(source.prefixe)}
    # Catalogue vide OU inexploitable (aucun gratuit à outils) alors que la source sert déjà
    # des modèles : anomalie (catalogue tronqué, format changé) bien plus probable qu'une
    # disparition de TOUS ses gratuits → on ne vide pas la cascade, on le signale (revue S239,
    # M1). Mais une SÉLECTION vide (KILO_TOP_N=0, KILO_EXCLURE qui écarte tout) est un choix
    # de l'opérateur — retirer un fournisseur pour confidentialité — et doit s'appliquer (M6).
    if not exploitables and actuels:
        raise RuntimeError(f"catalogue vide ou inexploitable — {len(actuels)} modèle(s) "
                           f"{source.prefixe}* en place conservé(s)")

    a_ajouter = [n for n in voulus if n not in actuels]
    a_retirer = [n for n in actuels if n not in voulus]

    ajoutes, retires, erreurs = [], [], []
    for nom in a_ajouter:
        try:
            r = client.post(f"{LITELLM_URL}/model/new", headers=_entetes(), timeout=_TIMEOUT,
                            json={"model_name": nom, "litellm_params": _params(source, voulus[nom])})
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

    # « inchangés » = ceux qui étaient DÉJÀ là et qu'on a laissés tels quels. Se calcule sur
    # `a_ajouter` (l'écart constaté) et non sur `ajoutes` (l'écart appliqué) : sinon un ajout
    # en échec se comptait comme un modèle en place, et le rapport annonçait « 12 inchangés »
    # alors que les 12 ajouts venaient d'échouer — exactement ce qu'on veut voir.
    return {"statut": "ok", "ajoutes": ajoutes, "retires": retires,
            "inchanges": len(voulus) - len(a_ajouter), "erreurs": erreurs}


def synchroniser() -> dict:
    """Synchronise chaque source indépendamment ; détail par source + agrégat.

    L'agrégat (`ajoutes`, `retires`, `inchanges`, `erreurs`) garde la forme d'avant S239, que
    `/sync`, `/sante` et la tâche d'horloge relaient. Une source en échec n'empêche pas les
    autres ; si AUCUNE source n'a pu tourner et qu'au moins une a échoué, on lève — `/sync`
    répond alors 502, lisible dans `GET /horloge/taches`, comme avant.
    """
    if not LITELLM_MASTER_KEY:
        return {"statut": "ignore", "raison": "LITELLM_MASTER_KEY absente"}

    detail: dict[str, dict] = {}
    with httpx.Client() as client:
        actuels = modeles_actuels(client)
        for source in sources():
            try:
                detail[source.nom] = _synchroniser_source(client, source, actuels)
            except Exception as e:  # noqa: BLE001
                detail[source.nom] = {"statut": "erreur", "raison": str(e)[:200]}

    statuts = [d["statut"] for d in detail.values()]
    if "ok" not in statuts and "erreur" in statuts:
        raise RuntimeError("; ".join(f"{n} : {d['raison']}" for n, d in detail.items()))

    ok = [d for d in detail.values() if d["statut"] == "ok"]
    erreurs = [e for d in ok for e in d["erreurs"]]
    erreurs += [f"{n} : {d['raison']}" for n, d in detail.items() if d["statut"] == "erreur"]
    resultat = {
        "statut": "ok" if ok else "ignore",
        "ajoutes": [n for d in ok for n in d["ajoutes"]],
        "retires": [n for d in ok for n in d["retires"]],
        "inchanges": sum(d["inchanges"] for d in ok),
        "erreurs": erreurs,
        "sources": detail,
    }
    if erreurs:
        logger.warning("gateway-sync : %d erreur(s) — %s", len(erreurs), "; ".join(erreurs))
    for nom, d in detail.items():
        if d["statut"] == "ok":
            logger.info("gateway-sync [%s] : %d ajouté(s), %d retiré(s), %d inchangé(s)",
                        nom, len(d["ajoutes"]), len(d["retires"]), d["inchanges"])
        else:
            logger.info("gateway-sync [%s] : %s — %s", nom, d["statut"], d["raison"])
    return resultat
