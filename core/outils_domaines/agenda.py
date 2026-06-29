"""Outils du domaine « agenda » (dispatch, extrait de outils.py — S115).

agenda (événements, partage, invitations) et TimeTree.
"""
import json
import agenda
from outils_communs import _confirmation


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    """Renvoie le résultat (str) si le nom appartient à ce domaine, sinon None."""
    if nom == "agenda_consulter":
        evts = await agenda.lister_evenements(registre, args.get("debut"), args.get("fin"))
        apercu = [{"event_id": e.get("id"), "titre": e.get("title"),
                   "debut": e.get("start_at"), "fin": e.get("end_at"),
                   "lieu": e.get("location"), "rappels": e.get("rappels") or []}
                  for e in evts]
        return json.dumps({"evenements": apercu, "total": len(apercu)}, ensure_ascii=False)

    if nom == "agenda_lister":
        cals = await agenda.lister_agendas(registre)
        apercu = [{"calendar_id": c.get("id"), "nom": c.get("name"),
                   "role": c.get("role"), "defaut": c.get("is_default")}
                  for c in cals]
        return json.dumps({"agendas": apercu, "total": len(apercu)}, ensure_ascii=False)

    if nom == "agenda_creer_evenement":
        titre = args.get("titre") or "Événement"
        evt = await agenda.creer_evenement(
            registre, titre, args.get("debut", ""), args.get("fin", ""),
            args.get("lieu"), args.get("description"), args.get("rappels"))
        return json.dumps({"cree": True, "event_id": evt.get("id"), "titre": evt.get("title"),
                           "debut": evt.get("start_at"), "fin": evt.get("end_at"),
                           "rappels": evt.get("rappels") or []}, ensure_ascii=False)

    if nom == "agenda_definir_rappels":
        evt = await agenda.definir_rappels(
            registre, args.get("event_id", ""), args.get("rappels") or [])
        return json.dumps({"defini": True, "event_id": evt.get("id"),
                           "rappels": evt.get("rappels") or []}, ensure_ascii=False)

    if nom == "agenda_deplacer_evenement":
        evt = await agenda.deplacer_evenement(
            registre, args.get("event_id", ""), args.get("debut", ""), args.get("fin", ""))
        return json.dumps({"deplace": True, "event_id": evt.get("id"),
                           "debut": evt.get("start_at"), "fin": evt.get("end_at")}, ensure_ascii=False)

    if nom == "agenda_supprimer_evenement":
        if not args.get("confirme"):
            return _confirmation("annuler l'événement", args.get("event_id", ""))
        ok = await agenda.supprimer_evenement(registre, args.get("event_id", ""))
        return json.dumps({"supprime": ok}, ensure_ascii=False)

    if nom == "agenda_creer_partage":
        cal = await agenda.creer_agenda_partage(
            registre, args.get("nom") or "Agenda partagé",
            args.get("description"), args.get("couleur"))
        return json.dumps({"cree": True, "calendar_id": cal.get("id"),
                           "nom": cal.get("name"), "role": cal.get("role")}, ensure_ascii=False)

    if nom == "agenda_inviter":
        cal_id = args.get("calendar_id", "")
        if not args.get("confirme"):
            return _confirmation("inviter à l'agenda partagé", cal_id)
        inv = await agenda.inviter(
            registre, cal_id, args.get("role") or "viewer",
            args.get("expire_heures", 72), args.get("email"))
        return json.dumps({"invite": True, "calendar_id": inv.get("calendar_id"),
                           "lien": inv.get("lien"), "token": inv.get("token"),
                           "role": inv.get("role"), "expire_le": inv.get("expires_at")},
                          ensure_ascii=False)

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
