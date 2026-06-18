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

_REPLI = ("Désolé, je n'arrive pas à joindre l'assistant pour l'instant. "
          "Réessaie dans un petit moment.")


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

    return {"ok": True, "reponse": reponse, "utilisateur": corr.get("utilisateur"),
            "repli": repli, "envoye": envoye}


async def sonder(reseau: str) -> dict:
    """Tire activement les messages d'un réseau (Telegram getUpdates) et les traite tous."""
    ad = adaptateurs.obtenir(reseau)
    if ad is None or not ad.configure():
        return {"ok": True, "reseau": reseau, "traites": 0, "configure": False}
    entrants = await ad.recuperer()
    comptes = [await traiter(reseau, e) for e in entrants]
    return {"ok": True, "reseau": reseau, "traites": len(entrants),
            "autorises": sum(1 for c in comptes if c.get("ok"))}
