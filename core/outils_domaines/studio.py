"""Outils du domaine « studio » (dispatch, extrait de outils.py — S115).

S134 : tous les outils studio_* et personnages_fiches_lister/personnage_importer_serie
migrés vers briques/studio/manifest.json et briques/personnages/manifest.json.

Les helpers personnage_creer_holistique reste statique (logique multi-étapes complexe).
"""
from outils_communs import _personnage_holistique


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    """Renvoie le résultat (str) si le nom appartient à ce domaine, sinon None."""
    if nom == "personnage_creer_holistique":
        return await _personnage_holistique(client, registre, args)
    return None
