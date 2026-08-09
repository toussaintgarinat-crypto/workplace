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

import catalogue
import config_assistant
import conscience
import guardrails_outils
import langue as langue_mod
import llm_pipeline
import muscle
import outils
import routage_outils
import personas
import identite
import proprioception
import amelioration
import moa
import suggestions
import validation_args
import accord_action

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20

_PREFIXES_ERREUR_OUTIL = (
    "Impossible :", "Échec (", "Indisponible (", "Brique injoignable (",
    "Erreur (", "Outil inconnu :",
)


def _est_erreur_outil(resultat: str) -> bool:
    """Détecte si `outils.executer` a renvoyé un message d'erreur."""
    if any(resultat.startswith(p) for p in _PREFIXES_ERREUR_OUTIL):
        return True
    try:
        return bool(json.loads(resultat).get("erreur"))
    except Exception:  # noqa: BLE001
        return False

# Streaming token-par-token (S60) : l'assistant émet le texte au fil de l'eau (feel
# ChatGPT, utile en mobilité). Kill-switch d'env : STREAM_ACTIF=0 rétablit la réponse
# en bloc (chemin `completer`), utile pour le debug.
STREAM_ACTIF = os.getenv("STREAM_ACTIF", "1").lower() not in ("0", "false", "no")

PROMPT_SYSTEME = (
    "Tu es l'assistant du Cœur de Workplace : un « Jarvis » de TOUTE la solution. "
    "Tu ne te limites pas à l'usine : tu peux consulter et agir sur l'ensemble des "
    "briques — entreprises livrées, documents (Ingestion), applications générées, données "
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
    "- Ce n'est pas qu'une consigne : le Cœur REFUSE d'exécuter une action dont l'accord "
    "n'a pas été demandé puis obtenu d'un vrai message de l'utilisateur, et l'accord porte "
    "sur les arguments EXACTS qui lui ont été présentés. Changer un destinataire ou une "
    "cible après son accord invalide l'accord — il faut redemander.\n"
    "- « décrocher » retire vraiment l'entreprise des bases centrales (vers un "
    "dossier portable) : préviens-en l'utilisateur avant de confirmer.\n"
    "- Si un outil échoue, explique-le simplement et continue.\n\n"
    "Workflow AMÉLIORER : quand l'utilisateur dit « Je veux améliorer la solution » ou clique"
    " [🛠️ Améliorer], pose-lui UNE seule question courte (« Qu'est-ce que tu veux ajouter"
    " ou changer ? »), attends sa réponse, puis appelle `dev_demander(intention=<sa réponse>)`."
    " Pour la suite : `dev_diff(cid=...)` quand il demande le diff ;"
    " `dev_plan_valider(cid=..., confirme=true)` pour valider le plan ;"
    " `dev_fusionner(cid=..., confirme=true)` pour pousser en prod ;"
    " `dev_jeter(cid=...)` pour annuler. Les boutons de navigation apparaissent automatiquement"
    " dans le chat après chaque outil — ne les liste pas dans ta réponse texte."
    # La langue de réponse est ajoutée à chaud (cf. converser → langue.consigne_reponse) :
    # c'est une préférence d'utilisateur (S39), pas un choix codé en dur.
)


async def converser(messages: list[dict], registre,
                    instructions_projet: str | None = None,
                    fil: str | None = None) -> AsyncIterator[dict]:
    """Déroule un tour de conversation et émet des événements jusqu'à la réponse finale.

    `messages` : historique au format OpenAI ({role, content}). Émet des dicts
    {type: texte|outil|resultat_outil|fin|erreur, ...}.

    `instructions_projet` : contexte propre au projet de la conversation (façon Claude
    Projects), injecté dans la zone VOLATILE de l'amorce — après le préfixe stable mis en
    cache (S90), pour ne pas le casser quand on passe d'un projet à l'autre.

    `fil` (S222) : identifiant du fil de conversation, sous lequel le Cœur tient les accords
    humains sur les actions. **Absent = aucun accord ne peut exister** : les actions
    `confirme=true` sont refusées. C'est le sens sûr — un appelant qui n'a pas de tour de
    parole humain n'a pas à pouvoir déclencher d'action confirmée.
    """
    fil_accord = fil or f"sans-fil:{id(messages)}"
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
    # Addendum d'auto-amélioration (S69) : une consigne issue d'une proposition VALIDÉE
    # puis APPLIQUÉE (gate humain). Vide tant que rien n'a été activé → prompt fondateur.
    systeme = (PROMPT_SYSTEME + personas.prompt_de(conf.get("persona"))
               + "\n- " + langue_mod.consigne_reponse(conf.get("langue"))
               + amelioration.addendum_actif())
    # S90a — préfixe stable & cacheable : on place d'abord TOUT ce qui ne change pas d'une
    # requête à l'autre (prompt fondateur, digests d'identité/conscience) ; le seul élément
    # VOLATIL — la date/heure — est ajouté en DERNIER message système, juste avant la
    # conversation, pour ne pas casser le préfixe mis en cache (cf. cache.py, S90b).
    amorce = [{"role": "system", "content": systeme}]
    # Qui est l'utilisateur : digest COMPACT dérivé de sa fiche d'identité (S48) —
    # prénom, âge, anniversaire, signes… Volontairement court (coût LLM, cf. S138) ;
    # vide si aucune fiche. C'est ce qui fait enfin « parler » la page « se présenter ».
    try:
        digest = identite.resume_texte(identite.charger_fiche())
    except Exception:  # noqa: BLE001 — l'identité ne doit jamais casser une conversation
        digest = ""
    if digest:
        amorce.append({"role": "system", "content": digest})

    # Outils présentés au LLM : les outils en dur + les capacités découvertes dans les
    # manifests (S64), TRIÉS par nom (préfixe stable, S90a). Avec la porte (S90), les
    # capacités de niveau ≥ 1 restent différées derrière `competence_charger` tant que le LLM
    # ne les a pas chargées dans CETTE conversation (`competences_chargees`). OFF par défaut.
    competences_chargees: set[str] = set()
    outils_actifs = outils.outils_pour(registre, chargees=competences_chargees,
                                        porte=outils.PORTE_PROGRESSIVE)

    # Conscience de soi (S65) : digest COMPACT de l'anatomie du Cœur (ses organes/briques
    # + le nombre d'outils) injecté comme un repère, à la manière du digest d'identité. Il
    # nomme le corps et RENVOIE à l'outil `mes_capacites` pour le détail → fin des
    # confabulations sur « ce que je sais faire ». Best-effort : ne casse jamais un tour.
    try:
        corps = conscience.digest(registre, len(outils_actifs))
    except Exception:  # noqa: BLE001 — la conscience de soi ne doit jamais casser une conversation
        corps = ""
    if corps:
        amorce.append({"role": "system", "content": corps})

    # Instructions du projet (façon Claude Projects) : contexte propre à la conversation,
    # placé dans la zone volatile (après le préfixe stable caché S90, avant la date).
    if (instructions_projet or "").strip():
        amorce.append({"role": "system",
                       "content": "Contexte du projet en cours :\n" + instructions_projet.strip()})

    # Mémoire proactive : top-3 souvenirs récents injectés sans que l'assistant ait à demander.
    # Complète l'outil memoire_rappeler (réactif) — l'assistant a toujours le contexte de base.
    # Best-effort : brique down ou lente (>1,5 s) → silencieux, conversation non bloquée.
    try:
        _base_mem = catalogue.base_brique(registre, "memoire")
        if _base_mem:
            async with httpx.AsyncClient(timeout=1.5) as _mc:
                _r = await _mc.get(f"{_base_mem}/rappeler", params={"q": "", "limite": 3})
                if _r.status_code < 400:
                    _souvenirs = _r.json().get("souvenirs", [])
                    if _souvenirs:
                        _lignes = "\n".join(
                            f"- {s.get('titre') or (s.get('contenu') or '')[:80]}"
                            for s in _souvenirs
                        )
                        amorce.append({"role": "system",
                                       "content": f"Souvenirs récents :\n{_lignes}"})
    except Exception:  # noqa: BLE001
        pass

    # VOLATIL en dernier (S90a) : la date ferme le préfixe stable sans le casser.
    amorce.append({"role": "system", "content": contexte_date})

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

        # Proprioception (S68) : on retiendra le dernier message utilisateur et les outils
        # appelés pour, à la fin du tour, échantillonner l'échange à des fins d'auto-mesure.
        question = next((m.get("content") for m in reversed(messages)
                         if m.get("role") == "user"), "") or ""
        outils_appeles: list[str] = []

        # Routage d'outils par embeddings (opt-in ROUTAGE_OUTILS) : ne présenter au LLM que les
        # outils PERTINENTS pour la requête courante + le socle des outils en dur (toujours
        # pertinents). Repli honnête : liste inchangée si le routage est inactif/indisponible.
        # La conscience de soi (plus haut) garde, elle, le compte COMPLET → anatomie honnête.
        # ⚠ La requête de routage inclut le message assistant PRÉCÉDENT (pas seulement `question`) :
        # sinon une confirmation de gate (« oui ») perd ses mots-clés et l'outil EN ATTENTE tombe
        # hors du top_k → l'assistant improviserait un mauvais outil (cf. requete_depuis_messages).
        outils_actifs = await routage_outils.filtrer_outils(
            routage_outils.requete_depuis_messages(messages), outils_actifs,
            client=client, toujours=outils.noms_socle(registre))

        # S143 : guardrail instancié par conversation (jamais en global).
        # S221 : il porte le validateur d'arguments — le registre est capturé ici, le
        # guardrail reste ignorant des manifests.
        guardrail = guardrails_outils.Guardrail(
            valideur=lambda n, a: validation_args.valider(n, a, registre))

        # S144 MOA : conseil de modèles en parallèle sur les requêtes complexes (opt-in MOA_MODELES).
        # Guidance éphémère — injectée pour ce seul appel, jamais persistée dans le journal.
        config_moa = moa._depuis_env()
        if config_moa and moa.est_complexe(question):
            try:
                guidance = await moa.consulter(historique, config_moa, client)
                historique = historique + [{"role": "system", "content": f"[Conseil MOA]\n{guidance}"}]
            except Exception:  # noqa: BLE001 — MOA jamais bloquant
                pass

        for iteration in range(MAX_ITERATIONS):
            # Pipeline unifié (S138) : trimming + bascule de modèles + comptage
            # tokens/coût + journal. La logique d'outils reste ici, côté agent.
            # S60 : en streaming, on émet le texte en `texte_delta` au fil de l'eau et on
            # réassemble le message (avec ses tool_calls) pour piloter la boucle d'outils.
            message = None
            if STREAM_ACTIF:
                erreur = None
                async for evt in llm_pipeline.completer_flux(
                        historique, modeles=modeles, tools=outils_actifs,
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
                    historique, modeles=modeles, tools=outils_actifs,
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
                # Proprioception (S68) : capture échantillonnée de l'échange (opt-in, jamais
                # bloquante). `message.content` porte la réponse finale dans les deux chemins.
                if proprioception.echantillonne(conf):
                    try:
                        proprioception.tracer(question, message.get("content") or "",
                                              etiquette="chat",
                                              modele=res.modele_utilise if not STREAM_ACTIF else None,
                                              outils=outils_appeles)
                    except Exception:  # noqa: BLE001 — l'auto-mesure ne casse jamais un tour
                        pass
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
                outils_appeles.append(nom)

                # S143 — guardrail : décision avant l'appel (block = pas d'appel réel).
                g_action, g_msg = guardrail.before_call(nom, args)
                g_note = g_msg if g_action == "warn" else None

                # S222 — gate structurel. Une action confirmée n'est recevable que si le
                # Cœur a enregistré un accord pour CES arguments exacts ; un accord ne
                # naît que d'un vrai tour de parole humain (cf. accord_action).
                est_une_action = outils.est_action(nom, registre)
                refus_accord = None
                if est_une_action:
                    if args.get("confirme"):
                        _ok, refus_accord = accord_action.REGISTRE.consommer(
                            fil_accord, nom, args)
                    else:
                        # Appel sans `confirme` : c'est la DEMANDE. Sans cet enregistrement,
                        # aucun `confirme=true` ultérieur ne sera jamais recevable.
                        accord_action.REGISTRE.demander(fil_accord, nom, args)
                else:
                    note_lot = accord_action.REGISTRE.noter_lecture(fil_accord, nom)
                    if note_lot:
                        g_note = (g_note + " | " + note_lot) if g_note else note_lot

                # S165 — fil d'activité : la brique d'origine accompagne l'appel, le
                # front peut afficher « brique › outil » dans la task trace.
                yield {"type": "outil", "nom": nom, "args": args,
                       "action": est_une_action,
                       "brique": outils.brique_de(nom, registre)}

                if g_action in ("block", "halt"):
                    resultat = json.dumps(
                        {"erreur": f"[GUARDRAIL] {g_msg}"}, ensure_ascii=False)
                    # S221 : un appel bloqué EST un échec — sans ça, un LLM qui s'obstine
                    # sur les mêmes arguments invalides reboucle jusqu'à MAX_ITERATIONS
                    # sans que les compteurs d'échec identique ne le coupent jamais.
                    guardrail.after_call(nom, args, resultat, erreur=True)
                elif refus_accord:
                    # `confirmation_requise` est conservé : le drapeau SSE et les boutons
                    # d'action (S76) continuent de s'afficher exactement comme avant.
                    # ⚠ On ne nourrit PAS les compteurs d'échec du guardrail ici : l'accord
                    # va arriver au tour suivant, et un outil déjà marqué « en échec 4× »
                    # resterait bloqué APRÈS le oui de l'utilisateur.
                    resultat = json.dumps(
                        {"erreur": f"[GATE] {refus_accord}", "confirmation_requise": True},
                        ensure_ascii=False)
                else:
                    resultat = await outils.executer(nom, args, registre)
                    # S143 — mise à jour de l'état + idempotence.
                    guardrail.after_call(nom, args, resultat,
                                         erreur=_est_erreur_outil(resultat))
                    if not _est_erreur_outil(resultat):
                        import graphe_apprentissage as _ga  # import local — évite cycle potentiel
                        try:
                            _ga._graphe.noter_usage(nom)
                        except Exception:  # noqa: BLE001 — jamais bloquant
                            pass
                    g_idem_action, g_idem_msg = guardrail.verifier_idempotence(nom, args)
                    if g_idem_msg:
                        g_note = (g_note + " | " + g_idem_msg) if g_note else g_idem_msg
                    if g_note:
                        try:
                            _data = json.loads(resultat)
                            _data["_guardrail"] = g_note
                            resultat = json.dumps(_data, ensure_ascii=False)
                        except Exception:  # noqa: BLE001
                            resultat += f"\n[GUARDRAIL] {g_note}"
                    # La porte (S90) : si le LLM vient d'ouvrir une compétence différée, on
                    # l'ajoute aux outils du tour suivant (son schéma devient appelable).
                    if nom == outils.META_CHARGER and '"ok": true' in resultat:
                        cible = (args or {}).get("nom")
                        if cible:
                            competences_chargees.add(cible)
                            outils_actifs = outils.outils_pour(
                                registre, chargees=competences_chargees, porte=True)

                confirmation = '"confirmation_requise": true' in resultat
                # S165 — `ok` dit au fil d'activité si l'appel a réussi (statut ✓/✖).
                yield {"type": "resultat_outil", "nom": nom,
                       "resultat": resultat, "confirmation": confirmation,
                       "ok": not _est_erreur_outil(resultat)}
                # Actions suggérées (S76) : boutons d'action génériques (web + Mini App).
                # Le tap injecte un message ; il ne court-circuite jamais le gate humain.
                sugg = suggestions.pour_resultat(nom, args, resultat, confirmation=confirmation)
                if sugg:
                    yield {"type": "actions", "actions": sugg}
                historique.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": resultat,
                })

        yield {"type": "texte",
               "contenu": "J'ai atteint la limite d'étapes pour cette demande. Reformule si besoin."}
        yield {"type": "fin"}
