"""Aspects astrologiques — majeurs + mineurs entre tous les points.

Fonctions pures. Orbes par type de point (luminaire/planète/point sensible).
"""
from __future__ import annotations

ASPECTS = {
    "conjonction":   {"angle": 0,   "type": "majeur"},
    "opposition":     {"angle": 180, "type": "majeur"},
    "trigone":        {"angle": 120, "type": "majeur"},
    "carre":          {"angle": 90,  "type": "majeur"},
    "sextile":        {"angle": 60,  "type": "majeur"},
    "semi_sextile":   {"angle": 30,  "type": "mineur"},
    "semi_carre":     {"angle": 45,  "type": "mineur"},
    "quintile":       {"angle": 72,  "type": "mineur"},
    "sesquicarre":    {"angle": 135, "type": "mineur"},
    "quinconce":      {"angle": 150, "type": "mineur"},
}

ORBES_BASE = {
    "majeur_luminaire": 10,
    "majeur_planete":   8,
    "majeur_point":     5,
    "mineur":           3,
}

_LUMINAIRES = {"Soleil", "Lune"}
_PLANETES = {"Mercure", "Vénus", "Mars", "Jupiter", "Saturne",
             "Uranus", "Neptune", "Pluton"}
# Tout le reste = point sensible (Asc, MC, Desc, IC, Nœuds, Chiron, Lilith)


def _type_point(nom: str) -> str:
    if nom in _LUMINAIRES:
        return "luminaire"
    if nom in _PLANETES:
        return "planete"
    return "point"


def _orbe_point(nom: str, type_aspect: str) -> int:
    if type_aspect == "mineur":
        return ORBES_BASE["mineur"]
    # Majeur
    tp = _type_point(nom)
    if tp == "luminaire":
        return ORBES_BASE["majeur_luminaire"]
    if tp == "planete":
        return ORBES_BASE["majeur_planete"]
    return ORBES_BASE["majeur_point"]


def aspects(points: dict[str, dict], orbes: dict | None = None) -> list[dict]:
    """Calcule les aspects entre tous les points. Tri par exactitude décroissante."""
    if orbes is None:
        orbes = ORBES_BASE
    noms = list(points.keys())
    resultats = []
    for i, a in enumerate(noms):
        for b in noms[i + 1:]:
            lon_a = points[a]["longitude"] % 360
            lon_b = points[b]["longitude"] % 360
            ecart_brut = abs(lon_a - lon_b) % 360
            ecart = min(ecart_brut, 360 - ecart_brut)
            for nom_aspect, info in ASPECTS.items():
                angle = info["angle"]
                diff = abs(ecart - angle)
                if diff > 180:
                    diff = 360 - diff
                # Orbe = min des orbes des deux points
                orbe_max = min(_orbe_point(a, info["type"]),
                               _orbe_point(b, info["type"]))
                if diff <= orbe_max:
                    resultats.append({
                        "aspect": nom_aspect,
                        "type": info["type"],
                        "point_a": a,
                        "point_b": b,
                        "angle_exact": float(angle),
                        "angle_reel": round(ecart, 4),
                        "orb": round(diff, 4),
                        "orbe_max": orbe_max,
                        "exactitude": round(1 - diff / orbe_max, 4),
                    })
    resultats.sort(key=lambda x: x["exactitude"], reverse=True)
    return resultats


def filtrer_par_type(aspects: list, type_: str) -> list:
    """Filtre 'majeur' / 'mineur' / 'tous'."""
    if type_ == "tous":
        return aspects
    return [a for a in aspects if a["type"] == type_]
