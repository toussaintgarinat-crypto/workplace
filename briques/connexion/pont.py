"""Le pont — orchestration d'un message entrant jusqu'à la réponse de l'assistant.

Pour chaque message reçu d'un réseau :
  1. on vérifie le CONSENTEMENT (correspondance) — un inconnu reçoit un accueil, pas l'assistant ;
  2. on charge l'historique de l'interlocuteur — CROSS-SURFACE (web + tout autre canal du
     même compte) si activé (`CONNEXION_HISTORIQUE_CROISE`), sinon le seul fil local
     (conversations) ;
  3. on construit les messages (système « qui parle » + historique + nouveau message) ;
  4. on interroge l'assistant du Cœur (client_assistant, flux SSE) ;
  5. on persiste le tour et on renvoie la réponse sur le réseau d'origine.

Repli HONNÊTE partout : assistant injoignable → message d'excuse clair (jamais une fausse
réponse) ; réseau injoignable à l'envoi → on journalise sans rien perdre en silence.
"""
import logging
import os
import re

import httpx

import adaptateurs
import client_assistant
import conversations
import correspondance
import voix

_CB = re.compile(r"ap:([0-9a-f]{32}):(ok|ko)")          # utilisé avec fullmatch
_CODE = re.compile(r"[0-9]{6}")                         # ASCII seulement (pas d'autres chiffres)
_log = logging.getLogger(__name__)

_EXT_IMAGE = ("png", "jpg", "jpeg", "webp", "gif")

_REPLI = ("Désolé, je n'arrive pas à joindre l'assistant pour l'instant. "
          "Réessaie dans un petit moment.")

_REPLI_VOIX = ("🎤 J'ai bien reçu ton message vocal, mais je n'ai pas réussi à le transcrire "
               "(moteur de transcription indisponible). Peux-tu réessayer ou m'écrire ?")


def _accueil(reseau: str, corr: dict) -> str:
    """Message envoyé à un interlocuteur pas encore relié (consentement)."""
    code = corr.get("code")
    return (f"Bonjour 👋 Je suis l'assistant de Workplace, mais tu n'es pas encore relié à "
            f"un compte. Communique ce code à l'administrateur pour être autorisé : {code}")


def _construire(reseau: str, entrant, corr: dict, historique: list) -> list:
    """Messages envoyés à l'assistant : un *système* « qui parle » + l'historique + le message."""
    qui = corr.get("nom") or entrant.nom or "un interlocuteur"
    util = corr.get("utilisateur")
    contexte = (f"Tu es l'assistant de Workplace. Tu dialogues via {reseau} avec « {qui} »"
                + (f" (compte Workplace : {util})." if util else ".")
                + " Réponds en texte clair, concis, adapté à la messagerie.")
    return [{"role": "system", "content": contexte}, *historique,
            {"role": "user", "content": entrant.texte}]


def _historique_croise_actif() -> bool:
    """Historique cross-surface activé ? (env `CONNEXION_HISTORIQUE_CROISE`, défaut off —
    à activer explicitement une fois le Cœur à jour avec `/assistant/historique_utilisateur`)."""
    return str(os.getenv("CONNEXION_HISTORIQUE_CROISE", "0")).strip().lower() in (
        "1", "true", "oui", "on")


async def _historique_pour(reseau: str, id_externe: str, utilisateur: str | None) -> list:
    """L'historique envoyé à l'assistant pour construire le tour : CROSS-SURFACE (web +
    Telegram + tout autre canal relié au même compte) si le compte est connu et la fusion
    activée, sinon repli sur le fil local à CE seul canal.

    Repli HONNÊTE : Cœur injoignable/en erreur → on ne bloque jamais le tour, on retombe
    simplement sur le fil local (moins riche mais jamais une panne)."""
    if utilisateur and _historique_croise_actif():
        try:
            fusionne = await client_assistant.historique_utilisateur(utilisateur)
            if fusionne:
                return fusionne
        except Exception:  # noqa: BLE001 — Cœur injoignable → repli local honnête
            pass
    return conversations.charger(reseau, id_externe)


def _tts_actif() -> bool:
    """Réponse vocale activée ? (env `CONNEXION_TTS`, défaut on)."""
    return str(os.getenv("CONNEXION_TTS", "1")).strip().lower() in ("1", "true", "oui", "on")


_MOTS_VOCAL = ("vocal", "à voix haute", "lis-moi", "synthèse vocale",
               "synthétise", "mp3", "tts", "fais-moi entendre", "dis à voix")


def _demande_vocale(texte: str) -> bool:
    """Détecte si un message TEXTE demande explicitement une réponse en audio."""
    t = (texte or "").lower()
    return any(mot in t for mot in _MOTS_VOCAL)


async def _vocaliser(ad, id_externe: str, texte: str, envoyer: bool) -> bool:
    """Synthétise `texte` (brique voix) et l'envoie en vocal. Repli HONNÊTE : moteur TTS
    indisponible (placeholder) ou réseau KO → on n'envoie rien de faux, le texte est déjà parti."""
    if not (envoyer and ad.configure()):
        return False
    try:
        res = await voix.synthetiser(texte)
        if not res or not res.get("audio"):
            return False
        return await ad.envoyer_audio(id_externe, res["audio"], res.get("format") or "ogg")
    except Exception:  # noqa: BLE001 — moteur/réseau/adaptateur sans vocal → repli honnête
        return False


async def _envoyer_medias(ad, id_externe: str, medias: list) -> int:
    """Télécharge chaque média produit par un outil (image/vidéo/export, cf. `url_interne`
    dans client_assistant._extraire_media) et le relaie en pièce jointe sur le réseau
    d'origine — `sendPhoto` pour une image, `sendDocument` sinon (PDF/PPTX/HTML…). Repli
    HONNÊTE : un média KO (réseau, adaptateur sans pièce jointe) n'interrompt jamais les
    autres ni le texte déjà envoyé."""
    envoyes = 0
    async with httpx.AsyncClient(timeout=60) as c:
        for m in medias:
            url = m.get("url")
            if not url:
                continue
            try:
                r = await c.get(url)
                r.raise_for_status()
                nom = url.rsplit("/", 1)[-1]
                ext = nom.rsplit(".", 1)[-1].lower() if "." in nom else ""
                if ext in _EXT_IMAGE:
                    ok = await ad.envoyer_photo(id_externe, r.content, nom)
                else:
                    ok = await ad.envoyer_document(id_externe, r.content, nom)
                envoyes += 1 if ok else 0
            except (httpx.HTTPError, NotImplementedError):
                continue
    return envoyes


async def _transcrire_vocal(reseau: str, ad, entrant, envoyer: bool) -> dict:
    """Télécharge le vocal et le transcrit (Whisper local). Repli HONNÊTE si le moteur est
    KO ou ne rend qu'un place_holder : on prévient l'interlocuteur, on ne relaie rien de faux."""
    try:
        audio = await ad.telecharger_media(entrant.media_id)
        res = await voix.transcrire(audio, entrant.media_nom or "voix.ogg")
        texte = (res.get("texte") or "").strip()
        if texte and not res.get("place_holder"):
            return {"ok": True, "texte": texte}
    except Exception:  # noqa: BLE001 — réseau/moteur KO → repli honnête ci-dessous
        pass
    if envoyer and ad.configure():
        try:
            await ad.envoyer(entrant.id_externe, _REPLI_VOIX)
        except Exception:  # noqa: BLE001
            pass
    return {"ok": False, "raison": "transcription_indisponible", "reponse": _REPLI_VOIX}


_VERDICT = {"expiree": "⌛ Demande expirée.", "deja_decidee": "ℹ️ Demande déjà traitée."}
_BULLE = {"ok": "Décision enregistrée", "expiree": "Demande expirée",
          "deja_decidee": "Déjà traitée", "prerequis": "Pas encore prête : sauvegarde non vérifiée",
          "introuvable": "Demande inconnue"}


async def traiter_callback(reseau: str, cb) -> dict:
    """Clic sur un bouton d'approbation. TOUTE vérification d'identité est ici, AVANT le Cœur :
    callback_data strict, chat privé, chat == émetteur, approbateur explicite (« lie »). Sinon
    : ignoré SANS réponse (pas d'oracle), journalisé (identifiants seulement, jamais le data).
    Le Cœur fait confiance à `par` : l'armement du code n'a donc lieu qu'après ces contrôles."""
    ad = adaptateurs.obtenir(reseau)
    m = _CB.fullmatch(cb.data or "")
    if (ad is None or not m or cb.chat_type != "private" or cb.chat_id != cb.from_id
            or not correspondance.est_approbateur(reseau, cb.from_id)):
        _log.warning("Approbation : callback ignoré (from=%s chat=%s type=%s data_len=%d)",
                     cb.from_id, cb.chat_id, cb.chat_type, len(cb.data or ""))
        return {"ok": False, "raison": "ignore"}
    id_, decision = m.group(1), m.group(2)
    par = f"{reseau}:{cb.from_id}"

    async def _tg(coro):                          # Telegram best-effort : la décision est déjà prise
        try:
            await coro
        except Exception as e:  # noqa: BLE001
            _log.warning("Approbation : appel %s en échec (%s)", reseau, type(e).__name__)

    try:
        rep = await client_assistant.decider_approbation(id_, decision, par)
        if rep.get("raison") == "code_requis" and decision == "ok":
            armement = await client_assistant.armer_code(id_, par)
            if armement.get("ok"):
                code_demande = True
            else:
                code_demande, rep = False, armement
        else:
            code_demande = False
    except Exception:  # noqa: BLE001 — Cœur injoignable : repli honnête, aucune exécution
        await _tg(ad.repondre_callback(cb.callback_id, "Service indisponible, réessaie"))
        return {"ok": False, "raison": "noyau_injoignable"}
    if code_demande:
        await _tg(ad.repondre_callback(cb.callback_id, "Code requis"))
        await _tg(ad.envoyer(cb.chat_id, "🔐 Action destructive : saisis ici le code à "
                                         "6 chiffres affiché dans l'app Workplace "
                                         "(3 essais, 5 min)."))
        return {"ok": True, "raison": "code_demande"}
    raison = rep.get("raison")
    await _tg(ad.repondre_callback(cb.callback_id, _BULLE.get(raison, "Impossible")))
    if rep.get("ok") and raison == "ok":
        await _tg(ad.editer_message(cb.chat_id, cb.message_id,
                                    "✅ Approuvée." if decision == "ok" else "❌ Refusée."))
    elif raison in _VERDICT:
        await _tg(ad.editer_message(cb.chat_id, cb.message_id, _VERDICT[raison]))
    return {"ok": bool(rep.get("ok")), "raison": raison}


async def _tenter_code(reseau: str, ad, entrant) -> dict | None:
    """Un message « 123456 » d'un approbateur est un CODE potentiel, jamais une question pour
    le LLM. None => message ordinaire (relayé comme avant) ; pour un approbateur, 6 chiffres ne sont JAMAIS relayés. Si le Cœur est injoignable, on NE
    relaie PAS les chiffres (ça pourrait être un code) : on demande de réessayer."""
    texte = (entrant.texte or "").strip()
    if not _CODE.fullmatch(texte):
        return None
    if not correspondance.est_approbateur(reseau, entrant.id_externe):
        return None
    try:
        r = await client_assistant.soumettre_code(f"{reseau}:{entrant.id_externe}", texte)
    except Exception as e:  # noqa: BLE001
        _log.warning("Approbation : saisie de code, Cœur injoignable ou refusé (%s) — "
                     "APPROBATIONS_CLE configurée ?", type(e).__name__)
        try:
            await ad.envoyer(entrant.id_externe, "Service indisponible, réessaie.")
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "raison": "noyau_injoignable"}
    if not r.get("pris_en_charge"):
        # Un approbateur qui envoie 6 chiffres sans saisie armée : JAMAIS relayé au LLM ni
        # journalisé (ce pourrait être un code valable pour une demande qui vient de se régler).
        msg = "Aucune saisie de code en cours : appuie d'abord sur ✅ sur la demande concernée."
        try:
            await ad.envoyer(entrant.id_externe, msg)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "code": "aucune_saisie"}
    msg = {"ok": "✅ Code bon, action approuvée.",
           "code_faux": f"❌ Code faux — {r.get('restants', 0)} essai(s) restant(s).",
           "essais_epuises": "❌ 3 codes faux : demande REFUSÉE.",
           "expiree": "⌛ Demande expirée.",
           "deja_decidee": "ℹ️ Demande déjà traitée.",
           "prerequis": "⏳ Pas encore prête : sauvegarde non vérifiée."}.get(r.get("raison"),
                                                           "Code non pris en compte.")
    try:
        await ad.envoyer(entrant.id_externe, msg)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "code": r.get("raison")}


async def traiter(reseau: str, entrant, *, envoyer: bool = True,
                  source_authentifiee: bool = True) -> dict:
    """Traite un message entrant de bout en bout. Renvoie un compte-rendu (sans lever)."""
    ad = adaptateurs.obtenir(reseau)
    if ad is None:
        return {"ok": False, "raison": "reseau_inconnu", "reseau": reseau}

    corr = correspondance.resoudre(reseau, entrant.id_externe, entrant.nom)
    if not corr["autorise"]:
        accueil = _accueil(reseau, corr)
        if envoyer and ad.configure():
            try:
                await ad.envoyer(entrant.id_externe, accueil)
            except Exception:  # noqa: BLE001 — repli honnête, on ne masque pas l'état réel
                pass
        return {"ok": False, "raison": "non_autorise", "statut": corr["statut"],
                "code": corr.get("code"), "accueil": accueil}

    # Message vocal (autorisé) : transcrire AVANT de relayer (Whisper local souverain).
    transcrit = None
    if getattr(entrant, "media_type", None) == "audio" and not (entrant.texte or "").strip():
        cr = await _transcrire_vocal(reseau, ad, entrant, envoyer)
        if not cr["ok"]:
            return cr
        transcrit = entrant.texte = cr["texte"]

    if (not source_authentifiee and transcrit is None
            and _CODE.fullmatch((entrant.texte or "").strip())
            and correspondance.est_approbateur(reseau, entrant.id_externe)):
        # 6 chiffres d'un approbateur via une source SANS authentification (webhook sans
        # secret) : identité forgeable → ni soumis au Cœur, ni relayé au LLM. Abandon muet.
        return {"ok": True, "raison": "source_non_authentifiee"}

    if envoyer and transcrit is None and source_authentifiee and ad.configure():
        pris = await _tenter_code(reseau, ad, entrant)
        if pris is not None:
            return pris
    elif (transcrit is None and _CODE.fullmatch((entrant.texte or "").strip())
          and correspondance.est_approbateur(reseau, entrant.id_externe)):
        # Réseau non configuré / mode sans envoi : mêmes 6 chiffres, même règle — jamais relayés.
        return {"ok": True, "raison": "code_non_traite"}

    historique = await _historique_pour(reseau, entrant.id_externe, corr.get("utilisateur"))
    messages = _construire(reseau, entrant, corr, historique)

    verbeux = str(os.getenv("CONNEXION_VERBEUX", "0")).strip() in ("1", "true", "oui")
    repli = False
    medias: list = []
    try:
        reponse = await client_assistant.converser(
            messages, verbeux=verbeux, surface=reseau,
            interlocuteur=entrant.id_externe, utilisateur=corr.get("utilisateur"),
            medias=medias)
        if not reponse:
            reponse, repli = _REPLI, True
    except Exception:  # noqa: BLE001 — assistant KO → repli honnête, pas de fausse réponse
        reponse, repli = _REPLI, True

    conversations.ajouter(reseau, entrant.id_externe, "user", entrant.texte)
    conversations.ajouter(reseau, entrant.id_externe, "assistant", reponse)

    envoye = False
    if envoyer and ad.configure():
        try:
            envoye = await ad.envoyer(entrant.id_externe, reponse)
        except Exception:  # noqa: BLE001
            envoye = False

    # Pièces jointes (S196) : images/PDF/HTML produits par un outil pendant ce tour, relayées
    # EN PLUS du texte (jamais à sa place — le texte reste le repli honnête si l'envoi du
    # média échoue). Pas de gate : ce ne sont jamais des ACTIONS, juste la restitution du
    # résultat d'un outil déjà exécuté et confirmé plus haut dans la boucle de l'assistant.
    medias_envoyes = 0
    if envoyer and ad.configure() and medias and not repli:
        try:
            medias_envoyes = await _envoyer_medias(ad, entrant.id_externe, medias)
        except Exception:  # noqa: BLE001 — un média KO ne doit jamais faire échouer le tour
            medias_envoyes = 0

    # Réponse vocale : speech-to-speech (message entrant était audio) OU demande explicite
    # dans un texte ("fais-moi un vocal", "lis-moi ça"…). Le texte est toujours envoyé en
    # premier : il sert de transcription lisible et de repli si la brique voix est KO.
    vocalise = False
    if (transcrit is not None or _demande_vocale(entrant.texte)) and not repli and _tts_actif():
        vocalise = await _vocaliser(ad, entrant.id_externe, reponse, envoyer)

    return {"ok": True, "reponse": reponse, "utilisateur": corr.get("utilisateur"),
            "repli": repli, "envoye": envoye, "transcrit": transcrit, "vocalise": vocalise,
            "medias_envoyes": medias_envoyes}


async def sonder(reseau: str) -> dict:
    """Tire activement les messages d'un réseau (Telegram getUpdates) et les traite tous."""
    ad = adaptateurs.obtenir(reseau)
    if ad is None or not ad.configure():
        return {"ok": True, "reseau": reseau, "traites": 0, "configure": False}
    entrants = await ad.recuperer()
    comptes = []
    for e in entrants:
        if isinstance(e, adaptateurs.Callback):
            comptes.append(await traiter_callback(reseau, e))
        else:
            comptes.append(await traiter(reseau, e))
    return {"ok": True, "reseau": reseau, "traites": len(entrants),
            "autorises": sum(1 for c in comptes if c.get("ok"))}
