"""Co-agent exécutif (S66) — le « lobe frontal » du Cœur.

L'assistant `converser` est un réflexe : une boucle ReAct courte (6 tours) qui répond
À l'utilisateur. Le co-agent est l'EXÉCUTIF : une boucle PROFONDE, autonome, lancée pour
mener un objectif précis à son terme sans repasser par l'humain à chaque étape. Exposé
comme un OUTIL unique (`coagent_lancer`) que l'assistant déclenche pour les tâches
multi-étapes (« compile l'état de toutes les entreprises et propose un plan »).

Deux garde-fous SOUVERAINS, conformes à l'épopée « Organisme vivant » :
  1. Le **budget de tokens** borne le COÛT de la pensée : la boucle s'arrête dès que le
     plafond est atteint (défense en profondeur avec un plafond d'ÉTAPES).
  2. Le **gate humain** borne le POUVOIR sur le corps : le co-agent est LECTURE SEULE —
     il ne voit JAMAIS les outils d'action (`outils.est_action`). S'il faut agir, il le
     RECOMMANDE dans sa synthèse ; c'est l'humain qui valide, dans la conversation.

Il pense de préférence sur le **Muscle** (calcul déporté, brique S58) mis en tête de
cascade quand un nœud est chaud — pour que la réflexion profonde ne coûte pas le cloud.
Best-effort : Muscle absent → cascade habituelle. Ne s'auto-appelle jamais (pas de
`coagent_lancer` dans sa propre trousse → pas de récursion).
"""
import asyncio
import json
import logging
import os

import httpx

import config_assistant
import llm_pipeline
import muscle
import outils

logger = logging.getLogger(__name__)

# Garde-fous par défaut (réglables par env, surchargés par l'appel). Le budget borne le
# COÛT ; le plafond d'étapes est un coupe-circuit indépendant (une étape peut être chère).
BUDGET_TOKENS_DEFAUT = int(os.getenv("COAGENT_BUDGET_TOKENS", "20000"))
MAX_ETAPES_DEFAUT = int(os.getenv("COAGENT_MAX_ETAPES", "12"))

# Jamais offerts au co-agent : lui-même (récursion) — les actions sont retirées à part.
_EXCLUS = {"coagent_lancer"}

PROMPT_COAGENT = (
    "Tu es le LOBE FRONTAL du Cœur de Workplace : un agent exécutif lancé pour mener à "
    "terme, EN AUTONOMIE, un objectif précis. Tu travailles par étapes : consulte les "
    "organes utiles (tes outils sont en LECTURE SEULE — tu ne peux PAS agir sur le corps), "
    "raisonne, puis recommence jusqu'à pouvoir conclure.\n"
    "RÈGLES :\n"
    "- Tu ne demandes RIEN à l'humain en cours de route : tu décides seul des outils à "
    "appeler.\n"
    "- Tu ne PEUX PAS exécuter d'action (créer, livrer, mémoriser, envoyer…). Si l'objectif "
    "en requiert une, ne l'invente pas : RECOMMANDE-la clairement dans ta synthèse pour que "
    "l'humain la valide.\n"
    "- N'invente jamais un fait : si un outil ne te le donne pas, dis-le.\n"
    "- Quand tu as de quoi conclure, réponds SANS appeler d'outil : rends une SYNTHÈSE "
    "claire, structurée et actionnable (constats → recommandations)."
)


def _outils_lecture(registre) -> list[dict]:
    """Trousse du co-agent : les outils du LLM SANS les actions ni l'auto-appel.

    Source unique : `outils.outils_pour` (les outils en dur + capacités découvertes S64).
    On retire toute action (`est_action`) — c'est le gate souverain : pas de pouvoir sur
    le corps en autonomie — et `coagent_lancer` lui-même (anti-récursion)."""
    trousse = []
    for spec in outils.outils_pour(registre):
        nom = spec["function"]["name"]
        if nom in _EXCLUS or outils.est_action(nom, registre):
            continue
        trousse.append(spec)
    return trousse


async def _cascade(conf: dict, client: httpx.AsyncClient) -> list[str]:
    """Cascade de modèles du co-agent, Muscle déporté en tête s'il est chaud (best-effort)."""
    modeles = await config_assistant.chaine_modeles(conf)
    if not modeles:
        modeles = [conf.get("model") or config_assistant.DEFAUT_REPLI_PAYANT]
    if conf.get("muscle_actif"):
        try:
            tete = await muscle.tete_de_cascade(client)
        except Exception:  # noqa: BLE001 — le Muscle ne doit jamais casser la réflexion
            tete = None
        if tete:
            modeles = [tete] + [m for m in modeles if m != tete]
    return modeles


def _resultat(*, ok, raison, objectif, synthese="", etapes=0, tokens=0, cout=0.0,
              modele=None, outils_appeles=None, erreur=None) -> dict:
    """Compte rendu structuré du co-agent (rendu tel quel à l'assistant via l'outil)."""
    return {
        "ok": ok,
        "objectif": objectif,
        "synthese": synthese,
        "raison_arret": raison,  # abouti | budget | max_etapes | erreur
        "etapes": etapes,
        "tokens": tokens,
        "cout_usd": round(cout, 6),
        "modele": modele,
        "outils_appeles": outils_appeles or [],
        "erreur": erreur,
        "note": "Co-agent LECTURE SEULE : aucune action n'a été exécutée. Les actions "
                "éventuelles sont à valider par l'humain.",
    }


async def _synthese_finale(messages, modeles, conf, client, objectif, *,
                           raison, etapes, tokens, cout, modele, appels) -> dict:
    """Demande une dernière synthèse SANS outils quand un plafond est atteint en cours de route.

    Un seul appel borné : on récupère une conclusion utile avec ce qui a déjà été collecté,
    plutôt que de rendre une boucle tronquée muette. Repli honnête si même ça échoue."""
    messages = messages + [{"role": "system", "content":
        f"Plafond atteint ({raison}). Arrête d'appeler des outils et rends MAINTENANT ta "
        "synthèse (constats + recommandations) avec ce que tu as déjà recueilli."}]
    res = await llm_pipeline.completer(messages, modeles=modeles, tools=None,
                                       etiquette="coagent", conf=conf, client=client)
    if res.ok:
        tokens += res.tokens_in + res.tokens_out
        cout += res.cout_usd
        modele = res.modele_utilise or modele
        synthese = res.message.get("content") or ""
    else:
        synthese = ("Objectif non abouti : plafond atteint avant conclusion et la synthèse "
                    "finale a échoué. Relance avec un budget plus large si besoin.")
    return _resultat(ok=True, raison=raison, objectif=objectif, synthese=synthese,
                     etapes=etapes, tokens=tokens, cout=cout, modele=modele,
                     outils_appeles=appels)


async def executer_objectif(objectif: str, registre, *, budget_tokens: int | None = None,
                            max_etapes: int | None = None, conf: dict | None = None,
                            client: httpx.AsyncClient | None = None) -> dict:
    """Mène un objectif en autonomie (boucle profonde lecture seule) et rend une synthèse.

    Bornée par `budget_tokens` (coût de la pensée) ET `max_etapes` (coupe-circuit). Le
    co-agent ne peut qu'OBSERVER le corps ; toute action est recommandée, jamais exécutée."""
    objectif = (objectif or "").strip()
    if not objectif:
        return _resultat(ok=False, raison="erreur", objectif=objectif,
                         erreur="Objectif vide : rien à mener.")
    budget = budget_tokens or BUDGET_TOKENS_DEFAUT
    max_e = max_etapes or MAX_ETAPES_DEFAUT
    conf = conf or config_assistant.charger()
    trousse = _outils_lecture(registre)

    messages = [{"role": "system", "content": PROMPT_COAGENT},
                {"role": "user", "content": objectif}]
    tokens = 0
    cout = 0.0
    modele = None
    appels: list[str] = []

    proprietaire = client is None
    client = client or httpx.AsyncClient(timeout=120)
    try:
        modeles = await _cascade(conf, client)
        for etape in range(1, max_e + 1):
            res = await llm_pipeline.completer(
                messages, modeles=modeles, tools=trousse, tool_choice="auto",
                temperature=0.2, etiquette="coagent", conf=conf, client=client)
            if not res.ok:
                return _resultat(ok=False, raison="erreur", objectif=objectif,
                                 etapes=etape - 1, tokens=tokens, cout=cout, modele=modele,
                                 outils_appeles=appels,
                                 erreur=res.erreur or "Aucun modèle disponible.")
            tokens += res.tokens_in + res.tokens_out
            cout += res.cout_usd
            modele = res.modele_utilise or modele
            message = res.message
            tool_calls = message.get("tool_calls") or []

            if not tool_calls:  # le co-agent conclut de lui-même → abouti
                return _resultat(ok=True, raison="abouti", objectif=objectif,
                                 synthese=message.get("content") or "", etapes=etape,
                                 tokens=tokens, cout=cout, modele=modele,
                                 outils_appeles=appels)

            messages.append({"role": "assistant", "content": message.get("content"),
                             "tool_calls": tool_calls})
            for tc in tool_calls:
                nom = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                appels.append(nom)
                resultat = await outils.executer(nom, args, registre)
                messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                 "content": resultat})

            if tokens >= budget:  # garde-fou COÛT : on s'arrête et on conclut dans le budget
                return await _synthese_finale(
                    messages, modeles, conf, client, objectif, raison="budget",
                    etapes=etape, tokens=tokens, cout=cout, modele=modele, appels=appels)

        # Plafond d'étapes atteint sans conclusion spontanée : dernière synthèse forcée.
        return await _synthese_finale(
            messages, modeles, conf, client, objectif, raison="max_etapes",
            etapes=max_e, tokens=tokens, cout=cout, modele=modele, appels=appels)
    finally:
        if proprietaire:
            await client.aclose()
