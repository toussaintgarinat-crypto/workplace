"""Outils du domaine « agenda » (dispatch, extrait de outils.py — S115).

Depuis S168, les 8 outils d'événements/partage (consulter, lister, creer_evenement,
definir_rappels, deplacer, supprimer, creer_partage, inviter) ne sont PLUS câblés ici :
ils sont découverts depuis le manifest agenda (capacités → surface `/service`) et routés
par `_appel_dynamique`. Ce module ne garde que les ponts encore câblés — **TimeTree** (le
login par mot de passe via LLM est sensible → hors manifest, cf. ADR agenda-surface-de-service).
Google et les étiquettes/documents/commentaires restent servis par le routeur dashboard,
pas par des outils LLM.
"""
import json
import agenda
from outils_communs import _confirmation


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    """Renvoie le résultat (str) si le nom appartient à ce domaine, sinon None."""
    if nom == "timetree_etat":
        return json.dumps(await agenda.timetree_etat(registre), ensure_ascii=False)

    if nom == "timetree_connecter":
        if not args.get("confirme"):
            return _confirmation("connecter le compte TimeTree", args.get("email", ""))
        res = await agenda.timetree_connecter(
            registre, args.get("email", ""), args.get("password", ""),
            args.get("calendar_id"))
        # On ne renvoie JAMAIS les identifiants ; juste l'état + les calendriers.
        if not res.get("connected"):
            return json.dumps({"connected": False, "erreur": res.get("erreur")}, ensure_ascii=False)
        return json.dumps({"connected": True, "calendriers": res.get("calendars", []),
                           "calendar_id": res.get("calendar_id")}, ensure_ascii=False)

    if nom == "timetree_choisir_calendrier":
        res = await agenda.timetree_choisir_calendrier(registre, args.get("calendar_id", ""))
        return json.dumps({"choisi": True, **res}, ensure_ascii=False)

    if nom == "timetree_synchroniser":
        return json.dumps(await agenda.timetree_synchroniser(registre), ensure_ascii=False)

    if nom == "timetree_deconnecter":
        if not args.get("confirme"):
            return _confirmation("déconnecter TimeTree", "TimeTree")
        ok = await agenda.timetree_deconnecter(registre)
        return json.dumps({"deconnecte": ok}, ensure_ascii=False)
    return None
