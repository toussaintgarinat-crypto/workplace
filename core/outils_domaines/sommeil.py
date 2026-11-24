"""Outils du domaine « sommeil » (S243) : l'assistant voit, réveille et endort les briques.

Outils CÂBLÉS dans le Cœur (pas des capacités de manifeste) : ils agissent sur l'infrastructure
(Docker), pas sur une route HTTP d'une brique — il n'y a donc pas de brique pour les déclarer.
Les garde-fous (opt-in par manifeste, liste noire) vivent dans `sommeil.py`, pas ici.
"""
import json

import sommeil


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    """Renvoie le résultat (str) si le nom appartient à ce domaine, sinon None."""
    if nom not in ("brique_etat", "brique_reveiller", "brique_endormir"):
        return None
    brique = ((args or {}).get("brique") or "").strip()

    if nom == "brique_etat":
        if brique:
            s = await sommeil.etat(registre, brique)
            res = {"brique": brique, "etat": s}
            if s == "inconnue":
                res["message"] = (f"« {brique} » n'a pas d'option sommeil, ou son conteneur est "
                                  "introuvable : son état de sommeil n'est pas connu.")
            return _j(res)
        return _j({"briques": [{"brique": n, "etat": await sommeil.etat(registre, n)}
                               for n in sommeil.briques_endormissables(registre)]})

    if not brique:
        return "Précise la brique (paramètre « brique »), ex. brique_reveiller(brique=\"geo\")."
    if nom == "brique_reveiller":
        return _j(await sommeil.reveiller(registre, brique))
    return _j(await sommeil.endormir(registre, brique))
