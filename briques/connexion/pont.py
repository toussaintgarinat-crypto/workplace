"""Le pont — orchestration d'un message entrant jusqu'à la réponse de l'assistant.

Pour chaque message reçu d'un réseau :
  1. on vérifie le CONSENTEMENT (correspondance) — un inconnu reçoit un accueil, pas l'assistant ;
  2. on charge l'historique de l'interlocuteur (conversations) ;
  3. on construit les messages (système « qui parle » + historique + nouveau message) ;
  4. on interroge l'assistant du Cœur (client_assistant, flux SSE) ;
  5. on persiste le tour et on renvoie la réponse sur le réseau d'origine.

Repli HONNÊTE partout : assistant injoignable → message d'excuse clair (jamais une fausse
réponse) ; réseau injoignable à l'envoi → on journalise sans rien perdre en silence.
"""
import os

import adaptateurs
import client_assistant
import conversations
import correspondance
import voix

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


def _tts_actif() -> bool:
    """Réponse vocale activée ? (env `CONNEXION_TTS`, défaut on)."""
    return str(os.getenv("CONNEXION_TTS", "1")).strip().lower() in ("1", "true", "oui", "on")


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


async def traiter(reseau: str, entrant, *, envoyer: bool = True) -> dict:
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

    historique = conversations.charger(reseau, entrant.id_externe)
    messages = _construire(reseau, entrant, corr, historique)

    verbeux = str(os.getenv("CONNEXION_VERBEUX", "0")).strip() in ("1", "true", "oui")
    repli = False
    try:
        reponse = await client_assistant.converser(messages, verbeux=verbeux)
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

    # Boucle speech-to-speech : si l'interlocuteur a PARLÉ (message vocal transcrit), on
    # répond AUSSI en vocal (le texte reste envoyé : il sert de transcription lisible).
    vocalise = False
    if transcrit is not None and not repli and _tts_actif():
        vocalise = await _vocaliser(ad, entrant.id_externe, reponse, envoyer)

    return {"ok": True, "reponse": reponse, "utilisateur": corr.get("utilisateur"),
            "repli": repli, "envoye": envoye, "transcrit": transcrit, "vocalise": vocalise}


async def sonder(reseau: str) -> dict:
    """Tire activement les messages d'un réseau (Telegram getUpdates) et les traite tous."""
    ad = adaptateurs.obtenir(reseau)
    if ad is None or not ad.configure():
        return {"ok": True, "reseau": reseau, "traites": 0, "configure": False}
    entrants = await ad.recuperer()
    comptes = [await traiter(reseau, e) for e in entrants]
    return {"ok": True, "reseau": reseau, "traites": len(entrants),
            "autorises": sum(1 for c in comptes if c.get("ok"))}
