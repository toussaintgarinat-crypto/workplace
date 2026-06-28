"""Outils du domaine « usine » (dispatch, extrait de outils.py — S115).

usine à applications : livrer / décrocher / reprendre une entreprise.
"""
import json
import cycle_de_vie
import orchestrateur
from outils_communs import _confirmation, _livrer


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    """Renvoie le résultat (str) si le nom appartient à ce domaine, sinon None."""
    if nom == "livrer_entreprise":
        cible = args.get("nom_entreprise") or "entreprise"
        if not args.get("confirme"):
            return _confirmation("livrer", cible)
        return await _livrer(registre, args)

    if nom == "decrocher_entreprise":
        lid = args.get("livraison_id", "")
        cible = (orchestrateur.lire_livraison(lid) or {}).get("nom_entreprise") or lid
        if not args.get("confirme"):
            return _confirmation("décrocher", cible)
        return json.dumps(await cycle_de_vie.decrocher(registre, lid), ensure_ascii=False)

    if nom == "reprendre_entreprise":
        lid = args.get("livraison_id", "")
        cible = (orchestrateur.lire_livraison(lid) or {}).get("nom_entreprise") or lid
        if not args.get("confirme"):
            return _confirmation("reprendre", cible)
        return json.dumps(await cycle_de_vie.reprendre(registre, lid), ensure_ascii=False)
    return None
