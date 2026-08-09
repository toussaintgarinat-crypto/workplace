"""Routes « assistant » du Cœur (extrait de main.py, S114).

Assistant : chat, conversations, projets, config, briefing, pouls, rappels.
"""
import os
import json
import httpx
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from etat import registre
import accord_action
import agenda
import assistant
import auth
import briefing
import catalogue
import ciblage
import classer
import config_assistant
import contexte_tenant
import horloge
import journal_conversations
import journal_usage
import langue as langue_mod
import orchestrateur
import personas
import pouls
import proactif
import projets as projets_mod
import proprioception
import shadow

router = APIRouter()


@router.post("/briefing/executer", tags=["assistant"])
async def briefing_executer(forcer: bool = False):
    """Génère le briefing quotidien (RDV, impayés, pipeline, coût LLM de la veille)
    et le dépose en rappel 🔔. Synthèse par l'économe local (S138). Idempotent par
    jour ; `forcer=true` régénère. Déclenché chaque matin par l'horloge S29 via la
    tâche `briefing-quotidien` du manifest `noyau` (S30)."""
    return await briefing.executer(registre, forcer=forcer)


@router.get("/briefing/dernier", tags=["assistant"])
async def briefing_dernier():
    """Dernier briefing déposé (rappel de type `briefing`), s'il existe."""
    briefings = [r for r in proactif.lister(limite=60) if r.get("type") == "briefing"]
    return {"briefing": briefings[0] if briefings else None}


@router.post("/pouls/battre", tags=["assistant"])
async def pouls_battre(forcer: bool = False):
    """Fait battre le cœur (S67) : réveille le co-agent (S66) sur l'objectif récurrent,
    en autonomie et lecture seule, puis dépose sa synthèse en rappel 🔔. Borné par le
    budget quotidien de tokens. Idempotent par jour ; `forcer=true` rejoue. Déclenché
    par l'horloge S29 via la tâche `pouls-autonome` du manifest `noyau`."""
    return await pouls.battre(registre, forcer=forcer)


@router.get("/pouls/dernier", tags=["assistant"])
async def pouls_dernier():
    """Dernier point autonome déposé (rappel de type `pouls`), s'il existe."""
    points = [r for r in proactif.lister(limite=60) if r.get("type") == "pouls"]
    return {"pouls": points[0] if points else None}


@router.get("/proprioception", tags=["assistant"])
async def proprioception_rapport(limite: int = 15):
    """Proprioception (S68) : le Cœur mesure ses propres réponses échantillonnées (juge
    LLM gratuit, repli heuristique honnête) et PROPOSE des cibles d'amélioration (S69
    prompts / S70 capacités). Lecture seule : ne modifie ni prompts ni code."""
    return await proprioception.mesurer(limite=limite)


# ── Auto-amélioration des prompts (S69) : proposer → évaluer → gate humain ───


def _resoudre_utilisateur(corps: dict, request: Request) -> str | None:
    """Identité à poser dans `contexte_tenant` pour ce tour de conversation.

    Priorité : `utilisateur` explicite du corps (Telegram/S2S, S78 — déjà résolu par
    `briques/connexion` ou un appelant S2S) > sub de la session web S171 si présente >
    `None` (défaut `"perso"` inchangé côté agenda). Jamais bloquant : une session
    absente/corrompue ne fait pas échouer le chat, elle retombe simplement au défaut."""
    return corps.get("utilisateur") or auth.sub_session_optionnel(request)


@router.post("/assistant/chat", tags=["assistant"])
async def assistant_chat(corps: dict, request: Request):
    """Conversation avec l'assistant. Corps : {"messages": [{role, content}, …]}.

    Répond en `text/event-stream` : chaque ligne `data:` est un événement JSON
    (texte, outil, resultat_outil, fin, erreur).

    Champs optionnels pour la TRACE unifiée (S78) : `surface` (web/telegram/…),
    `interlocuteur` (qui), `utilisateur` (compte). La conversation est journalisée côté
    Cœur quelle que soit la surface — best-effort, jamais bloquant.

    Champ optionnel `cible` (S165) : nom de la brique sur laquelle l'utilisateur a
    déposé le jeton assistant — son contexte est injecté dans la zone volatile.
    Champ optionnel `capture` (S165 « yeux ») : {"data": <base64>} — capture d'écran
    de la zone ciblée, lue par la brique vision (OCR) puis injectée au même endroit."""
    messages = corps.get("messages") or []
    surface = corps.get("surface") or "web"
    interlocuteur = corps.get("interlocuteur") or "dashboard"
    utilisateur = _resoudre_utilisateur(corps, request)
    # Le champ `utilisateur` du corps (surfaces Telegram/Mini App, S78) raffine le
    # contexte de tenant déjà posé par la dépendance depuis les en-têtes (S121) : les
    # appels d'outils du tour (agenda/donnees/forge) porteront cette identité.
    if utilisateur:
        contexte_tenant.definir_contexte(utilisateur=utilisateur)
    fil = journal_conversations.fil(surface, interlocuteur)

    # Projet de la conversation (façon Claude Projects) : on prend le `projet_id` du corps
    # si fourni, sinon celui déjà rattaché au fil ; ses instructions nourrissent le prompt.
    projet_id = corps.get("projet_id") or journal_conversations.meta(fil).get("projet_id")
    instructions_projet = projets_mod.contexte_de(projet_id)

    # Ciblage (S165) : l'utilisateur a déposé le jeton assistant sur une brique →
    # son contexte (rôle + capacités) rejoint la zone volatile. Contexte, pas pouvoir :
    # les gates de confirmation restent inchangés.
    instructions_projet = ciblage.fusionner_instructions(
        instructions_projet, corps.get("cible"), registre)

    # Yeux (S165 phase 2) : la capture de la zone déposée est lue par la brique vision
    # (OCR souverain 5960) → l'assistant LIT ce qui est à l'écran, pas seulement le
    # manifest. Échec de lecture = note honnête, jamais un texte inventé.
    instructions_projet = await ciblage.fusionner_capture(
        instructions_projet, corps.get("capture"), registre)

    # Vision multimodale : si le client envoie une image (data + mime_type), on l'injecte
    # dans le dernier message utilisateur au format OpenAI multimodal → LiteLLM la route.
    vision_image = corps.get("vision_image")
    if vision_image and vision_image.get("data"):
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                texte = messages[i].get("content") or ""
                if isinstance(texte, str):  # ne pas ré-emballer si déjà multimodal
                    messages[i] = {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": texte},
                            {"type": "image_url", "image_url": {
                                "url": f"data:{vision_image.get('mime_type', 'image/jpeg')};base64,{vision_image['data']}"
                            }}
                        ]
                    }
                break

    # Trace : on enregistre le DERNIER message utilisateur avant de répondre.
    # Si le contenu est multimodal (liste), on extrait uniquement le texte.
    dernier_user_brut = next((m.get("content") for m in reversed(messages)
                              if m.get("role") == "user"), None)
    dernier_user = (
        " ".join(p.get("text", "") for p in dernier_user_brut if isinstance(p, dict) and p.get("type") == "text")
        if isinstance(dernier_user_brut, list)
        else (dernier_user_brut or "")
    )
    if dernier_user:
        journal_conversations.enregistrer(surface, interlocuteur, "user", dernier_user,
                                          utilisateur=utilisateur)

    # S222 — le tour de parole humain. C'est le SEUL endroit où une demande de confirmation
    # en attente devient un accord : sans passage par ici, aucun `confirme=true` du LLM
    # n'est recevable. Un refus explicite (« non », « annule ») révoque au lieu d'accorder.
    #
    # ⚠ La clé n'est PAS `fil` seul. Sur le web, `journal_conversations.fil()` vaut
    # « web:dashboard » pour TOUT LE MONDE (l'interlocuteur est la surface, pas la
    # personne) : depuis l'identité multi-utilisateur du Cœur (S182/S217), deux personnes
    # connectées partageraient alors le même registre d'accords, et le « oui » de l'une
    # validerait l'action en attente de l'autre.
    fil_accord = accord_action.cle(fil, utilisateur)
    accord_action.REGISTRE.tour_utilisateur(fil_accord, dernier_user or "")

    async def flux():
        final = ""
        try:
            async for evt in assistant.converser(messages, registre,
                                                  instructions_projet=instructions_projet,
                                                  fil=fil_accord):
                t = evt.get("type")
                if t == "texte_delta":
                    final += evt.get("contenu") or ""
                elif t == "texte":
                    final = evt.get("contenu") or ""
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'erreur', 'contenu': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            # Trace : on enregistre la réponse de l'assistant une fois le tour terminé.
            if final.strip():
                journal_conversations.enregistrer(surface, interlocuteur, "assistant", final,
                                                  utilisateur=utilisateur)

    return StreamingResponse(flux(), media_type="text/event-stream")


@router.get("/assistant/conversations", tags=["assistant"])
async def assistant_conversations(fil: str | None = None, limite: int = 100,
                                  projet: str | None = None):
    """Trace UNIFIÉE des conversations (S78), toutes surfaces confondues. Sans `fil` :
    la liste des fils (titre, projet, aperçu). Avec `fil` : les messages de ce fil.
    `projet` filtre la liste sur les conversations rattachées à ce projet."""
    if fil:
        return {"fil": fil, "messages": journal_conversations.messages(fil, limite),
                "meta": journal_conversations.meta(fil)}
    return {"fils": journal_conversations.fils(limite, projet_id=projet)}


@router.get("/assistant/historique_utilisateur", tags=["assistant"])
async def assistant_historique_utilisateur(utilisateur: str, limite: int = 40):
    """Historique CROSS-SURFACE d'un compte : fusionne tous ses fils (web, Telegram, tout
    autre canal) du journal unifié (S78), triés chronologiquement. Sert `briques/connexion`
    (le pont) à construire le contexte envoyé au LLM avec la mémoire des autres surfaces,
    plutôt que le seul fil local du canal en cours."""
    lignes = journal_conversations.messages_utilisateur(utilisateur, limite)
    return {"messages": [{"role": l.get("role"), "content": l.get("content")} for l in lignes]}


@router.post("/assistant/conversations/reordonner", tags=["assistant"])
async def assistant_conversations_reordonner(corps: dict):
    """Réordonne les conversations par cliquer-déposer (S104). `fils` = la nouvelle suite ;
    chaque conversation reçoit son rang comme `ordre`."""
    return {"ok": True, "ordonnees": journal_conversations.reordonner(corps.get("fils") or [])}


@router.patch("/assistant/conversations/{fil:path}", tags=["assistant"])
async def assistant_conversation_modifier(fil: str, corps: dict):
    """Modifie la méta d'une conversation : `titre`, `projet_id`, `epingle`, `archive`, `ordre`.
    Seuls les champs présents sont touchés (façon « renommer » / « ranger dans un projet »)."""
    champs = {k: corps[k] for k in ("titre", "projet_id", "epingle", "archive", "ordre") if k in corps}
    if "titre" in champs:
        champs["titre"] = (champs["titre"] or "").strip()
    return {"ok": True, "meta": journal_conversations.definir_meta(fil, **champs)}


@router.delete("/assistant/conversations/{fil:path}", tags=["assistant"])
async def assistant_conversation_supprimer(fil: str):
    """Supprime une conversation (ses messages ET sa méta)."""
    journal_conversations.supprimer_fil(fil)
    return {"ok": True}


@router.get("/assistant/projets", tags=["assistant"])
async def assistant_projets():
    """Liste des projets (façon Claude Projects / Perplexity Spaces) avec compteur de
    conversations rattachées."""
    fils = journal_conversations.fils(limite=10000)
    par_projet: dict[str, int] = {}
    for f in fils:
        pid = f.get("projet_id")
        if pid:
            par_projet[pid] = par_projet.get(pid, 0) + 1
    projets = projets_mod.lister()
    for p in projets:
        p["conversations"] = par_projet.get(p["id"], 0)
    return {"projets": projets}


@router.post("/assistant/projets", tags=["assistant"])
async def assistant_projet_creer(corps: dict):
    """Crée un projet : `nom` (requis), `instructions` (contexte propre), `documents` (refs)."""
    p = projets_mod.creer(nom=corps.get("nom") or "", instructions=corps.get("instructions") or "",
                          documents=corps.get("documents") or [], couleur=corps.get("couleur"))
    return {"ok": True, "projet": p}


@router.patch("/assistant/projets/{projet_id}", tags=["assistant"])
async def assistant_projet_modifier(projet_id: str, corps: dict):
    """Met à jour un projet (nom, instructions, documents, couleur)."""
    p = projets_mod.modifier(projet_id, nom=corps.get("nom"),
                             instructions=corps.get("instructions"),
                             documents=corps.get("documents"), couleur=corps.get("couleur"))
    if not p:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return {"ok": True, "projet": p}


@router.delete("/assistant/projets/{projet_id}", tags=["assistant"])
async def assistant_projet_supprimer(projet_id: str):
    """Supprime un projet ; ses conversations sont DÉTACHÉES (elles ne sont pas effacées)."""
    detachees = journal_conversations.detacher_projet(projet_id)
    ok = projets_mod.supprimer(projet_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return {"ok": True, "conversations_detachees": detachees}


@router.get("/assistant/config", tags=["assistant"])
async def assistant_config_get():
    """État du « cerveau » : modèle courant, modèles disponibles, clé OpenRouter définie ?"""
    conf = config_assistant.charger()
    return {
        "model": conf["model"],
        "fallback_models": conf["fallback_models"],
        "modeles_disponibles": await config_assistant.lister_modeles(),
        "cle_openrouter_definie": config_assistant.cle_openrouter_definie(),
        # Clés des autres fournisseurs LLM (Anthropic, Groq, OpenCode Go…) : état défini/absent.
        "cles_fournisseurs": config_assistant.cles_fournisseurs_etat(),
        "voix_provider": conf["voix_provider"],
        "unmute_url": conf["unmute_url"],
        "wakeword_url": conf["wakeword_url"],
        "voix_fin_mode": conf["voix_fin_mode"],
        "voix_silence_ms": conf["voix_silence_ms"],
        "persona": conf["persona"],
        "personas": personas.catalogue(),
        "langue": conf["langue"],
        "langues": langue_mod.catalogue(),
        "routage_actif": conf["routage_actif"],
        "modele_econome": conf["modele_econome"],
        # Cascade auto (cost-first) : gratuits → repli payant, + chaîne effective.
        "cascade_auto": conf["cascade_auto"],
        "repli_payant": conf["repli_payant"],
        "cascade_free_n": conf["cascade_free_n"],
        "chaine_effective": await config_assistant.chaine_modeles(conf),
        # Muscle déporté (brique calcul, roadmap S58) : opt-in + état des nœuds.
        "muscle_actif": conf["muscle_actif"],
        # Repli souverain CPU sur le Cœur (S62) : dernier maillon local de la cascade.
        "repli_souverain": conf["repli_souverain"],
        "repli_souverain_avant_payant": conf["repli_souverain_avant_payant"],
    }


@router.get("/assistant/muscle", tags=["assistant"])
async def assistant_muscle_get():
    """État du « Muscle » déporté : opt-in actif ? + nœuds de calcul connus (brique calcul)."""
    import muscle
    conf = config_assistant.charger()
    return {"muscle_actif": conf["muscle_actif"], **await muscle.etat()}


@router.post("/assistant/muscle", tags=["assistant"])
async def assistant_muscle_post(corps: dict):
    """Active/désactive le recours au muscle déporté. Corps : {"actif": bool}."""
    conf = config_assistant.definir_muscle(corps.get("actif"))
    return {"muscle_actif": conf["muscle_actif"]}


@router.post("/assistant/routage", tags=["assistant"])
async def assistant_routage_post(corps: dict):
    """Active/désactive le routage dynamique (S138) et fixe le modèle économe.

    Corps : {"actif": bool?, "modele_econome": "free/..."?}."""
    conf = config_assistant.definir_routage(corps.get("actif"), corps.get("modele_econome"))
    return {"routage_actif": conf["routage_actif"], "modele_econome": conf["modele_econome"]}


@router.post("/assistant/config", tags=["assistant"])
async def assistant_config_post(corps: dict):
    """Règle le cerveau de l'assistant (effet immédiat).

    Corps (tous optionnels) :
    - "model"            : modèle mis EN TÊTE de la cascade ("" = pas de tête, cascade pure) ;
    - "fallback_models"  : repli manuel (mode cascade_auto=false) ;
    - "cascade_auto"     : true = gratuits auto → repli payant ; false = [model]+fallbacks ;
    - "repli_payant"     : modèle payant final de la cascade ;
    - "cascade_free_n"   : nombre de gratuits essayés avant le repli ;
    - "repli_souverain"  : modèle CPU local, dernier maillon souverain (S62) ;
    - "repli_souverain_avant_payant" : true = souveraineté d'abord (avant le payant cloud).
    """
    if any(k in corps for k in ("cascade_auto", "repli_payant", "cascade_free_n")):
        config_assistant.definir_cascade(
            actif=corps.get("cascade_auto"),
            repli=corps.get("repli_payant"),
            n=corps.get("cascade_free_n"),
        )
    if "repli_souverain" in corps or "repli_souverain_avant_payant" in corps:
        config_assistant.definir_repli_souverain(
            modele=corps.get("repli_souverain"),
            avant_payant=corps.get("repli_souverain_avant_payant"),
        )
    if "model" in corps or "fallback_models" in corps:
        config_assistant.definir_modele(corps.get("model"), corps.get("fallback_models"))

    conf = config_assistant.charger()
    chaine = await config_assistant.chaine_modeles(conf)
    # On teste le 1er modèle réellement essayé (tête de cascade), pas un champ figé.
    tete = chaine[0] if chaine else (conf.get("model") or conf.get("repli_payant"))
    ok, detail = await config_assistant.tester_modele(tete)
    return {"ok": ok, "config": conf, "chaine_effective": chaine, "tete": tete, "detail": detail}


# ── Profil utilisateur (contexte d'amorçage, éditable depuis le dashboard) ──
# Le défaut est baké dans l'image (core/profil_defaut.md → /app) ; les modifs sont
# persistées dans le volume du Cœur (/data/profil.md) et survivent aux rebuilds.
PROFIL_PATH = os.getenv("PROFIL_PATH", "/data/profil.md")
PROFIL_DEFAUT_PATH = os.getenv("PROFIL_DEFAUT_PATH", "/app/profil_defaut.md")


@router.get("/assistant/usage", tags=["assistant"])
async def assistant_usage_get():
    """Suivi des coûts LLM (S138) : tokens & dépense du jour / du mois / total,
    état des budgets, hits de cache, tokens économisés (trim) et appels rétrogradés."""
    return journal_usage.resume()


@router.get("/assistant/shadow", tags=["assistant"])
async def assistant_shadow_get():
    """Rapport shadow (S138-4) : par flux, score d'équivalence d'un candidat moins
    cher, économie observée et recommandation de rétrogradation."""
    return shadow.rapport()


@router.post("/assistant/persona", tags=["assistant"])
async def assistant_persona_post(corps: dict):
    """Change la personnalité de l'assistant (effet immédiat au prochain message)."""
    conf = config_assistant.definir_persona(corps.get("persona"))
    return {"ok": True, "persona": conf["persona"]}


@router.post("/assistant/langue", tags=["assistant"])
async def assistant_langue_post(corps: dict):
    """Change la langue du Jarvis — réponses ET voix (effet immédiat, S39).

    Corps : {"langue": "fr"|"en"|"es"}. Toute langue inconnue retombe sur `fr`."""
    conf = config_assistant.definir_langue(corps.get("langue"))
    return {"ok": True, "langue": conf["langue"],
            "locale_voix": langue_mod.locale_voix(conf["langue"])}


@router.post("/assistant/voix", tags=["assistant"])
async def assistant_voix_post(corps: dict):
    """Règle le fournisseur de voix et les URLs (effet au prochain chargement du front).

    Corps : {"voix_provider": "webspeech"|"unmute"|"wakeword",
             "unmute_url": "wss://…"?, "wakeword_url": "ws://…/ecoute"?,
             "voix_fin_mode": "appui"|"silence"?, "voix_silence_ms": int?}."""
    conf = config_assistant.definir_voix(
        corps.get("voix_provider"), corps.get("unmute_url"), corps.get("wakeword_url"),
        corps.get("voix_fin_mode"), corps.get("voix_silence_ms"))
    return {"ok": True, "voix_provider": conf["voix_provider"],
            "unmute_url": conf["unmute_url"], "wakeword_url": conf["wakeword_url"],
            "voix_fin_mode": conf["voix_fin_mode"], "voix_silence_ms": conf["voix_silence_ms"]}


@router.post("/assistant/cle-openrouter", tags=["assistant"])
async def assistant_cle_openrouter(corps: dict):
    """Enregistre une clé OpenRouter, recrée la Gateway, puis valide par une complétion.

    Corps : {"cle": "sk-or-..."}."""
    cle = (corps.get("cle") or "").strip()
    if not cle:
        raise HTTPException(status_code=400, detail="La clé est vide.")
    config_assistant._ecrire_cle(cle)
    if not await config_assistant.recreer_gateway():
        return {"ok": False, "etape": "recreation",
                "detail": "Conteneur de la Gateway introuvable (le Cœur a-t-il accès au socket Docker ?)."}
    if not await config_assistant.attendre_gateway():
        return {"ok": False, "etape": "attente",
                "detail": "La Gateway n'est pas redevenue joignable après recréation."}
    conf = config_assistant.charger()
    ok, detail = await config_assistant.tester_modele(conf["model"])
    return {"ok": ok, "etape": "fini" if ok else "test", "detail": detail,
            "cle_openrouter_definie": config_assistant.cle_openrouter_definie()}


@router.post("/assistant/cle-fournisseur", tags=["assistant"])
async def assistant_cle_fournisseur(corps: dict):
    """Enregistre la clé d'un fournisseur LLM (Anthropic, Groq, OpenCode Go…) puis
    recrée la Gateway pour qu'elle la prenne en compte.

    Corps : {"fournisseur": "groq"|"anthropic"|…, "cle": "..."}.
    Contrairement à /assistant/cle-openrouter, ne lance PAS de complétion de test :
    le modèle actif n'est pas forcément celui de ce fournisseur. On confirme que la
    clé est écrite et que la Gateway est redevenue joignable. Pour l'utiliser, choisir
    ensuite un de ses modèles dans ⚙ Cerveau → Modèle LLM."""
    fid = (corps.get("fournisseur") or "").strip()
    cle = (corps.get("cle") or "").strip()
    nom_env = config_assistant._ENV_PAR_ID.get(fid)
    if not nom_env:
        raise HTTPException(status_code=400, detail=f"Fournisseur inconnu : {fid!r}.")
    if not cle:
        raise HTTPException(status_code=400, detail="La clé est vide.")
    config_assistant._ecrire_cle_env(nom_env, cle)
    if not await config_assistant.recreer_gateway():
        return {"ok": False, "etape": "recreation",
                "detail": "Conteneur de la Gateway introuvable (accès au socket Docker ?).",
                "cles_fournisseurs": config_assistant.cles_fournisseurs_etat()}
    joignable = await config_assistant.attendre_gateway()
    return {"ok": joignable, "etape": "fini" if joignable else "attente",
            "detail": "Gateway redémarrée." if joignable else "Gateway injoignable après recréation.",
            "cles_fournisseurs": config_assistant.cles_fournisseurs_etat()}


@router.post("/assistant/document", tags=["assistant"])
async def assistant_document(fichier: UploadFile = File(...)):
    """Dépose un document : l'ingère (brique `ingestion`), le fait CLASSER par le LLM, puis range
    le classement dans ses métadonnées. Renvoie le classement au front.

    Le résumé n'est PAS écrit en Mémoire ici (action sensible) : le front le propose."""
    ingestion = orchestrateur._brique_base(registre, "ingestion")
    contenu = await fichier.read()
    if not contenu:
        raise HTTPException(status_code=400, detail="Fichier vide.")

    entetes_ingestion = orchestrateur.entetes_brique("ingestion")
    async with httpx.AsyncClient(timeout=120) as client:
        # 1) Ingestion (extraction de texte) par la brique dédiée.
        r = await client.post(
            f"{ingestion}/ingerer",
            files={"fichier": (fichier.filename or "document", contenu,
                               fichier.content_type or "application/octet-stream")},
            headers=entetes_ingestion,
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Ingestion échouée : {r.text}")
        doc_id = r.json().get("id")

        # 2) Récupération du texte extrait.
        d = await client.get(f"{ingestion}/documents/{doc_id}", headers=entetes_ingestion)
        texte = d.json().get("texte_extrait", "") if d.status_code < 400 else ""

        # 3) Classement par le LLM (même cerveau que l'assistant).
        classement = await classer.classer_texte(texte, fichier.filename or "document")

        # 4) Persistance du classement dans les métadonnées du document.
        await client.patch(f"{ingestion}/documents/{doc_id}/classement", json=classement,
                           headers=entetes_ingestion)

    texte_tronque = texte[:6000] + ("\n…[tronqué]" if len(texte) > 6000 else "")
    return {"doc_id": doc_id, "nom": fichier.filename,
            "nb_caracteres": len(texte), "classement": classement,
            "texte_extrait": texte_tronque}


@router.get("/assistant/rappels", tags=["assistant"])
async def assistant_rappels(non_lus: bool = False):
    """Rappels proactifs (agenda imminent, documents à classer…)."""
    return {"rappels": proactif.lister(non_lus=non_lus), "non_lus": proactif.compter_non_lus()}


@router.post("/assistant/rappels/check", tags=["assistant"])
async def assistant_rappels_check():
    """Force une vérification proactive immédiate (utile pour tester sans attendre le tick)."""
    nb = await proactif.run_check(registre)
    return {"nouveaux": nb, "non_lus": proactif.compter_non_lus()}


@router.post("/assistant/rappels/{rappel_id}/vu", tags=["assistant"])
async def assistant_rappel_vu(rappel_id: str):
    return {"ok": proactif.marquer_vu(rappel_id), "non_lus": proactif.compter_non_lus()}


@router.get("/assistant/dossiers", tags=["assistant"])
async def assistant_dossiers():
    """Dossiers (projets + catégories avec compteurs), relayés depuis la brique `ingestion`."""
    ingestion = orchestrateur._brique_base(registre, "ingestion")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{ingestion}/dossiers",
                                 headers=orchestrateur.entetes_brique("ingestion"))
            return r.json() if r.status_code < 400 else {"projets": {}, "categories": {}}
    except httpx.HTTPError:
        return {"projets": {}, "categories": {}}
