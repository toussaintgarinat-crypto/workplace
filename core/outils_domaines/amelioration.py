"""Outils du domaine « amelioration » (dispatch, extrait de outils.py — S115).

auto-amélioration & curateur pilotés en conversation (gate humain).
"""
import json
from outils_communs import _confirmation


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    """Renvoie le résultat (str) si le nom appartient à ce domaine, sinon None."""
    # — AUTO-AMÉLIORATION pilotée en conversation (S75) —
    # Le cycle S68→S70 (mesure → propose → gate humain) devient pilotable EN PARLANT
    # (Telegram/chat). Le gate humain = la confirmation DANS la conversation
    # (confirme=true) : on PROPOSE, et on n'APPLIQUE que sur accord. Une capacité
    # retenue reste une SPÉC à implémenter — jamais auto-câblée (honnêteté S70).
    # Import LOCAL : curateur importe outils → on casse le cycle.
    if nom == "amelioration_etat":
        import amelioration
        import curateur
        return json.dumps({
            "prompt": amelioration.lister(),
            "capacites_proposees": curateur.lister_capacites(),
        }, ensure_ascii=False)

    if nom == "curateur_lancer":
        if not args.get("confirme"):
            return _confirmation("lancer un cycle de curation", "l'assistant lui-même")
        import curateur
        return json.dumps(await curateur.curer(registre, forcer=True), ensure_ascii=False)

    if nom == "amelioration_evaluer":
        if not args.get("confirme"):
            return _confirmation("évaluer (A/B) une proposition de prompt", args.get("id", "?"))
        import amelioration
        return json.dumps(await amelioration.evaluer(args.get("id", "")), ensure_ascii=False)

    if nom == "amelioration_decider":
        decision = (args.get("decision") or "").lower()
        if decision not in ("valider", "appliquer", "rejeter", "desactiver"):
            return "decision doit valoir : valider, appliquer, rejeter ou desactiver."
        cible = "prompt fondateur" if decision == "desactiver" else args.get("id", "?")
        if not args.get("confirme"):
            return _confirmation(f"{decision} l'amélioration de prompt", cible)
        import amelioration
        if decision == "desactiver":
            return json.dumps(amelioration.desactiver(), ensure_ascii=False)
        id_ = args.get("id", "")
        if decision == "valider":
            return json.dumps(amelioration.valider(id_), ensure_ascii=False)
        if decision == "rejeter":
            return json.dumps(amelioration.rejeter(id_), ensure_ascii=False)
        # appliquer = gate en un geste depuis le chat : valider (si besoin) puis activer.
        amelioration.valider(id_)
        return json.dumps(amelioration.appliquer(id_), ensure_ascii=False)

    if nom == "capacite_decider":
        decision = (args.get("decision") or "").lower()
        if decision not in ("retenir", "rejeter"):
            return "decision doit valoir : retenir ou rejeter."
        if not args.get("confirme"):
            return _confirmation(f"{decision} le brouillon de capacité", args.get("id", "?"))
        import curateur
        id_ = args.get("id", "")
        res = (curateur.retenir_capacite(id_) if decision == "retenir"
               else curateur.rejeter_capacite(id_))
        return json.dumps(res, ensure_ascii=False)
    return None
