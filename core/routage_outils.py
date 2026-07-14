"""Routage d'outils par embeddings — ne présenter au LLM que les outils PERTINENTS.

Aujourd'hui le Cœur présente au modèle, à CHAQUE appel, l'intégralité des outils : les
outils en dur + toutes les capacités découvertes dans les manifests (~64). Ça gonfle le
contexte (coût + latence) alors qu'une requête donnée n'en mobilise qu'une poignée.

Ce module filtre dynamiquement cette liste selon la requête de l'utilisateur :

  - au DÉMARRAGE (`indexer`) : on calcule, via la Gateway (`text-embedding-3-small`), l'embedding
    de la description de chaque outil et on les garde EN MÉMOIRE (matrice numpy) ;
  - à CHAQUE requête (`filtrer_outils`) : on embed la requête, on classe les outils par
    similarité COSINUS, et on ne garde que les `top_k` plus proches — PLUS un socle d'outils
    « toujours pertinents » (passé via `toujours`) qu'on n'enlève jamais.

Contexte plus court → appel plus rapide et moins cher, SANS amputer les pouvoirs : un outil
écarté pour une requête redevient candidat à la suivante.

Garde-fous (repli honnête, jamais bloquant) :
  - OPT-IN : inerte tant que `ROUTAGE_OUTILS` n'est pas activé → comportement actuel inchangé.
  - Gateway KO / numpy absent / index vide AU DÉMARRAGE → on n'indexe pas, et `filtrer_outils`
    renvoie TOUS les outils (le comportement actuel). Idem si l'embedding de la requête échoue.

⚠ Honnêteté sur « niveau-0 » : dans ce dépôt le `niveau` d'une capacité (porte S90) vaut 0 PAR
DÉFAUT — la quasi-totalité des capacités sont donc niveau-0. « Toujours inclure niveau-0 » à la
lettre reviendrait à ne (presque) rien filtrer. Le vrai socle « toujours pertinent » de ce Cœur,
ce sont les outils EN DUR (lister_entreprises, mes_capacites…) : c'est lui qu'on passe en
`toujours` côté appelant. Le paramètre reste libre si l'on veut un autre socle.

numpy quand il est là, repli pur-Python sinon : l'index est une matrice numpy (rapide) dès que
numpy est installé (image Docker, `requirements.txt`) ; sans numpy (ex. environnement de test),
on bascule sur un cosinus en Python pur — le contexte est minuscule (~64 vecteurs), c'est sans
incidence. Le résultat est identique ; seul le moteur de calcul change.
"""
import logging
import math
import os

import httpx

logger = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")
GATEWAY_KEY = os.getenv("GATEWAY_KEY", "")
EMBEDDING_MODEL = os.getenv("ROUTAGE_EMBEDDING_MODEL", "text-embedding-3-small")
ACTIF = os.getenv("ROUTAGE_OUTILS", "0").lower() in ("1", "true", "yes", "on")
TOP_K = int(os.getenv("ROUTAGE_TOP_K", "8"))
# Poids du boost lexical (graphe d'apprentissage S145). 0 = désactivé (rétrocompat parfaite).
ALPHA_BOOST = float(os.getenv("GRAPHE_ALPHA", "0.3"))

try:  # numpy = chemin rapide ; absent → repli cosinus pur-Python (cf. en-tête)
    import numpy as _np
except ImportError:  # pragma: no cover — dépend de l'environnement
    _np = None

# État construit au démarrage (`indexer`) : nom d'outil → vecteur NORMALISÉ (np.ndarray ou liste).
_index: dict = {}
_pret: bool = False


def _nom(spec: dict) -> str:
    return (spec.get("function") or {}).get("name", "")


def _texte(spec: dict) -> str:
    """Texte représentant l'outil pour l'embedding : nom + description (le signal le plus riche)."""
    f = spec.get("function") or {}
    return f"{f.get('name', '')}: {f.get('description', '') or ''}".strip()


async def _embed_lot(client: httpx.AsyncClient, textes: list) -> list | None:
    """Embeddings d'un LOT de textes via la Gateway (un seul appel). None si indisponible."""
    try:
        r = await client.post(
            f"{GATEWAY_URL}/v1/embeddings",
            headers={"Authorization": f"Bearer {GATEWAY_KEY}"},
            json={"model": EMBEDDING_MODEL, "input": [t[:8000] for t in textes]},
        )
        if r.status_code >= 400:
            logger.warning("Routage : embeddings Gateway %s", r.status_code)
            return None
        # OpenAI/LiteLLM renvoient un `index` par embedding : on réordonne par sûreté.
        data = sorted(r.json()["data"], key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        logger.warning("Routage : embeddings injoignables (%s)", e)
        return None


async def _embed(client: httpx.AsyncClient, texte: str) -> list | None:
    """Embedding d'UN texte (la requête). None si indisponible (→ repli sur tous les outils)."""
    lot = await _embed_lot(client, [texte])
    return lot[0] if lot else None


def _normaliser(vec):
    """Vecteur unitaire → produit scalaire = cosinus directement. numpy si présent, sinon liste."""
    if _np is not None:
        v = _np.asarray(vec, dtype="float32")
        n = float(_np.linalg.norm(v))
        return v / n if n else v
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n else list(vec)


def _cos(q, v) -> float:
    """Cosinus entre deux vecteurs DÉJÀ normalisés (= leur produit scalaire)."""
    if _np is not None:
        return float(_np.dot(q, v))
    return sum(a * b for a, b in zip(q, v))


def reinitialiser() -> None:
    """Vide l'index (tests / rechargement des briques)."""
    global _pret
    _index.clear()
    _pret = False


async def indexer(specs: list, client: httpx.AsyncClient | None = None) -> bool:
    """Construit l'index des embeddings d'outils AU DÉMARRAGE. Renvoie True si prêt.

    Repli honnête (renvoie False, index laissé vide → `filtrer_outils` laisse tout passer) si le
    routage est désactivé ou si la Gateway est injoignable/incomplète au démarrage."""
    global _pret
    reinitialiser()
    if not ACTIF or not specs:
        return False
    proprietaire = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        vecteurs = await _embed_lot(client, [_texte(s) for s in specs])
    finally:
        if proprietaire:
            await client.aclose()
    if not vecteurs or len(vecteurs) != len(specs):
        logger.warning("Routage : indexation incomplète → repli sur tous les outils")
        return False
    for spec, vec in zip(specs, vecteurs):
        _index[_nom(spec)] = _normaliser(vec)
    _pret = True
    logger.info("Routage d'outils : %d outils indexés (modèle %s)", len(_index), EMBEDDING_MODEL)
    return True


def _classer(vec_requete, noms: list) -> list:
    """Noms d'outils (parmi `noms`, présents à l'index) triés par cosinus décroissant."""
    q = _normaliser(vec_requete)
    scores = [(n, _cos(q, _index[n])) for n in noms if n in _index]
    scores.sort(key=lambda x: x[1], reverse=True)
    return [n for n, _ in scores]


def selectionner(vec_requete, toutes_capacites: list, *, top_k: int = TOP_K,
                 toujours=None, requete: str = "") -> list:
    """Cœur PUR (testable sans Gateway) : garde le socle `toujours` + les `top_k` outils les plus
    proches de `vec_requete`, en PRÉSERVANT l'ordre d'origine (préfixe stable → cacheable S90).

    Si `requete` est fournie ET que GRAPHE_ALPHA > 0, le score final intègre le boost lexical
    du graphe d'apprentissage (S145) : score_final = score_cos + ALPHA_BOOST * boost_lexical.
    """
    toujours = set(toujours or ())

    # Scores cosinus de base
    q = _normaliser(vec_requete)
    noms = [_nom(s) for s in toutes_capacites]
    scores: dict[str, float] = {n: _cos(q, _index[n]) for n in noms if n in _index}

    # Boost lexical du graphe d'apprentissage (opt-in via GRAPHE_ALPHA)
    if requete and ALPHA_BOOST > 0:
        import graphe_apprentissage as _ga  # import local — évite cycle au module-level
        boosts = _ga._graphe.boost(requete, toutes_capacites)
        scores = {n: scores.get(n, 0.0) + ALPHA_BOOST * boosts.get(n, 0.0) for n in scores}

    proches = set(sorted(scores, key=lambda n: -scores[n])[:top_k])
    gardes = proches | toujours
    return [s for s in toutes_capacites if _nom(s) in gardes]


def _texte_contenu(contenu) -> str:
    """Texte plat d'un `content` de message OpenAI (gère le multimodal = liste de parts)."""
    if isinstance(contenu, list):
        return " ".join(p.get("text", "") for p in contenu
                        if isinstance(p, dict) and p.get("type") == "text")
    return contenu or ""


def requete_depuis_messages(messages: list) -> str:
    """Requête de routage à partir de l'historique : le DERNIER message, enrichi du message
    ASSISTANT qui le précède (tronqué).

    Motif clé — les confirmations de gate : « supprime la série X » → *(gate)* → « **oui** ».
    Le « oui » n'a aucun mot-clé ; mais l'invite de confirmation de l'assistant juste avant
    RESTATE l'action (« Je vais supprimer la série X… ») → l'inclure garde l'outil EN ATTENTE
    dans le top_k. Sans ce contexte, « oui » écarterait l'outil (ex. `studio_serie_supprimer`)
    et l'assistant improviserait un mauvais outil. N'affecte QUE la sélection d'outils.
    """
    if not messages:
        return ""
    dernier = _texte_contenu(messages[-1].get("content"))
    precedent = ""
    if len(messages) >= 2 and messages[-2].get("role") == "assistant":
        precedent = _texte_contenu(messages[-2].get("content"))[:600]
    return (precedent + "\n" + dernier).strip() if precedent else dernier.strip()


async def filtrer_outils(requete: str, toutes_capacites: list, *,
                         client: httpx.AsyncClient | None = None,
                         top_k: int = TOP_K, toujours=None) -> list:
    """Réduit la liste d'outils présentée au LLM aux plus pertinents pour `requete`.

    Renvoie `toutes_capacites` INCHANGÉ (repli honnête) si le routage n'est pas prêt (désactivé /
    non indexé / Gateway KO au démarrage) ou si l'embedding de la requête échoue. Sinon : socle
    `toujours` + les `top_k` outils les plus proches (similarité cosinus)."""
    if not _pret or not (requete or "").strip():
        return toutes_capacites
    proprietaire = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        vec = await _embed(client, requete)
    finally:
        if proprietaire:
            await client.aclose()
    if vec is None:
        return toutes_capacites
    return selectionner(vec, toutes_capacites, top_k=top_k, toujours=toujours, requete=requete)
