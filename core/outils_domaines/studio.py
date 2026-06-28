"""Outils du domaine « studio » (dispatch, extrait de outils.py — S115).

Studio audio-séries et atelier de personnages holistiques.
"""
from outils_communs import _confirmation, _studio_appel, _personnage_holistique


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    """Renvoie le résultat (str) si le nom appartient à ce domaine, sinon None."""
    if nom == "studio_series_lister":
        return await _studio_appel(client, registre, "GET", "/series", timeout=15)

    if nom == "studio_serie_lire":
        sid = args.get("serie_id", "")
        return await _studio_appel(client, registre, "GET", f"/series/{sid}", timeout=15)

    if nom == "studio_personnages_lister":
        sid = args.get("serie_id", "")
        return await _studio_appel(client, registre, "GET", f"/series/{sid}/personnages",
                                   timeout=15)

    if nom == "studio_serie_creer":
        if not args.get("confirme"):
            return _confirmation("créer une série dans le Studio", args.get("titre", ""))
        charge = {"titre": args.get("titre", "")}
        if args.get("idee"):
            charge["idee"] = args["idee"]
        if args.get("langue"):
            charge["langue"] = args["langue"]
        if args.get("public_cible"):
            charge["cible"] = args["public_cible"]   # nom de champ côté brique
        return await _studio_appel(client, registre, "POST", "/series", charge=charge,
                                   timeout=30)

    if nom == "studio_episode_produire":
        sid = args.get("serie_id", "")
        if not args.get("confirme"):
            return _confirmation("produire l'épisode suivant de la série", sid)
        return await _studio_appel(client, registre, "POST", f"/series/{sid}/episode",
                                   charge={}, timeout=120)

    if nom == "studio_express":
        sid = args.get("serie_id", "")
        if not args.get("confirme"):
            return _confirmation("produire un épisode express (bible auto) de la série", sid)
        charge = {"idee": args["idee"]} if args.get("idee") else {}
        return await _studio_appel(client, registre, "POST", f"/series/{sid}/express",
                                   charge=charge, timeout=120)

    if nom == "studio_voix_lister":
        return await _studio_appel(client, registre, "GET", "/voix",
                                   params={"langue": args.get("langue", "fr")}, timeout=15)

    if nom == "studio_bible_proposer":
        sid = args.get("serie_id", "")
        charge = {"dimension": args.get("dimension", "")}
        if args.get("mon_idee"):
            charge["mon_idee"] = args["mon_idee"]
        return await _studio_appel(client, registre, "POST", f"/series/{sid}/proposer",
                                   charge=charge, timeout=60)

    if nom == "studio_distribution_proposer":
        sid = args.get("serie_id", "")
        charge = {}
        if args.get("combien"):
            charge["combien"] = args["combien"]
        if args.get("mon_idee"):
            charge["mon_idee"] = args["mon_idee"]
        return await _studio_appel(client, registre, "POST",
                                   f"/series/{sid}/personnages/proposer",
                                   charge=charge, timeout=60)

    if nom == "studio_bible_decider":
        sid = args.get("serie_id", "")
        if not args.get("confirme"):
            return _confirmation("figer une dimension de la bible", args.get("dimension", ""))
        charge = {"dimension": args.get("dimension", ""), "choix": args.get("choix", "")}
        return await _studio_appel(client, registre, "POST", f"/series/{sid}/decider",
                                   charge=charge, timeout=30)

    if nom == "studio_perso_creer":
        sid = args.get("serie_id", "")
        if not args.get("confirme"):
            return _confirmation("ajouter un personnage à la distribution", args.get("nom", ""))
        charge = {"nom": args.get("nom", "")}
        if args.get("role"):
            charge["role"] = args["role"]
        if args.get("description"):
            charge["description"] = args["description"]
        return await _studio_appel(client, registre, "POST", f"/series/{sid}/personnages",
                                   charge=charge, timeout=30)

    if nom == "studio_audio_produire":
        sid = args.get("serie_id", "")
        if not args.get("confirme"):
            return _confirmation("produire l'audio de l'épisode", sid)
        charge = {"n": args["n"]} if args.get("n") else {}
        return await _studio_appel(client, registre, "POST", f"/series/{sid}/audio",
                                   charge=charge, timeout=180)

    # — PERSONNAGES (atelier holistique cosmique) —
    if nom == "personnage_creer_holistique":
        return await _personnage_holistique(client, registre, args)

    # — TRANSCRIPTION (notes d'appel/réunion) —
    return None
