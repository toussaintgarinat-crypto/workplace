"""Outils du domaine « forge » (S134 : tous migrés vers briques/forge/manifest.json).

Les outils forge_* sont désormais découverts dynamiquement via le catalogue
de capacités (core/catalogue.py). Ce dispatcher est conservé à titre de référence
mais ne traite plus aucun outil — le routage passe par _appel_dynamique.
"""


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    """Renvoie None : tous les outils forge_* sont dans le manifest (S134)."""
    return None
