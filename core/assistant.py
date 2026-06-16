"""Assistant conversationnel du Cœur (Sprint S7).

Un agent « ReAct » : il dialogue avec l'utilisateur et, quand c'est utile, appelle
des **outils** qui pilotent l'usine (cf. `outils.py`). Modèle repris de
`workspace/assistant` (boucle LLM ↔ outils, fallback de modèles), adapté à
l'architecture Workplace : le LLM passe par le **Gateway** déjà utilisé par les
autres briques (compatible OpenAI, function-calling), et les outils n'appellent
que des contrats internes du Cœur.

On émet un flux d'événements (SSE) au navigateur : texte, appel d'outil, résultat
d'outil, fin. La boucle s'arrête dès que le modèle répond sans demander d'outil.
"""

import json
import logging
import os
from datetime import datetime
from typing import AsyncIterator
from zoneinfo import ZoneInfo

import httpx

import config_assistant
import langue as langue_mod
import llm_pipeline
import muscle
import outils
import personas
import identite

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 6

# Streaming token-par-token (S60) : l'assistant émet le texte au fil de l'eau (feel
# ChatGPT, utile en mobilité). Kill-switch d'env : STREAM_ACTIF=0 rétablit la réponse
# en bloc (chemin `completer`), utile pour le debug.
STREAM_ACTIF = os.getenv("STREAM_ACTIF", "1").lower() not in ("0", "false", "no")

PROMPT_SYSTEME = (
    "Tu es l'assistant du Cœur de Workplace : un « Jarvis » de TOUTE la solution. "
    "Tu ne te limites pas à l'usine : tu peux consulter et agir sur l'ensemble des "
    "briques — entreprises livrées, documents (ETL), applications générées, données "
    "saisies, et la mémoire de la solution — via tes outils.\n\n"
    "Tu as DEUX MÉMOIRES (paramètre `espace` de `memoire_rappeler`/`memoire_retenir`) : "
    "« solution » (l'usine, les entreprises, les projets — défaut) et « perso » (ce qui "
    "concerne l'utilisateur lui-même : ses préférences, habitudes, faits personnels). "
    "Range dans « perso » ce qui le concerne (« je préfère… », « je suis… »), dans "
    "« solution » ce qui concerne le travail. Consulte la mémoire utile au début d'une "
    "demande ; mémorise (après accord) ce que l'utilisateur veut garder.\n\n"
    "Tu gères des DOCUMENTS : l'utilisateur en dépose, ils sont rangés dans des "
    "DOSSIERS. Avec `lister_dossiers` vois les projets et catégories ; avec "
    "`chercher_documents` filtre par catégorie, projet ou entreprise ; avec "
    "`classer_document` ajuste le rangement d'un document (catégorie, tags, projet, "
    "entreprise rattachée). Un document peut être relié à une entreprise et/ou rangé "
    "dans un projet (ex. « prochain sprint »). Quand un document vient d'être déposé "
    "et classé, propose à l'utilisateur d'en retenir l'essentiel en mémoire.\n\n"
    "Tu pilotes FORGE (agents IA + RAG) : `forge_capacites` dit ce que Forge sait faire ; "
    "`forge_rag_chercher` cherche dans les documents ingérés (lecture, sans confirmation) ; "
    "`forge_rag_ingerer` ajoute un document au RAG et `forge_lancer_agent` lance un agent "
    "qui raisonne — ces deux dernières sont des ACTIONS (confirmation requise).\n\n"
    "Tu gères un AGENDA personnel : `agenda_consulter` liste les rendez-vous sur une "
    "période ; `agenda_creer_evenement` et `agenda_deplacer_evenement` créent/replanifient "
    "DIRECTEMENT (pas de confirmation, c'est réversible) ; `agenda_supprimer_evenement` "
    "annule et exige confirmation. "
    "Convertis les dates relatives (« demain 14h », « lundi prochain ») en ISO 8601 en "
    "t'appuyant sur la date/heure courante donnée ci-dessous. Si l'heure de fin n'est pas "
    "précisée, prévois 1 heure. Pour déplacer/annuler, retrouve d'abord l'event_id avec "
    "`agenda_consulter`.\n\n"
    "Règles :\n"
    "- Pour agir sur une entreprise, retrouve d'abord son identifiant avec "
    "`lister_entreprises` (l'utilisateur parle par nom, pas par id) ; de même, "
    "retrouve un app_id via `lister_apps` ou `lister_entreprises` au besoin.\n"
    "- Les ACTIONS (livrer, décrocher, reprendre, ingérer un document, créer un "
    "enregistrement, mémoriser, ingérer dans le RAG de Forge, lancer un agent Forge) "
    "sont SENSIBLES. Ne passe JAMAIS `confirme=true` de ta "
    "propre initiative. Appelle d'abord l'outil sans `confirme` : il te renverra une "
    "demande de confirmation. Reformule-la clairement, ATTENDS l'accord explicite de "
    "l'utilisateur, et seulement alors rappelle l'outil avec `confirme=true`.\n"
    "- Si, dans son DERNIER message, l'utilisateur a clairement accepté une action que "
    "tu venais de proposer (« oui », « vas-y », « ok », « confirme »), alors appelle "
    "directement l'outil avec `confirme=true` — ne redemande pas une seconde fois.\n"
    "- « décrocher » retire vraiment l'entreprise des bases centrales (vers un "
    "dossier portable) : préviens-en l'utilisateur avant de confirmer.\n"
    "- Si un outil échoue, explique-le simplement et continue."
    # La langue de réponse est ajoutée à chaud (cf. converser → langue.consigne_reponse) :
    # c'est une préférence d'utilisateur (S39), pas un choix codé en dur.
)


async def converser(messages: list[dict], registre) -> AsyncIterator[dict]:
    """Déroule un tour de conversation et émet des événements jusqu'à la réponse finale.

    `messages` : historique au format OpenAI ({role, content}). Émet des dicts
    {type: texte|outil|resultat_outil|fin|erreur, ...}.
    """
    # Date/heure courante (Europe/Paris) injectée pour interpréter « demain », « lundi »…
    try:
        maintenant = datetime.now(ZoneInfo("Europe/Paris"))
    except Exception:
        maintenant = datetime.now()
    contexte_date = (
        "Date et heure actuelles : "
        + maintenant.strftime("%A %d %B %Y, %H:%M")
        + f" (ISO : {maintenant.isoformat(timespec='minutes')}, fuseau Europe/Paris)."
    )
    # Modèle + persona lus à CHAUD (réglables depuis le front, cf. config_assistant).
    conf = config_assistant.charger()
    systeme = (PROMPT_SYSTEME + personas.prompt_de(conf.get("persona"))
               + "\n- " + langue_mod.consigne_reponse(conf.get("langue")))
    amorce = [{"role": "system", "content": systeme},
              {"role": "system", "content": contexte_date}]
    # Qui est l'utilisateur : digest COMPACT dérivé de sa fiche d'identité (S48) —
    # prénom, âge, anniversaire, signes… Volontairement court (coût LLM, cf. S138) ;
    # vide si aucune fiche. C'est ce qui fait enfin « parler » la page « se présenter ».
    try:
        digest = identite.resume_texte(identite.charger_fiche())
    except Exception:  # noqa: BLE001 — l'identité ne doit jamais casser une conversation
        digest = ""
    if digest:
        amorce.append({"role": "system", "content": digest})
    historique = amorce + list(messages)
    # Ordre effectif : cascade auto (gratuits → repli payant) ou chaîne manuelle.
    modeles = await config_assistant.chaine_modeles(conf)
    if not modeles:  # garde-fou : ne jamais partir sans modèle
        modeles = [conf.get("model") or config_assistant.DEFAUT_REPLI_PAYANT]

    async with httpx.AsyncClient(timeout=120) as client:
        # Muscle déporté (brique calcul, roadmap S58) : opt-in. Si un nœud de calcul est
        # DÉJÀ prêt, on le met en tête de la cascade ; sinon on déclenche un réveil EN FOND
        # (la requête courante part en mode dégradé sur les gratuits ; le prochain message
        # tombera sur un muscle chaud). Best-effort : calcul absent/muet → cascade inchangée.
        if conf.get("muscle_actif"):
            tete = await muscle.tete_de_cascade(client)
            if tete:
                modeles = [tete] + [m for m in modeles if m != tete]
            else:
                muscle.planifier_reveil()

        for iteration in range(MAX_ITERATIONS):
            # Pipeline unifié (S138) : trimming + bascule de modèles + comptage
            # tokens/coût + journal. La logique d'outils reste ici, côté agent.
            # S60 : en streaming, on émet le texte en `texte_delta` au fil de l'eau et on
            # réassemble le message (avec ses tool_calls) pour piloter la boucle d'outils.
            message = None
            if STREAM_ACTIF:
                erreur = None
                async for evt in llm_pipeline.completer_flux(
                        historique, modeles=modeles, tools=outils.OUTILS,
                        tool_choice="auto", temperature=0.2, etiquette="chat",
                        conf=conf, client=client):
                    if evt["type"] == "delta":
                        yield {"type": "texte_delta", "contenu": evt["contenu"]}
                    elif evt["type"] == "fin":
                        message = evt["message"]
                    elif evt["type"] == "erreur":
                        erreur = evt["erreur"]
                if message is None:
                    yield {"type": "erreur", "contenu": erreur or "Aucun modèle disponible."}
                    return
            else:
                res = await llm_pipeline.completer(
                    historique, modeles=modeles, tools=outils.OUTILS,
                    tool_choice="auto", temperature=0.2, etiquette="chat",
                    conf=conf, client=client,
                )
                if not res.ok:
                    yield {"type": "erreur", "contenu": res.erreur or "Aucun modèle disponible."}
                    return
                message = res.message

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                # En streaming le texte a déjà été émis en deltas ; sinon on l'émet en bloc.
                if not STREAM_ACTIF:
                    yield {"type": "texte", "contenu": message.get("content") or ""}
                yield {"type": "fin"}
                return

            # Le modèle veut des outils : on les exécute puis on reboucle.
            historique.append({
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": tool_calls,
            })
            for tc in tool_calls:
                nom = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield {"type": "outil", "nom": nom, "args": args,
                       "action": nom in outils.OUTILS_ACTION}
                resultat = await outils.executer(nom, args, registre)
                confirmation = '"confirmation_requise": true' in resultat
                yield {"type": "resultat_outil", "nom": nom,
                       "resultat": resultat, "confirmation": confirmation}
                historique.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": resultat,
                })

        yield {"type": "texte",
               "contenu": "J'ai atteint la limite d'étapes pour cette demande. Reformule si besoin."}
        yield {"type": "fin"}
